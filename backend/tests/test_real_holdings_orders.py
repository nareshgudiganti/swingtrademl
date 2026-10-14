"""Every check in front of a real My Holdings order. Nothing reaches Zerodha
when one fails; the owner sees one plain sentence."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from swing_trade_ml.brokers import OrderResult
from swing_trade_ml.brokers.kite import kite_broker
from swing_trade_ml.core import config, market_session
from swing_trade_ml.core.enums import OrderStatus, PositionStatus
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Position, Strategy
from swing_trade_ml.services import execution, holdings_sync, real_orders
from swing_trade_ml.services.real_orders import RealOrderRefused


@pytest.fixture
def ready(monkeypatch):
    """Latch on, market open, Zerodha logged in, price 1000, orders recorded."""
    sent: list = []
    state = {"price": 1000.0, "session": True}
    monkeypatch.setattr(config.settings, "ALLOW_REAL_HOLDINGS_ORDERS", True, raising=False)
    monkeypatch.setattr(market_session, "is_open", lambda *a, **k: True)
    monkeypatch.setattr(kite_broker, "load_session", lambda db: state["session"])
    monkeypatch.setattr(kite_broker, "_token_loaded", True, raising=False)
    monkeypatch.setattr(kite_broker, "get_ltp", lambda symbols, db: dict.fromkeys(symbols, state["price"]))

    def place(request, db):
        sent.append(request)
        return OrderResult(broker_order_id=str(600 + len(sent)), status=OrderStatus.PENDING)

    monkeypatch.setattr(kite_broker, "place_order", place)
    monkeypatch.setattr(execution.notifier, "send_sync", lambda *a, **k: True)
    return sent, state


def _setup(db, symbol="ZZRO", token=882_001):
    strategy = Strategy(
        name="real_trading",
        strategy_type="ml_swing",
        mode="live",
        execution_mode="advisory",
        is_active=True,
        params={},
        symbols=[],
    )
    instrument = Instrument(instrument_token=token, tradingsymbol=symbol, exchange="NSE")
    db.add_all([strategy, instrument])
    db.flush()
    return strategy, instrument


def _holding(db, strategy, instrument, qty=10):
    p = Position(
        strategy_id=strategy.id,
        instrument_id=instrument.id,
        mode="live",
        quantity=qty,
        initial_quantity=qty,
        entry_price=100.0,
        current_price=110.0,
        total_charges=0.0,
        entry_at=datetime(2026, 10, 1, tzinfo=UTC),
        status=PositionStatus.OPEN,
    )
    db.add(p)
    db.flush()
    db.refresh(p)
    return p


def test_a_small_buy_inside_the_limits_is_sent(db_session, ready):
    sent, _ = ready
    strategy, instrument = _setup(db_session)
    order = real_orders.buy(db_session, strategy, instrument, 9)
    assert order.status == OrderStatus.PENDING and len(sent) == 1


def test_switch_off_refuses_and_sends_nothing(db_session, ready, monkeypatch):
    sent, _ = ready
    monkeypatch.setattr(config.settings, "ALLOW_REAL_HOLDINGS_ORDERS", False, raising=False)
    strategy, instrument = _setup(db_session)
    with pytest.raises(RealOrderRefused, match="switched off"):
        real_orders.buy(db_session, strategy, instrument, 1)
    position = _holding(db_session, strategy, instrument)
    with pytest.raises(RealOrderRefused, match="switched off"):
        real_orders.sell(db_session, position, None)
    assert sent == []


def test_market_closed_is_refused(db_session, ready, monkeypatch):
    sent, _ = ready
    monkeypatch.setattr(market_session, "is_open", lambda *a, **k: False)
    strategy, instrument = _setup(db_session)
    with pytest.raises(RealOrderRefused, match="market is closed"):
        real_orders.buy(db_session, strategy, instrument, 1)
    assert sent == []


def test_over_10k_in_one_order_is_refused(db_session, ready):
    sent, state = ready
    state["price"] = 1000.01
    strategy, instrument = _setup(db_session)
    with pytest.raises(RealOrderRefused, match="per order"):
        real_orders.buy(db_session, strategy, instrument, 10)
    assert sent == []


def test_the_third_10k_buy_of_the_day_is_refused(db_session, ready):
    sent, _ = ready
    strategy, instrument = _setup(db_session)
    other = Instrument(instrument_token=882_002, tradingsymbol="ZZRO2", exchange="NSE")
    third = Instrument(instrument_token=882_003, tradingsymbol="ZZRO3", exchange="NSE")
    db_session.add_all([other, third])
    db_session.flush()
    real_orders.buy(db_session, strategy, instrument, 10)  # 10,000
    real_orders.buy(db_session, strategy, other, 10)  # 20,000
    with pytest.raises(RealOrderRefused, match="daily limit"):
        real_orders.buy(db_session, strategy, third, 10)  # would be 30,000
    assert len(sent) == 2


def test_pending_buys_count_toward_the_daily_cap(db_session, ready):
    """A market order has no fill price yet; its reference price still counts."""
    strategy, instrument = _setup(db_session)
    real_orders.buy(db_session, strategy, instrument, 10)
    assert real_orders.spent_today(db_session, strategy.id) == 10_000


def test_an_open_order_with_zero_average_price_still_counts(db_session, ready):
    """Kite reports average_price = 0 for an OPEN, unfilled order and reconcile
    copies it; the reference price must still count toward the day."""
    strategy, instrument = _setup(db_session)
    order = real_orders.buy(db_session, strategy, instrument, 10)
    order.status = OrderStatus.OPEN
    order.average_price = 0.0
    db_session.flush()
    assert real_orders.spent_today(db_session, strategy.id) == 10_000


def test_rejected_buys_do_not_use_up_the_day(db_session, ready):
    strategy, instrument = _setup(db_session)
    order = real_orders.buy(db_session, strategy, instrument, 10)
    order.status = OrderStatus.REJECTED
    db_session.flush()
    assert real_orders.spent_today(db_session, strategy.id) == 0


def test_a_sell_is_never_blocked_by_the_money_limit(db_session, ready):
    sent, state = ready
    state["price"] = 50_000.0
    strategy, instrument = _setup(db_session)
    position = _holding(db_session, strategy, instrument, qty=10)
    real_orders.sell(db_session, position, None)
    assert sent[-1].quantity == 10


def test_selling_more_than_held_is_refused(db_session, ready):
    strategy, instrument = _setup(db_session)
    position = _holding(db_session, strategy, instrument, qty=5)
    with pytest.raises(RealOrderRefused, match="between 1 and 5"):
        real_orders.sell(db_session, position, 6)


def test_only_my_holdings_positions_can_be_sold(db_session, ready):
    _, instrument = _setup(db_session)
    bot = Strategy(
        name="zz_bot2", strategy_type="ml_swing", mode="paper", execution_mode="auto", is_active=True
    )
    db_session.add(bot)
    db_session.flush()
    position = _holding(db_session, bot, instrument)
    with pytest.raises(RealOrderRefused, match="My Holdings"):
        real_orders.sell(db_session, position, None)


def test_a_second_order_while_one_is_waiting_is_refused(db_session, ready):
    sent, _ = ready
    strategy, instrument = _setup(db_session)
    real_orders.buy(db_session, strategy, instrument, 1)
    with pytest.raises(RealOrderRefused, match="still waiting"):
        real_orders.buy(db_session, strategy, instrument, 1)
    assert len(sent) == 1


def test_no_zerodha_session_is_refused_plainly(db_session, ready):
    sent, state = ready
    state["session"] = False
    strategy, instrument = _setup(db_session)
    with pytest.raises(RealOrderRefused, match="Log in to Zerodha"):
        real_orders.buy(db_session, strategy, instrument, 1)
    assert sent == []


def test_status_reports_switch_limits_spend_and_waiting(db_session, ready):
    strategy, instrument = _setup(db_session)
    real_orders.buy(db_session, strategy, instrument, 2)
    s = real_orders.status(db_session, strategy)
    assert s["enabled"] is True and s["max_order_inr"] == 10_000 and s["max_day_inr"] == 25_000
    assert s["spent_today_inr"] == 2_000
    assert s["waiting"][0]["symbol"] == "ZZRO" and s["waiting"][0]["side"] == "BUY"


def test_sync_leaves_a_holding_with_a_waiting_order_alone(db_session, ready):
    """Zerodha already dropped the sold shares, but the app has not recorded
    the real fill yet. The sync must not close it at a guessed price."""
    strategy, instrument = _setup(db_session)
    position = _holding(db_session, strategy, instrument)
    real_orders.sell(db_session, position, None)

    closed = holdings_sync.close_positions_no_longer_held(db_session, strategy, held_symbols=set())

    assert closed == []
    db_session.refresh(position)
    assert position.status == PositionStatus.OPEN


def test_sync_still_closes_a_holding_sold_outside_the_app(db_session, ready):
    strategy, instrument = _setup(db_session)
    _holding(db_session, strategy, instrument)
    closed = holdings_sync.close_positions_no_longer_held(db_session, strategy, held_symbols=set())
    assert [c["symbol"] for c in closed] == ["ZZRO"]
