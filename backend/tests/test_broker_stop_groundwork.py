"""Groundwork for broker-held stop orders, and the sell-once latch it needs.

Today the stop-loss is a polled comparison inside check_exits(), run once a
minute. The moment a real stop also sits at the broker, two things can decide
to sell the same shares — so the pieces pinned here are the ones that stay
true either way: an exit order that carries the reason it was placed for
(otherwise every reconciled exit is graded as "manual"), a latch that makes a
second sell impossible while one is in flight, and a broker interface callers
can branch on without knowing which broker they hold.

Prices are driven the way the paper broker reads them in tests: through the
cached `quotes` row (no Kite session), so check_exits() and the simulated fill
see the same price.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from swing_trade_ml.brokers import OrderResult
from swing_trade_ml.brokers.base import BrokerStopState, StopRequest
from swing_trade_ml.brokers.kite import kite_broker
from swing_trade_ml.brokers.paper import paper_broker
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
    quantity: int = 20,
    price: float = 1000.0,
    stop_loss: float = 900.0,
    take_profit: float = 1080.0,
    symbol: str = "TITAN",
) -> Position:
    inst = Instrument(
        instrument_token=abs(hash(symbol)) % 1_000_000, tradingsymbol=symbol, exchange="NSE",
        is_watchlisted=True,
    )
    strategy = Strategy(
        name=f"strat_{symbol}", strategy_type="ml_swing", mode="paper", is_active=True,
        execution_mode="auto", params={"scale_out_at_pct": 0},
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

    position = execution.open_position(db, strategy, inst, signal, quantity)
    assert position is not None
    return position


def _tick(db, position: Position, price: float) -> list[Trade]:
    quote = db.execute(select(Quote).where(Quote.instrument_id == position.instrument_id)).scalar_one()
    quote.last_price = price
    db.commit()
    return execution.check_exits(db)


def _sell_orders(db, position: Position) -> list[Order]:
    return list(
        db.execute(
            select(Order)
            .where(Order.position_id == position.id, Order.transaction_type == TransactionType.SELL)
            .order_by(Order.id)
        ).scalars()
    )


# ------------------------------------------------------- the exit reason --


def test_a_reconciled_exit_records_the_reason_it_was_placed_for(db_session):
    """A live sell fills later, through reconciliation. Every one of them used
    to be written as MANUAL, so a stop-loss, a target and a time stop were
    indistinguishable afterwards — and exit-quality grading would train on
    that."""
    position = _open(db_session)
    order = Order(
        position_id=position.id, strategy_id=position.strategy_id,
        instrument_id=position.instrument_id, mode="paper",
        transaction_type=TransactionType.SELL, quantity=20, status=OrderStatus.COMPLETE,
        exit_reason=ExitReason.STOP_LOSS_HIT,
        placed_at=datetime.now(UTC), filled_at=datetime.now(UTC), broker_order_id="LIVE-SL",
    )
    db_session.add(order)
    db_session.commit()

    execution._finish_reconciled_order(
        db_session, order,
        OrderResult(
            broker_order_id="LIVE-SL", status=OrderStatus.COMPLETE, filled_quantity=20,
            average_price=899.0, brokerage=0.0, taxes=25.0,
        ),
    )

    trade = db_session.execute(select(Trade).where(Trade.position_id == position.id)).scalar_one()
    assert trade.exit_reason == ExitReason.STOP_LOSS_HIT
    assert position.exit_reason == ExitReason.STOP_LOSS_HIT


def test_an_exit_order_with_no_reason_is_still_a_manual_close(db_session):
    """The fallback is a real case, not just defensiveness: a sell the user
    initiated themselves carries no reason of ours."""
    position = _open(db_session)
    order = Order(
        position_id=position.id, strategy_id=position.strategy_id,
        instrument_id=position.instrument_id, mode="paper",
        transaction_type=TransactionType.SELL, quantity=20, status=OrderStatus.COMPLETE,
        placed_at=datetime.now(UTC), filled_at=datetime.now(UTC), broker_order_id="LIVE-M",
    )
    db_session.add(order)
    db_session.commit()

    execution._finish_reconciled_order(
        db_session, order,
        OrderResult(
            broker_order_id="LIVE-M", status=OrderStatus.COMPLETE, filled_quantity=20,
            average_price=1010.0, brokerage=0.0, taxes=25.0,
        ),
    )

    assert position.exit_reason == ExitReason.MANUAL


def test_close_position_stamps_the_reason_on_the_order_it_places(db_session):
    """Reconciliation can only read the reason back if placement wrote it."""
    position = _open(db_session)
    execution.close_position(db_session, position, 1085.0, ExitReason.TARGET_HIT)

    assert [o.exit_reason for o in _sell_orders(db_session, position)] == [ExitReason.TARGET_HIT]


def test_the_time_stop_survives_the_round_trip_through_reconciliation(db_session):
    """End to end: check_exits decides, the order carries it, reconciliation
    writes it — the three steps that used to lose the label between them."""
    position = _open(db_session)
    position.entry_at = datetime.now(UTC) - timedelta(days=40)
    db_session.commit()

    _tick(db_session, position, 1010.0)

    order = _sell_orders(db_session, position)[0]
    assert order.exit_reason == ExitReason.TIME_STOP
    assert position.exit_reason == ExitReason.TIME_STOP


# -------------------------------------------------------- the sell latch --


def test_no_second_sell_while_an_exit_is_already_in_progress(db_session):
    position = _open(db_session)
    position.exit_in_progress_at = datetime.now(UTC)
    db_session.commit()

    assert _tick(db_session, position, 890.0) == []
    assert _sell_orders(db_session, position) == []
    assert position.status == PositionStatus.OPEN
    assert position.quantity == 20


def test_a_stale_claim_does_not_block_a_legitimate_exit_forever(db_session):
    """A crash between claiming and selling must not strand a position below
    its stop — the claim expires."""
    position = _open(db_session)
    position.exit_in_progress_at = datetime.now(UTC) - execution.EXIT_CLAIM_TTL - timedelta(minutes=1)
    db_session.commit()

    closed = _tick(db_session, position, 890.0)

    assert [t.exit_reason for t in closed] == [ExitReason.STOP_LOSS_HIT]
    assert position.status == PositionStatus.CLOSED


def test_the_claim_is_visible_in_the_database_before_the_order_is_sent(db_session):
    """The ordering is the whole point: claim, commit, then sell. Claiming
    after the order is away leaves exactly the window it exists to close."""
    seen: list[datetime | None] = []
    original = paper_broker.place_order

    def _record(request, db):
        if request.transaction_type == TransactionType.SELL:
            seen.append(
                db.execute(
                    select(Position.exit_in_progress_at).where(Position.id == position.id)
                ).scalar_one()
            )
        return original(request, db)

    position = _open(db_session)
    paper_broker.place_order = _record
    try:
        _tick(db_session, position, 890.0)
    finally:
        paper_broker.place_order = original

    assert len(seen) == 1
    assert seen[0] is not None


def test_the_claim_is_released_when_the_sell_does_not_fill(db_session):
    """A rejected sell must leave the position claimable again, or one bad
    order would silently disable its stop-loss until the claim went stale."""
    position = _open(db_session)
    original = paper_broker.place_order

    def _reject(request, db):
        if request.transaction_type == TransactionType.SELL:
            return OrderResult(
                broker_order_id="PAPER-REJECT", status=OrderStatus.REJECTED,
                message="simulated rejection",
            )
        return original(request, db)

    paper_broker.place_order = _reject
    try:
        assert _tick(db_session, position, 890.0) == []
    finally:
        paper_broker.place_order = original

    assert position.status == PositionStatus.OPEN
    assert position.exit_in_progress_at is None

    closed = _tick(db_session, position, 890.0)
    assert [t.exit_reason for t in closed] == [ExitReason.STOP_LOSS_HIT]


def test_a_pending_sell_still_blocks_a_second_one(db_session):
    """The claim is the new guard, but the older one — an order still resting
    at the broker — has to keep holding regardless of it."""
    position = _open(db_session)
    db_session.add(
        Order(
            position_id=position.id, strategy_id=position.strategy_id,
            instrument_id=position.instrument_id, mode="paper",
            transaction_type=TransactionType.SELL, quantity=20, status=OrderStatus.PENDING,
            placed_at=datetime.now(UTC), broker_order_id="LIVE-PENDING",
        )
    )
    db_session.commit()

    assert _tick(db_session, position, 890.0) == []
    assert len(_sell_orders(db_session, position)) == 1


def test_a_normal_exit_leaves_no_claim_behind(db_session):
    position = _open(db_session)
    closed = _tick(db_session, position, 1085.0)

    assert [t.exit_reason for t in closed] == [ExitReason.TARGET_HIT]
    assert position.exit_in_progress_at is None


# ---------------------------------------------------- the broker interface --


def test_the_paper_broker_holds_no_stops_of_its_own():
    """Callers branch on this flag, never on the broker's type — that is what
    lets the Kite/GTT side arrive later without touching any of them."""
    assert paper_broker.supports_broker_stops is False


def test_the_stop_methods_are_safe_to_call_on_a_broker_without_stops(db_session):
    stop = StopRequest(tradingsymbol="TITAN", exchange="NSE", quantity=20, trigger_price=900.0)

    assert paper_broker.place_stop(stop, db_session) is None
    assert paper_broker.modify_stop("GTT-1", 910.0, None, db_session) is None
    assert paper_broker.cancel_stop("GTT-1", db_session) is None
    assert paper_broker.list_stops(db_session) == []


def test_a_new_position_carries_the_broker_stop_columns_unset(db_session):
    """They ship now so the migration happens once; nothing writes to them
    until the GTT side exists."""
    position = _open(db_session)

    assert position.broker_stop_id is None
    assert position.broker_stop_trigger is None
    assert position.broker_stop_qty is None
    assert position.broker_stop_state == BrokerStopState.NONE
    assert position.broker_stop_error is None
    assert position.broker_stop_synced_at is None
