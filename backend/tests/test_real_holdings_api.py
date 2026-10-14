"""The real-order routes: owner only, refusals as plain 409s."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from swing_trade_ml.brokers import OrderResult
from swing_trade_ml.brokers.kite import kite_broker
from swing_trade_ml.core import config, market_session
from swing_trade_ml.core.enums import OrderStatus, PositionStatus
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Order, Position, Strategy
from swing_trade_ml.services import execution
from swing_trade_ml.services.portfolio import REAL_TRADING_STRATEGY_NAME

HEADERS = {"X-API-Key": "test-api-key"}


@pytest.fixture
def ready(monkeypatch, db_session):
    sent: list = []
    monkeypatch.setattr(config.settings, "ALLOW_REAL_HOLDINGS_ORDERS", True, raising=False)
    monkeypatch.setattr(market_session, "is_open", lambda *a, **k: True)
    monkeypatch.setattr(kite_broker, "load_session", lambda db: True)
    monkeypatch.setattr(kite_broker, "get_ltp", lambda symbols, db: dict.fromkeys(symbols, 500.0))

    def place(request, db):
        sent.append(request)
        return OrderResult(broker_order_id="701", status=OrderStatus.PENDING)

    monkeypatch.setattr(kite_broker, "place_order", place)
    monkeypatch.setattr(execution.notifier, "send_sync", lambda *a, **k: True)
    db_session.add(Instrument(instrument_token=883_001, tradingsymbol="ZZAPI", exchange="NSE"))
    db_session.commit()
    return sent


def test_buy_route_sends_a_small_order(client, ready):
    r = client.post("/api/v1/portfolio/real/buy", json={"symbol": "zzapi", "quantity": 4}, headers=HEADERS)
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "PENDING" and r.json()["symbol"] == "ZZAPI"
    assert len(ready) == 1


def test_a_refusal_is_a_409_with_the_reason(client, ready):
    r = client.post("/api/v1/portfolio/real/buy", json={"symbol": "ZZAPI", "quantity": 100}, headers=HEADERS)
    assert r.status_code == 409 and "per order" in r.json()["detail"]
    assert ready == []


def test_switch_off_is_refused(client, ready, monkeypatch):
    monkeypatch.setattr(config.settings, "ALLOW_REAL_HOLDINGS_ORDERS", False, raising=False)
    r = client.post("/api/v1/portfolio/real/buy", json={"symbol": "ZZAPI", "quantity": 1}, headers=HEADERS)
    assert r.status_code == 409 and "switched off" in r.json()["detail"]


def test_unknown_stock_is_404(client, ready):
    r = client.post("/api/v1/portfolio/real/buy", json={"symbol": "NOPE", "quantity": 1}, headers=HEADERS)
    assert r.status_code == 404


def test_status_and_quote(client, ready):
    s = client.get("/api/v1/portfolio/real/orders-status", headers=HEADERS)
    assert s.status_code == 200 and s.json()["enabled"] is True
    q = client.get("/api/v1/portfolio/real/quote?symbol=ZZAPI", headers=HEADERS)
    assert q.status_code == 200 and q.json()["price"] == 500.0


def test_no_credentials_is_refused(client, ready):
    assert client.post("/api/v1/portfolio/real/buy", json={"symbol": "ZZAPI", "quantity": 1}).status_code in (
        401,
        403,
    )
    assert ready == []


def _real_holding(db, qty=10):
    strategy = db.execute(
        select(Strategy).where(Strategy.name == REAL_TRADING_STRATEGY_NAME)
    ).scalar_one_or_none()
    if strategy is None:
        strategy = Strategy(
            name=REAL_TRADING_STRATEGY_NAME,
            strategy_type="ml_swing",
            params={},
            is_active=True,
            mode="live",
            execution_mode="advisory",
        )
        db.add(strategy)
        db.flush()
    instrument = db.execute(select(Instrument).where(Instrument.tradingsymbol == "ZZAPI")).scalar_one()
    position = Position(
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
    db.add(position)
    db.commit()
    return position.id


def test_sell_route_sends_the_quantity(client, ready, db_session):
    pid = _real_holding(db_session)
    r = client.post(f"/api/v1/portfolio/real/positions/{pid}/sell", json={"quantity": 3}, headers=HEADERS)
    assert r.status_code == 201, r.text
    assert r.json()["quantity"] == 3 and r.json()["symbol"] == "ZZAPI"
    assert len(ready) == 1 and ready[0].quantity == 3


def test_sell_unknown_holding_is_404(client, ready):
    r = client.post("/api/v1/portfolio/real/positions/999999/sell", json={}, headers=HEADERS)
    assert r.status_code == 404


def test_failed_send_is_a_502_and_the_order_is_rejected(client, ready, monkeypatch, db_session):
    def boom(request, db):
        raise RuntimeError("kite down")

    monkeypatch.setattr(kite_broker, "place_order", boom)
    r = client.post("/api/v1/portfolio/real/buy", json={"symbol": "ZZAPI", "quantity": 2}, headers=HEADERS)
    assert r.status_code == 502 and "Check the Kite app" in r.json()["detail"]
    db_session.expire_all()
    orders = db_session.execute(select(Order)).scalars().all()
    assert len(orders) == 1 and orders[0].status == OrderStatus.REJECTED
