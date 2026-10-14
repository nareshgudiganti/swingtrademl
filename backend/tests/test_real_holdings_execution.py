"""Placing and finishing the owner's real My Holdings orders.

Kite is never called for real: the kite_broker singleton's methods are
replaced by a fake that records what it was asked to do.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from swing_trade_ml.brokers import OrderResult
from swing_trade_ml.brokers.kite import kite_broker
from swing_trade_ml.core.enums import ExitReason, OrderStatus, PositionStatus, TransactionType
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Order, Position, Strategy, Trade
from swing_trade_ml.services import execution


class FakeKite:
    def __init__(self) -> None:
        self.placed: list = []
        self.status: dict[str, OrderResult] = {}
        self.next_id = 500

    def place_order(self, request, db):
        self.placed.append(request)
        self.next_id += 1
        return OrderResult(broker_order_id=str(self.next_id), status=OrderStatus.PENDING)

    def get_order_status(self, broker_order_id, db):
        return self.status.get(broker_order_id)

    def load_session(self, db):
        return True


@pytest.fixture
def kite(monkeypatch):
    fake = FakeKite()
    for name in ("place_order", "get_order_status", "load_session"):
        monkeypatch.setattr(kite_broker, name, getattr(fake, name))
    monkeypatch.setattr(execution.notifier, "send_sync", lambda *a, **k: True)
    return fake


def _setup(db, symbol="ZZRHBUY", token=881_001):
    strategy = Strategy(
        name="real_trading", strategy_type="ml_swing", mode="live",
        execution_mode="advisory", is_active=True, params={}, symbols=[],
    )
    instrument = Instrument(instrument_token=token, tradingsymbol=symbol, exchange="NSE")
    db.add_all([strategy, instrument])
    db.flush()
    return strategy, instrument


def _complete(kite, order, price, qty):
    kite.status[order.broker_order_id] = OrderResult(
        broker_order_id=order.broker_order_id, status=OrderStatus.COMPLETE,
        filled_quantity=qty, average_price=price,
    )


def test_buy_is_sent_tagged_as_live_market_cnc(db_session, kite):
    strategy, instrument = _setup(db_session)
    order = execution.place_real_holding_buy(db_session, strategy, instrument, 3, 1000.0)

    assert order.mode == "live" and order.transaction_type == TransactionType.BUY
    assert order.status == OrderStatus.PENDING and order.broker_order_id == "501"
    assert order.price == 1000.0
    [req] = kite.placed
    assert req.tag == f"stmlh-b-{order.id}" and len(req.tag) <= 20
    assert req.price is None and req.quantity == 3


def test_a_filled_buy_becomes_a_holding_with_minus_4_plus_8(db_session, kite):
    strategy, instrument = _setup(db_session)
    order = execution.place_real_holding_buy(db_session, strategy, instrument, 3, 1000.0)
    _complete(kite, order, 990.0, 3)

    execution.reconcile_pending_orders(db_session)

    position = db_session.execute(
        select(Position).where(Position.strategy_id == strategy.id)
    ).scalar_one()
    assert position.status == PositionStatus.OPEN and position.mode == "live"
    assert position.quantity == 3 and position.entry_price == 990.0
    assert position.stop_loss == round(990.0 * 0.96, 2)
    assert position.take_profit == round(990.0 * 1.08, 2)
    assert "ZZRHBUY" in (strategy.symbols or []), "the model must read an app-bought stock daily"


def test_a_rejected_buy_creates_nothing(db_session, kite):
    strategy, instrument = _setup(db_session)
    order = execution.place_real_holding_buy(db_session, strategy, instrument, 3, 1000.0)
    kite.status[order.broker_order_id] = OrderResult(
        broker_order_id=order.broker_order_id, status=OrderStatus.REJECTED, message="Insufficient funds"
    )

    execution.reconcile_pending_orders(db_session)

    assert db_session.get(Order, order.id).status == OrderStatus.REJECTED
    assert db_session.execute(select(Position).where(Position.strategy_id == strategy.id)).first() is None


def _holding(db, strategy, instrument, qty=10):
    p = Position(
        strategy_id=strategy.id, instrument_id=instrument.id, mode="live", quantity=qty,
        initial_quantity=qty, entry_price=100.0, current_price=110.0, total_charges=0.0,
        entry_at=datetime(2026, 10, 1, tzinfo=UTC), status=PositionStatus.OPEN,
    )
    db.add(p)
    db.flush()
    return p


def test_a_full_sell_closes_the_holding_at_the_real_fill(db_session, kite):
    strategy, instrument = _setup(db_session, "ZZRHSELL", 881_002)
    position = _holding(db_session, strategy, instrument)

    order = execution.place_real_holding_sell(db_session, position, 10)
    assert kite.placed[0].tag == f"stmlh-s-{order.id}"
    assert order.exit_reason == ExitReason.MANUAL and order.position_id == position.id
    _complete(kite, order, 112.0, 10)

    execution.reconcile_pending_orders(db_session)

    db_session.refresh(position)
    assert position.status == PositionStatus.CLOSED and position.exit_price == 112.0
    trade = db_session.execute(select(Trade).where(Trade.position_id == position.id)).scalar_one()
    assert trade.quantity == 10 and trade.exit_reason == ExitReason.MANUAL


def test_a_partial_sell_keeps_the_rest(db_session, kite):
    strategy, instrument = _setup(db_session, "ZZRHHALF", 881_003)
    position = _holding(db_session, strategy, instrument)

    order = execution.place_real_holding_sell(db_session, position, 4)
    _complete(kite, order, 112.0, 4)
    execution.reconcile_pending_orders(db_session)

    db_session.refresh(position)
    assert position.status == PositionStatus.OPEN and position.quantity == 6


def test_paper_bot_orders_are_not_sent_to_kite_by_the_second_pass(db_session, kite, monkeypatch):
    """The extra pass looks only at real_trading's live orders."""
    strategy, instrument = _setup(db_session, "ZZRHBOT", 881_004)
    bot = Strategy(name="zz_bot", strategy_type="ml_swing", mode="paper", execution_mode="auto", is_active=True)
    db_session.add(bot)
    db_session.flush()
    db_session.add(Order(
        strategy_id=bot.id, instrument_id=instrument.id, mode="live", transaction_type="BUY",
        quantity=1, status=OrderStatus.PENDING, broker_order_id="777",
        placed_at=datetime.now(UTC),
    ))
    db_session.flush()
    asked: list[str] = []
    monkeypatch.setattr(kite_broker, "get_order_status", lambda oid, db: asked.append(oid))

    execution.reconcile_pending_orders(db_session)

    assert "777" not in asked
