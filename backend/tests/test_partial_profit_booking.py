"""Partial profit booking: sell part of a position at a first target, trail the rest.

The property most worth pinning is the money, not the mechanics. A partial
exit splits one entry's charges across two Trade rows, and the paper cash
ledger derives locked capital from what the position still holds — get
either wrong and realised P&L and cash drift quietly, poisoning every
statistic built on them. So beyond "did it sell half", these tests check that
the two Trade rows' charges add up to exactly what the three orders paid, and
that cash always equals starting capital plus the Trade rows' net P&L.

Prices are driven the way the paper broker reads them in tests: through the
cached `quotes` row (no Kite session), so check_exits() and the simulated
fill see the same price.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from swing_trade_ml.brokers import OrderResult
from swing_trade_ml.brokers.kite import kite_broker
from swing_trade_ml.brokers.paper import paper_broker
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import (
    ExitReason,
    OrderStatus,
    PositionStatus,
    SignalType,
    TransactionType,
)
from swing_trade_ml.db.models.market import Instrument, Quote
from swing_trade_ml.db.models.trading import Order, Position, Signal, Strategy, Trade
from swing_trade_ml.services import execution
from swing_trade_ml.services.backtest import (
    BacktestTrade,
    _charges,
    _close_position,
    _maybe_scale_out,
    _OpenPosition,
)
from swing_trade_ml.services.exit_policy import (
    DEFAULT_TIME_STOP_DAYS,
    ExitPolicy,
    exit_policy_for,
    exit_policy_for_strategy,
    scale_out_quantity,
)
from swing_trade_ml.services.portfolio import mark_to_market, portfolio_value_and_cash
from swing_trade_ml.services.risk import open_exposure_value

BARRIER_PARAMS = {"scale_out_at_pct": 0.05, "scale_out_fraction": 0.5, "time_stop_days": 30}
# An explicit opt-out: the one way a strategy row can still refuse partial
# booking now that it is the default.
NO_SCALE_OUT_PARAMS = {"scale_out_at_pct": 0}


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    """No Kite session, so every price comes from the quotes row; and capture
    notifications instead of sending them."""
    monkeypatch.setattr(kite_broker, "_token_loaded", False)
    sent: list[str] = []
    monkeypatch.setattr(execution.notifier, "send_sync", lambda text, event=None: sent.append(text) or True)
    return sent


def _open(
    db,
    *,
    params: dict | None = None,
    quantity: int = 20,
    price: float = 1000.0,
    stop_loss: float = 900.0,
    take_profit: float = 1080.0,
    execution_mode: str = "auto",
    symbol: str = "TITAN",
) -> Position:
    inst = Instrument(
        instrument_token=abs(hash(symbol)) % 1_000_000, tradingsymbol=symbol, exchange="NSE",
        is_watchlisted=True,
    )
    strategy = Strategy(
        name=f"strat_{symbol}", strategy_type="ml_swing", mode="paper", is_active=True,
        execution_mode=execution_mode, params=params or {},
    )
    db.add_all([inst, strategy])
    db.flush()
    db.add(Quote(instrument_id=inst.id, last_price=price, ts=datetime.now(UTC)))
    signal = Signal(
        strategy_id=strategy.id, instrument_id=inst.id, signal_type=SignalType.BUY, mode="paper",
        price=price, confidence=0.7, stop_loss=stop_loss, take_profit=take_profit,
        generated_at=datetime.now(UTC),
    )
    db.add(signal)
    db.commit()

    if execution_mode == "advisory":
        return execution.manual_open_position(
            db, strategy, inst, quantity, price, stop_loss=stop_loss, take_profit=take_profit
        )
    position = execution.open_position(db, strategy, inst, signal, quantity)
    assert position is not None
    return position


def _tick(db, position: Position, price: float) -> list[Trade]:
    quote = db.execute(select(Quote).where(Quote.instrument_id == position.instrument_id)).scalar_one()
    quote.last_price = price
    db.commit()
    return execution.check_exits(db)


def _trades(db, position: Position) -> list[Trade]:
    return list(
        db.execute(select(Trade).where(Trade.position_id == position.id).order_by(Trade.id)).scalars()
    )


def _orders(db, position: Position) -> list[Order]:
    return list(
        db.execute(
            select(Order).where(Order.instrument_id == position.instrument_id).order_by(Order.id)
        ).scalars()
    )


def _all_net_pnl(db) -> float:
    return float(db.execute(select(func.coalesce(func.sum(Trade.net_pnl), 0.0))).scalar_one())


# -------------------------------------------------------------- defaults --


def test_a_plain_strategy_row_scales_out_at_the_first_target(db_session):
    """The change that finally switches partial booking on. Every strategy in
    the running bot carries no scale-out params at all, so while this had to
    be opted into row by row it had never executed once — half of a 20-share
    position is sold here purely from the settings default."""
    position = _open(db_session, params={})
    closed = _tick(
        db_session, position, position.entry_price * (1 + settings.ML_FIRST_TARGET_PCT)
    )

    assert [t.exit_reason for t in closed] == [ExitReason.SCALE_OUT]
    assert closed[0].quantity == 10
    assert position.status == PositionStatus.OPEN
    assert position.quantity == 10
    assert position.scaled_out_at is not None


def test_the_first_target_is_five_percent_above_entry(db_session):
    """One tick short of +5% sells nothing; the tick that reaches it sells
    half. Pins the level itself, not merely that something eventually fires.

    Measured from the filled entry price rather than the signalled one: the
    paper broker charges slippage, so 1000.0 in becomes 1000.5 held, and the
    trigger moves with it.
    """
    assert settings.ML_FIRST_TARGET_PCT == 0.05
    position = _open(db_session, params={})
    trigger = position.entry_price * (1 + settings.ML_FIRST_TARGET_PCT)

    assert _tick(db_session, position, trigger - 0.01) == []
    assert position.quantity == 20

    closed = _tick(db_session, position, trigger)
    assert [t.exit_reason for t in closed] == [ExitReason.SCALE_OUT]
    assert position.quantity == 10


def test_a_plain_strategy_row_is_closed_by_the_thirty_day_time_stop(db_session):
    """60 days was four times the model's 15-trading-day horizon: a position
    held that long is answering a question the model was never asked."""
    position = _open(db_session, params={})
    position.entry_at = datetime.now(UTC) - timedelta(days=29)
    db_session.commit()
    assert _tick(db_session, position, 1010.0) == []

    position.entry_at = datetime.now(UTC) - timedelta(days=30)
    db_session.commit()
    closed = _tick(db_session, position, 1010.0)

    assert len(closed) == 1
    assert closed[0].exit_reason == ExitReason.TIME_STOP
    assert closed[0].quantity == 20
    assert position.status == PositionStatus.CLOSED


def test_an_explicit_zero_still_turns_scale_out_off(db_session):
    position = _open(db_session, params=NO_SCALE_OUT_PARAMS)
    closed = _tick(db_session, position, 1060.0)

    assert closed == []
    assert _trades(db_session, position) == []
    assert position.status == PositionStatus.OPEN
    assert position.quantity == 20
    assert position.scaled_out_at is None


# ------------------------------------------------------------ regression --


def test_full_close_arithmetic_is_unchanged(db_session):
    """One exit, one Trade, charged the entry charges plus the exit's own —
    the original formula, for a position that never scaled out."""
    position = _open(db_session, params={})
    entry_charges = position.total_charges
    closed = _tick(db_session, position, 1085.0)

    assert len(closed) == 1
    trade = closed[0]
    buy, sell = _orders(db_session, position)
    assert trade.exit_reason == ExitReason.TARGET_HIT
    assert trade.charges == pytest.approx(entry_charges + sell.brokerage + sell.taxes)
    assert trade.gross_pnl == pytest.approx((sell.average_price - buy.average_price) * 20)
    assert position.realized_pnl == pytest.approx(trade.net_pnl)
    assert position.total_charges == pytest.approx(trade.charges)
    assert position.quantity == 20


# ------------------------------------------------------------- scale out --


def test_first_target_sells_half_and_raises_the_stop_to_entry(db_session, _offline):
    position = _open(db_session, params=BARRIER_PARAMS)
    entry = position.entry_price

    closed = _tick(db_session, position, 1060.0)  # +6%: past +5%, short of the 1080 target

    assert len(closed) == 1
    trade = closed[0]
    assert trade.exit_reason == ExitReason.SCALE_OUT
    assert trade.quantity == 10
    assert _trades(db_session, position) == [trade]

    assert position.status == PositionStatus.OPEN
    assert position.quantity == 10
    assert position.initial_quantity == 20
    assert position.scaled_out_at is not None
    # The trail from a 900 stop would only reach ~959.5 here, so this is the
    # scale-out's own raise, not the trailing stop.
    assert position.stop_loss == pytest.approx(entry)
    assert position.exit_reason is None

    message = _offline[-1]
    assert "Sold half of TITAN at +" in message
    assert "moved its sell-if-wrong price up to what you paid" in message


def test_then_final_target_closes_the_rest_with_charges_split_correctly(db_session):
    position = _open(db_session, params=BARRIER_PARAMS)
    starting = settings.PAPER_STARTING_CAPITAL

    _tick(db_session, position, 1060.0)
    closed = _tick(db_session, position, 1085.0)

    assert len(closed) == 1
    first, second = _trades(db_session, position)
    assert second.exit_reason == ExitReason.TARGET_HIT
    assert second.quantity == 10
    assert position.status == PositionStatus.CLOSED
    assert position.quantity == 20  # a closed row reports the position's size

    buy, sell_half, sell_rest = _orders(db_session, position)
    assert (buy.quantity, sell_half.quantity, sell_rest.quantity) == (20, 10, 10)
    entry_charges = buy.brokerage + buy.taxes
    exit_charges = (sell_half.brokerage + sell_half.taxes) + (sell_rest.brokerage + sell_rest.taxes)

    # Each slice carries half the entry charges plus its own exit charges —
    # and together, every charge exactly once.
    assert first.charges == pytest.approx(entry_charges / 2 + sell_half.brokerage + sell_half.taxes)
    assert second.charges == pytest.approx(entry_charges / 2 + sell_rest.brokerage + sell_rest.taxes)
    assert first.charges + second.charges == pytest.approx(entry_charges + exit_charges)

    assert position.realized_pnl == pytest.approx(first.net_pnl + second.net_pnl)
    assert position.total_charges == pytest.approx(entry_charges + exit_charges)

    # Cash: starting capital, plus every rupee in and out of the three orders,
    # equals starting capital plus the Trade rows' net P&L.
    cash_by_orders = (
        starting
        - (buy.average_price * 20 + entry_charges)
        + (sell_half.average_price * 10 - sell_half.brokerage - sell_half.taxes)
        + (sell_rest.average_price * 10 - sell_rest.brokerage - sell_rest.taxes)
    )
    assert paper_broker.get_available_cash(db_session) == pytest.approx(cash_by_orders)
    assert paper_broker.get_available_cash(db_session) == pytest.approx(starting + _all_net_pnl(db_session))


def test_cash_is_right_while_the_remainder_is_still_open(db_session):
    """The drift case: after the half-sale, locked capital must be the held
    half's cost plus its share of entry charges — not the whole entry."""
    position = _open(db_session, params=BARRIER_PARAMS)
    _tick(db_session, position, 1060.0)

    buy, sell_half = _orders(db_session, position)
    expected = (
        settings.PAPER_STARTING_CAPITAL
        - (buy.average_price * 20 + buy.brokerage + buy.taxes)
        + (sell_half.average_price * 10 - sell_half.brokerage - sell_half.taxes)
    )
    assert paper_broker.get_available_cash(db_session) == pytest.approx(expected)


def test_valuation_and_exposure_count_only_the_shares_still_held(db_session):
    position = _open(db_session, params=BARRIER_PARAMS)
    _tick(db_session, position, 1060.0)

    quote = db_session.execute(
        select(Quote).where(Quote.instrument_id == position.instrument_id)
    ).scalar_one()
    quote.last_price = 1070.0
    db_session.commit()
    assert mark_to_market(db_session, "paper") == 1

    assert position.unrealized_pnl == pytest.approx((1070.0 - position.entry_price) * 10)
    total, cash = portfolio_value_and_cash(db_session, "paper")
    assert total - cash == pytest.approx(1070.0 * 10)
    assert open_exposure_value(
        db_session, "paper", position.strategy_id, position.instrument_id
    ) == pytest.approx(position.entry_price * 10)


def test_scale_out_happens_once_only(db_session):
    position = _open(db_session, params=BARRIER_PARAMS)
    _tick(db_session, position, 1060.0)
    _tick(db_session, position, 1062.0)
    _tick(db_session, position, 1055.0)

    trades = _trades(db_session, position)
    assert len(trades) == 1
    assert position.quantity == 10


def test_a_tick_at_the_final_target_sells_everything_in_one_order(db_session):
    """Gapping straight past both targets is a single full exit — one
    depository fee, not a half-sale immediately followed by the other half."""
    position = _open(db_session, params=BARRIER_PARAMS)
    closed = _tick(db_session, position, 1090.0)

    assert len(closed) == 1
    assert closed[0].exit_reason == ExitReason.TARGET_HIT
    assert closed[0].quantity == 20
    assert position.scaled_out_at is None


def test_remainder_stopped_at_entry_keeps_cash_consistent(db_session):
    position = _open(db_session, params=BARRIER_PARAMS)
    _tick(db_session, position, 1060.0)
    closed = _tick(db_session, position, position.entry_price - 1)

    assert len(closed) == 1
    assert closed[0].exit_reason == ExitReason.STOP_LOSS_HIT
    assert position.status == PositionStatus.CLOSED
    assert paper_broker.get_available_cash(db_session) == pytest.approx(
        settings.PAPER_STARTING_CAPITAL + _all_net_pnl(db_session)
    )


def test_skipped_below_the_minimum_position_value(db_session):
    """15 shares at 1,060 is 15,900 — under 16,000, so a second flat
    depository fee is not worth paying."""
    assert settings.SCALE_OUT_MIN_POSITION_INR == 16_000.0
    position = _open(db_session, params=BARRIER_PARAMS, quantity=15)
    assert _tick(db_session, position, 1060.0) == []
    assert position.quantity == 15


def test_skipped_for_a_one_share_position(db_session):
    position = _open(
        db_session, params=BARRIER_PARAMS, quantity=1, price=20_000.0, stop_loss=18_000.0,
        take_profit=21_600.0,
    )
    assert _tick(db_session, position, 21_200.0) == []
    assert position.quantity == 1
    assert position.scaled_out_at is None


def test_time_stop_days_param_is_honoured(db_session):
    position = _open(db_session, params=BARRIER_PARAMS)
    position.entry_at = datetime.now(UTC) - timedelta(days=29)
    db_session.commit()
    assert _tick(db_session, position, 1010.0) == []

    position.entry_at = datetime.now(UTC) - timedelta(days=30)
    db_session.commit()
    closed = _tick(db_session, position, 1010.0)
    assert [t.exit_reason for t in closed] == [ExitReason.TIME_STOP]


def test_advisory_strategy_is_never_scaled_out_automatically(db_session, _offline):
    position = _open(db_session, params=BARRIER_PARAMS, execution_mode="advisory")
    sent_before = len(_offline)

    assert _tick(db_session, position, 1060.0) == []
    assert position.quantity == 20
    assert _orders(db_session, position) == []
    assert len(_offline) == sent_before


def test_no_second_half_sell_while_one_is_still_pending(db_session):
    """Live orders fill later, via reconciliation. Until then the exit job
    must not send another half-sell every minute."""
    position = _open(db_session, params=BARRIER_PARAMS)
    db_session.add(
        Order(
            position_id=position.id, strategy_id=position.strategy_id,
            instrument_id=position.instrument_id, mode="paper",
            transaction_type=TransactionType.SELL, quantity=10, status=OrderStatus.PENDING,
            placed_at=datetime.now(UTC), broker_order_id="LIVE-123",
        )
    )
    db_session.commit()

    assert _tick(db_session, position, 1060.0) == []
    assert position.quantity == 20


def test_close_position_quantity_at_or_above_held_is_a_full_close(db_session):
    position = _open(db_session, params={})
    trade = execution.close_position(db_session, position, None, ExitReason.MANUAL, quantity=50)
    assert trade is not None and trade.quantity == 20
    assert position.status == PositionStatus.CLOSED


def test_close_position_rejects_a_non_positive_quantity(db_session):
    position = _open(db_session, params={})
    with pytest.raises(ValueError):
        execution.close_position(db_session, position, None, ExitReason.MANUAL, quantity=0)


# --------------------------------------------------------- reconciliation --


def test_reconciled_partial_exit_keeps_the_position_open(db_session):
    position = _open(db_session, params=BARRIER_PARAMS)
    entry_charges = position.total_charges
    order = Order(
        position_id=position.id, strategy_id=position.strategy_id,
        instrument_id=position.instrument_id, mode="paper",
        transaction_type=TransactionType.SELL, quantity=10, status=OrderStatus.COMPLETE,
        placed_at=datetime.now(UTC), filled_at=datetime.now(UTC), broker_order_id="LIVE-1",
    )
    db_session.add(order)
    db_session.commit()
    result = OrderResult(
        broker_order_id="LIVE-1", status=OrderStatus.COMPLETE, filled_quantity=10,
        average_price=1060.0, brokerage=0.0, taxes=27.0,
    )

    execution._finish_reconciled_order(db_session, order, result)
    execution._finish_reconciled_order(db_session, order, result)  # idempotent

    trades = _trades(db_session, position)
    assert len(trades) == 1
    assert trades[0].exit_reason == ExitReason.SCALE_OUT
    assert trades[0].charges == pytest.approx(entry_charges / 2 + 27.0)
    assert position.status == PositionStatus.OPEN
    assert position.quantity == 10
    assert position.stop_loss == pytest.approx(position.entry_price)

    final = Order(
        position_id=position.id, strategy_id=position.strategy_id,
        instrument_id=position.instrument_id, mode="paper",
        transaction_type=TransactionType.SELL, quantity=10, status=OrderStatus.COMPLETE,
        placed_at=datetime.now(UTC), filled_at=datetime.now(UTC), broker_order_id="LIVE-2",
    )
    db_session.add(final)
    db_session.commit()
    execution._finish_reconciled_order(
        db_session, final,
        OrderResult(
            broker_order_id="LIVE-2", status=OrderStatus.COMPLETE, filled_quantity=10,
            average_price=1085.0, brokerage=0.0, taxes=28.0,
        ),
    )

    first, second = _trades(db_session, position)
    assert position.status == PositionStatus.CLOSED
    assert first.charges + second.charges == pytest.approx(entry_charges + 27.0 + 28.0)


# ---------------------------------------------------------------- policy --


def test_exit_policy_defaults_are_the_traded_policy():
    """Absent params mean the policy the model was scored on, not the feature
    switched off. The old reading is why partial booking never ran: every
    strategy row in the bot carries no params at all."""
    policy = exit_policy_for({})
    assert policy.scale_out_enabled is True
    assert policy.scale_out_at_pct == settings.ML_FIRST_TARGET_PCT
    assert policy.time_stop_days == DEFAULT_TIME_STOP_DAYS == 30
    assert exit_policy_for(None) == policy
    assert exit_policy_for({"scale_out_at_pct": None}) == policy


def test_a_long_horizon_strategy_does_not_inherit_the_swing_policy():
    """A 250-trading-day thesis targeting +30% must not book half at +5% or be
    closed at 30 days. Making the swing policy the default put every strategy
    carrying no params on it, and the backtest path is not advisory-gated, so
    long-term backtests would have quietly run a different strategy."""
    from swing_trade_ml.strategies.long_term_value import (
        LONG_TERM_HORIZON_DAYS,
        LongTermValueStrategy,
    )

    policy = exit_policy_for(LongTermValueStrategy.default_params)

    assert policy.scale_out_enabled is False
    assert policy.time_stop_days > LONG_TERM_HORIZON_DAYS


def test_a_strategy_row_resolves_its_own_classs_policy():
    """Strategy.params holds only what was explicitly set on the row, and the
    rows in the running bot were created carrying none of these keys — so
    reading the row alone hands a one-year thesis the swing trade's defaults,
    however carefully the class declares otherwise."""
    from swing_trade_ml.strategies.long_term_value import LONG_TERM_TIME_STOP_DAYS

    row = Strategy(name="lt", strategy_type="long_term_value", mode="paper", params={})

    policy = exit_policy_for_strategy(row)

    assert policy.scale_out_enabled is False
    assert policy.time_stop_days == LONG_TERM_TIME_STOP_DAYS


def test_a_swing_row_still_gets_the_swing_policy():
    row = Strategy(name="sw", strategy_type="ml_swing", mode="paper", params={})

    policy = exit_policy_for_strategy(row)

    assert policy.scale_out_at_pct == settings.ML_FIRST_TARGET_PCT
    assert policy.time_stop_days == DEFAULT_TIME_STOP_DAYS


def test_exit_policy_malformed_values_switch_scale_out_off():
    assert exit_policy_for({"scale_out_at_pct": 0.05, "scale_out_fraction": 1.0}).scale_out_enabled is False
    assert exit_policy_for({"scale_out_at_pct": "abc"}).scale_out_enabled is False
    assert exit_policy_for({"scale_out_at_pct": -0.05}).scale_out_enabled is False
    assert exit_policy_for({"time_stop_days": 0}).time_stop_days == DEFAULT_TIME_STOP_DAYS


def test_scale_out_quantity_rounds_down_and_never_sells_everything():
    policy = ExitPolicy(scale_out_at_pct=0.05, scale_out_fraction=0.5)
    kwargs = {"entry_price": 1000.0, "price": 1050.0, "already_scaled_out": False, "min_position_value": 0}
    assert scale_out_quantity(policy, quantity=21, **kwargs) == 10
    assert scale_out_quantity(policy, quantity=1, **kwargs) == 0
    assert scale_out_quantity(policy, quantity=3, **kwargs) == 1
    assert scale_out_quantity(ExitPolicy(0.05, 0.29), quantity=100, **kwargs) == 29
    assert scale_out_quantity(policy, quantity=20, **(kwargs | {"price": 1049.0})) == 0
    assert scale_out_quantity(policy, quantity=20, **(kwargs | {"already_scaled_out": True})) == 0


# -------------------------------------------------------------- backtest --


def _backtest_position(quantity=20, entry=1000.0, stop=900.0) -> tuple[_OpenPosition, float]:
    brokerage, taxes = _charges(entry * quantity, "BUY")
    pos = _OpenPosition(
        instrument_id=1, symbol="TITAN", quantity=quantity, entry_price=entry,
        entry_date=date(2024, 1, 1), stop_loss=stop, take_profit=1080.0,
        charges_so_far=brokerage + taxes,
    )
    return pos, entry * quantity + brokerage + taxes


def test_backtest_scale_out_writes_two_trades_with_the_same_arithmetic():
    policy = exit_policy_for(BARRIER_PARAMS)
    pos, entry_cost = _backtest_position()
    entry_charges = pos.charges_so_far
    trades: list[BacktestTrade] = []

    proceeds = _maybe_scale_out(pos, policy, bar_high=1055.0, trades=trades, day=date(2024, 1, 5))
    assert len(trades) == 1
    assert trades[0].exit_reason == "SCALE_OUT"
    assert trades[0].quantity == 10
    assert pos.quantity == 10
    assert pos.scaled_out is True
    assert pos.stop_loss == 1000.0
    assert pos.charges_so_far == pytest.approx(entry_charges / 2)

    # Once only.
    assert _maybe_scale_out(pos, policy, bar_high=1070.0, trades=trades, day=date(2024, 1, 6)) == 0.0

    proceeds += _close_position(pos, 1080.0, trades, "TARGET_HIT", date(2024, 1, 9))
    assert [t.quantity for t in trades] == [10, 10]

    # Same apportionment as the live path: entry charges split by quantity,
    # every charge counted once.
    _, exit1 = _charges(trades[0].exit_price * 10, "SELL")
    _, exit2 = _charges(trades[1].exit_price * 10, "SELL")
    assert sum(t.charges for t in trades) == pytest.approx(entry_charges + exit1 + exit2, abs=0.02)
    # The cash ledger nets to the trades' P&L (to the 2dp trades are rounded to).
    assert proceeds - entry_cost == pytest.approx(sum(t.net_pnl for t in trades), abs=0.05)


def test_backtest_scales_out_on_the_default_policy():
    """The backtest reads the same policy object as the live exit check, so a
    changed default has to move both at once — otherwise a backtest stops
    describing what the bot would actually have done."""
    pos, _ = _backtest_position()
    trades: list[BacktestTrade] = []
    result = _maybe_scale_out(pos, exit_policy_for({}), bar_high=1079.0, trades=trades, day=date(2024, 1, 5))
    assert result > 0.0
    assert len(trades) == 1
    assert pos.quantity == 10


def test_backtest_scale_out_respects_the_minimum_position_value():
    pos, _ = _backtest_position(quantity=15)  # 15 x 1,050 = 15,750
    trades: list[BacktestTrade] = []
    assert _maybe_scale_out(pos, exit_policy_for(BARRIER_PARAMS), 1060.0, trades, date(2024, 1, 5)) == 0.0
    assert trades == []
