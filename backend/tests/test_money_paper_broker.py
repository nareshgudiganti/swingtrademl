"""PaperBroker: simulated fills against real prices, charged and pessimistic (qa8 coverage floor).

The Kite singleton is never asked for anything real: it is either left unauthenticated (so the paper
broker falls back to stored prices) or its get_ltp is replaced with a fake.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from swing_trade_ml.brokers import current_mode, get_broker, kite_broker, paper_broker
from swing_trade_ml.brokers.base import Broker, OrderRequest, StopRequest
from swing_trade_ml.brokers.paper import PaperBroker
from swing_trade_ml.core import config
from swing_trade_ml.core.enums import OrderStatus, OrderType, TransactionType
from swing_trade_ml.db.models.market import Candle, Instrument, Quote
from swing_trade_ml.db.models.trading import Order, Position, Strategy

_TOKEN = iter(range(880_000_000, 890_000_000))


@pytest.fixture(autouse=True)
def _no_kite(monkeypatch):
    monkeypatch.setattr(kite_broker, "_token_loaded", False)


def _instrument(db, symbol="PAPERTEST"):
    inst = Instrument(instrument_token=next(_TOKEN), tradingsymbol=symbol, exchange="NSE")
    db.add(inst)
    db.flush()
    return inst


def _req(side=TransactionType.BUY, qty=10, order_type=OrderType.MARKET, price=None, symbol="PAPERTEST"):
    return OrderRequest(
        tradingsymbol=symbol,
        exchange="NSE",
        transaction_type=side,
        quantity=qty,
        order_type=order_type,
        price=price,
    )


# --------------------------------------------------------------- factory --


def test_factory_returns_paper_unless_both_latches_are_open(monkeypatch):
    monkeypatch.setattr(config.settings, "TRADING_MODE", "live", raising=False)
    monkeypatch.setattr(config.settings, "ALLOW_LIVE_TRADING", False, raising=False)
    assert get_broker() is paper_broker and current_mode() == "paper"
    monkeypatch.setattr(config.settings, "TRADING_MODE", "paper", raising=False)
    monkeypatch.setattr(config.settings, "ALLOW_LIVE_TRADING", True, raising=False)
    assert get_broker() is paper_broker
    monkeypatch.setattr(config.settings, "TRADING_MODE", "live", raising=False)
    assert get_broker() is kite_broker  # both open; nothing is placed here


def test_base_broker_stop_methods_are_safe_no_ops(db_session):
    assert isinstance(paper_broker, Broker)
    assert paper_broker.supports_broker_stops is False
    req = StopRequest(tradingsymbol="X", exchange="NSE", quantity=1, trigger_price=9.0)
    assert paper_broker.place_stop(req, db_session) is None
    assert paper_broker.modify_stop("s1", 9.0, None, db_session) is None
    assert paper_broker.cancel_stop("s1", db_session) is None
    assert paper_broker.list_stops(db_session) == []


# --------------------------------------------------------------- pricing --


def test_reference_price_falls_back_quote_then_candle_then_none(db_session):
    b = PaperBroker()
    assert b._reference_price("NOSUCHSTOCK", "NSE", db_session) is None
    inst = _instrument(db_session)
    assert b._reference_price("PAPERTEST", "NSE", db_session) is None
    db_session.add(
        Candle(
            instrument_id=inst.id,
            interval="day",
            ts=datetime.now(UTC) - timedelta(days=1),
            open=1,
            high=1,
            low=1,
            close=95.0,
            volume=10,
        )
    )
    db_session.flush()
    assert b._reference_price("PAPERTEST", "NSE", db_session) == 95.0
    db_session.add(Quote(instrument_id=inst.id, last_price=97.0, ts=datetime.now(UTC)))
    db_session.flush()
    assert b._reference_price("PAPERTEST", "NSE", db_session) == 97.0


def test_reference_price_prefers_live_ltp_and_survives_its_failure(db_session, monkeypatch):
    b = PaperBroker()
    inst = _instrument(db_session)
    db_session.add(Quote(instrument_id=inst.id, last_price=97.0, ts=datetime.now(UTC)))
    db_session.flush()
    monkeypatch.setattr(kite_broker, "_token_loaded", True)
    monkeypatch.setattr(kite_broker, "get_ltp", lambda keys, db: {"NSE:PAPERTEST": 101.0})
    assert b._reference_price("PAPERTEST", "NSE", db_session) == 101.0

    def broken(keys, db):
        raise RuntimeError("kite down")

    monkeypatch.setattr(kite_broker, "get_ltp", broken)
    assert b._reference_price("PAPERTEST", "NSE", db_session) == 97.0


# ---------------------------------------------------------------- orders --


def test_no_price_rejects(db_session):
    result = PaperBroker().place_order(_req(symbol="NOSUCHSTOCK"), db_session)
    assert result.status == OrderStatus.REJECTED and "No price" in result.message


def test_market_buy_fills_adversely_with_charges(db_session):
    inst = _instrument(db_session)
    db_session.add(Quote(instrument_id=inst.id, last_price=100.0, ts=datetime.now(UTC)))
    db_session.flush()
    buy = PaperBroker().place_order(_req(qty=5), db_session)
    assert buy.status == OrderStatus.COMPLETE and buy.filled_quantity == 5
    assert buy.average_price >= 100.0  # never better than the quote
    assert buy.brokerage + buy.taxes >= 0
    sell = PaperBroker().place_order(_req(TransactionType.SELL, qty=5), db_session)
    assert sell.status == OrderStatus.COMPLETE and sell.average_price <= 100.0


def test_limit_orders_only_fill_when_reachable(db_session):
    inst = _instrument(db_session)
    db_session.add(Quote(instrument_id=inst.id, last_price=100.0, ts=datetime.now(UTC)))
    db_session.flush()
    b = PaperBroker()
    assert b.place_order(_req(order_type=OrderType.LIMIT, price=99.0), db_session).status == OrderStatus.OPEN
    assert (
        b.place_order(_req(TransactionType.SELL, order_type=OrderType.LIMIT, price=101.0), db_session).status
        == OrderStatus.OPEN
    )
    filled = b.place_order(_req(order_type=OrderType.LIMIT, price=100.5), db_session)
    assert filled.status == OrderStatus.COMPLETE and filled.average_price == 100.5


def test_buy_beyond_paper_cash_is_rejected(db_session, monkeypatch):
    inst = _instrument(db_session)
    db_session.add(Quote(instrument_id=inst.id, last_price=100.0, ts=datetime.now(UTC)))
    db_session.flush()
    b = PaperBroker()
    monkeypatch.setattr(PaperBroker, "get_available_cash", lambda self, db: 500.0)
    result = b.place_order(_req(qty=10), db_session)
    assert result.status == OrderStatus.REJECTED and "Insufficient paper cash" in result.message
    # Selling never needs cash.
    assert b.place_order(_req(TransactionType.SELL, qty=10), db_session).status == OrderStatus.COMPLETE


def test_cancel_and_status_only_touch_resting_paper_orders(db_session):
    inst = _instrument(db_session)
    resting = Order(
        instrument_id=inst.id,
        mode="paper",
        transaction_type="BUY",
        order_type="LIMIT",
        product="CNC",
        quantity=1,
        status=OrderStatus.OPEN,
        broker_order_id="PAPER-REST1",
        placed_at=datetime.now(UTC),
    )
    done = Order(
        instrument_id=inst.id,
        mode="paper",
        transaction_type="BUY",
        order_type="MARKET",
        product="CNC",
        quantity=1,
        status=OrderStatus.COMPLETE,
        broker_order_id="PAPER-DONE1",
        filled_quantity=1,
        average_price=10.0,
        brokerage=0.0,
        taxes=0.1,
        placed_at=datetime.now(UTC),
    )
    db_session.add_all([resting, done])
    db_session.flush()
    b = PaperBroker()
    assert b.cancel_order("PAPER-MISSING", db_session) is False
    assert b.cancel_order("PAPER-DONE1", db_session) is False
    assert b.cancel_order("PAPER-REST1", db_session) is True
    assert resting.status == OrderStatus.CANCELLED
    assert b.get_order_status("PAPER-MISSING", db_session) is None
    status = b.get_order_status("PAPER-DONE1", db_session)
    assert status.status == OrderStatus.COMPLETE and status.filled_quantity == 1


def test_positions_margins_and_cash_follow_open_rows(db_session):
    b = PaperBroker()
    cash_before = b.get_available_cash(db_session)
    inst = _instrument(db_session)
    strat = Strategy(name="paper_broker_cov", strategy_type="ml_swing", mode="paper")
    db_session.add(strat)
    db_session.flush()
    db_session.add(
        Position(
            strategy_id=strat.id,
            instrument_id=inst.id,
            mode="paper",
            status="OPEN",
            quantity=10,
            entry_price=100.0,
            entry_at=datetime.now(UTC),
            current_price=110.0,
            total_charges=5.0,
        )
    )
    db_session.flush()
    assert b.get_available_cash(db_session) == pytest.approx(cash_before - 1005.0)
    mine = [p for p in b.get_positions(db_session) if p.tradingsymbol == "PAPERTEST"]
    assert mine and mine[0].pnl == pytest.approx(100.0)
    m = b.get_margins(db_session)
    assert m.total == pytest.approx(m.available_cash + m.used_margin)


def test_get_ltp_delegates_then_falls_back(db_session, monkeypatch):
    inst = _instrument(db_session)
    db_session.add(Quote(instrument_id=inst.id, last_price=88.0, ts=datetime.now(UTC)))
    db_session.flush()
    b = PaperBroker()
    assert b.get_ltp(["NSE:PAPERTEST", "NSE:NOSUCHSTOCK"], db_session) == {"NSE:PAPERTEST": 88.0}
    monkeypatch.setattr(kite_broker, "_token_loaded", True)
    monkeypatch.setattr(kite_broker, "get_ltp", lambda keys, db: {"NSE:PAPERTEST": 90.0})
    assert b.get_ltp(["NSE:PAPERTEST"], db_session) == {"NSE:PAPERTEST": 90.0}

    def broken(keys, db):
        raise RuntimeError("down")

    monkeypatch.setattr(kite_broker, "get_ltp", broken)
    monkeypatch.setattr(kite_broker, "_token_loaded", True)
    # _reference_price also tries the (broken) live call, then the quote.
    assert b.get_ltp(["NSE:PAPERTEST"], db_session) == {"NSE:PAPERTEST": 88.0}


def test_historical_data_delegates_and_now_is_utc(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        kite_broker,
        "get_historical_data",
        lambda token, f, t, i, db: seen.setdefault("args", (token, i)) and [{"close": 1}],
    )
    start = datetime(2026, 1, 1, tzinfo=UTC)
    assert PaperBroker().get_historical_data(5, start, start, "day", None) == [{"close": 1}]
    assert seen["args"] == (5, "day")
    assert PaperBroker.now().tzinfo is not None
