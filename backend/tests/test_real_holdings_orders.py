"""Real buy/sell from My Holdings while the bot stays on paper (spec 2026-10-14-real-holdings-orders).

Zerodha is replaced by a recording fake: no test can reach a real account. Covers the latch, the narrow
gate in KiteBroker.place_order, every server-side check, the review additions (kill switch on buys,
Zerodha's own share count on sells, the same-day sync, Telegram on every order) and reconciliation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from swing_trade_ml.brokers import get_broker
from swing_trade_ml.brokers.base import OrderRequest
from swing_trade_ml.brokers.kite import kite_broker
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import OrderType, ProductType, TransactionType
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Order, Position, Strategy, Trade
from swing_trade_ml.services import execution, holdings_sync, real_orders, system_state

OWNER = {"X-API-Key": "test-api-key"}


class FakeKite:
    VARIETY_REGULAR = "regular"

    def __init__(self) -> None:
        self.placed: list[dict] = []
        self.price = 500.0
        self.hold: dict[str, int] = {}  # settled + t1 holdings
        self.today: dict[str, int] = {}  # today's CNC buys (positions)
        self.history: dict[str, list[dict]] = {}
        self.reject: str | None = None

    def place_order(self, **kw):
        if self.reject:
            from kiteconnect.exceptions import InputException

            raise InputException(self.reject)
        self.placed.append(kw)
        return f"K{len(self.placed)}"

    def ltp(self, symbols):
        return {s: {"last_price": self.price} for s in symbols}

    def holdings(self):
        return [{"tradingsymbol": s, "quantity": q, "t1_quantity": 0} for s, q in self.hold.items()]

    def positions(self):
        return {"net": [{"tradingsymbol": s, "quantity": q, "product": "CNC"} for s, q in self.today.items()]}

    def order_history(self, order_id):
        return self.history.get(order_id, [])


@pytest.fixture
def zerodha(monkeypatch, db_session):
    fake = FakeKite()
    monkeypatch.setattr(kite_broker, "_kite", fake)
    monkeypatch.setattr(kite_broker, "_token_loaded", True)
    monkeypatch.setattr(settings, "ALLOW_REAL_HOLDINGS_ORDERS", True)
    monkeypatch.setattr(real_orders.market_session, "is_open", lambda now=None, **kw: True)
    sent: list[str] = []
    monkeypatch.setattr(execution.notifier, "send_sync", lambda text, *a, **kw: sent.append(text))
    fake.sent = sent
    inst = Instrument(instrument_token=738561, tradingsymbol="RELIANCE", exchange="NSE", is_watchlisted=True)
    db_session.add(inst)
    db_session.flush()
    fake.inst = inst
    return fake


def _orders(db) -> list[Order]:
    return list(db.execute(select(Order).order_by(Order.id)).scalars())


def _fill(fake, order: Order, price: float, qty: int | None = None) -> None:
    fake.history[order.broker_order_id] = [
        {"status": "COMPLETE", "filled_quantity": qty or order.quantity, "average_price": price}
    ]


def _bought(db, fake, qty=10, price=500.0) -> Position:
    order = real_orders.buy(db, "RELIANCE", "NSE", qty, "owner")
    _fill(fake, order, price)
    execution.reconcile_pending_orders(db)
    return db.execute(select(Position).where(Position.instrument_id == fake.inst.id)).scalar_one()


# --- the latch and the narrow gate --------------------------------------------------------------------


def test_latch_off_refuses_and_zerodha_is_never_called(db_session, zerodha, monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_REAL_HOLDINGS_ORDERS", False)
    with pytest.raises(real_orders.RealOrderRefusedError, match="switched off"):
        real_orders.buy(db_session, "RELIANCE", "NSE", 1, "owner")
    assert zerodha.placed == [] and _orders(db_session) == []


@pytest.mark.parametrize(
    ("tag", "product", "order_type"),
    [
        ("stml-5", ProductType.CNC, OrderType.MARKET),  # a bot order
        ("stmlholdb1", ProductType.MIS, OrderType.MARKET),  # right tag, intraday product
        ("stmlholdb1", ProductType.CNC, OrderType.LIMIT),  # right tag, limit order
        ("stmlholdb" + "9" * 20, ProductType.CNC, OrderType.MARKET),  # tag too long for Zerodha
    ],
)
def test_the_gate_only_opens_for_a_tagged_cnc_market_order(db_session, zerodha, tag, product, order_type):
    req = OrderRequest("RELIANCE", "NSE", TransactionType.BUY, 1, order_type, product, tag=tag)
    with pytest.raises(RuntimeError, match="Refusing to place a live order"):
        kite_broker.place_order(req, db_session)
    assert zerodha.placed == []


def test_the_bot_still_gets_the_paper_broker_with_the_latch_on(zerodha):
    assert get_broker().mode == "paper"


# --- buys -------------------------------------------------------------------------------------------


def test_a_real_buy_is_sent_tagged_cnc_market_and_messaged(db_session, zerodha):
    order = real_orders.buy(db_session, "reliance", "NSE", 10, "owner")
    assert (order.mode, order.transaction_type, order.status, order.quantity) == (
        "live",
        "BUY",
        "PENDING",
        10,
    )
    sent = zerodha.placed[0]
    assert sent["tag"] == f"stmlholdb{order.id}" and len(sent["tag"]) <= 20
    assert (sent["product"], sent["order_type"], sent["transaction_type"]) == ("CNC", "MARKET", "BUY")
    assert "Real BUY sent" in zerodha.sent[-1] and "owner" in zerodha.sent[-1]


def test_one_buy_over_the_order_limit_is_refused(db_session, zerodha):
    zerodha.price = 1000.01
    with pytest.raises(real_orders.RealOrderRefusedError, match="above the ₹10,000 limit"):
        real_orders.buy(db_session, "RELIANCE", "NSE", 10, "owner")
    assert zerodha.placed == []


def test_the_daily_limit_counts_pending_buys(db_session, zerodha, monkeypatch):
    for sym, token in (("TCS", 1), ("INFY", 2), ("ITC", 3)):
        db_session.add(Instrument(instrument_token=token, tradingsymbol=sym, exchange="NSE"))
    db_session.flush()
    zerodha.price = 900.0
    real_orders.buy(db_session, "TCS", "NSE", 10, "owner")  # 9,000, still pending
    real_orders.buy(db_session, "INFY", "NSE", 10, "owner")  # 18,000
    with pytest.raises(real_orders.RealOrderRefusedError, match="daily limit"):
        real_orders.buy(db_session, "ITC", "NSE", 10, "owner")  # 27,000 > 25,000
    assert len(zerodha.placed) == 2


def test_market_closed_refuses(db_session, zerodha, monkeypatch):
    monkeypatch.setattr(real_orders.market_session, "is_open", lambda now=None, **kw: False)
    with pytest.raises(real_orders.RealOrderRefusedError, match="Market is closed"):
        real_orders.buy(db_session, "RELIANCE", "NSE", 1, "owner")
    assert zerodha.placed == []


def test_the_kill_switch_pauses_real_buys(db_session, zerodha):
    system_state.halt(db_session, reason="drill", by="test")
    with pytest.raises(real_orders.RealOrderRefusedError, match="kill switch"):
        real_orders.buy(db_session, "RELIANCE", "NSE", 1, "owner")
    assert zerodha.placed == []


def test_a_second_order_while_one_is_waiting_is_refused(db_session, zerodha):
    real_orders.buy(db_session, "RELIANCE", "NSE", 1, "owner")
    with pytest.raises(real_orders.RealOrderRefusedError, match="still waiting"):
        real_orders.buy(db_session, "RELIANCE", "NSE", 1, "owner")
    assert len(zerodha.placed) == 1


def test_a_zerodha_rejection_is_recorded_and_messaged(db_session, zerodha):
    zerodha.reject = "Insufficient funds"
    order = real_orders.buy(db_session, "RELIANCE", "NSE", 1, "owner")
    assert order.status == "REJECTED" and "Insufficient funds" in order.status_message
    assert "not placed" in zerodha.sent[-1]
    assert db_session.execute(select(Position)).first() is None


# --- reconciliation ---------------------------------------------------------------------------------


def test_a_filled_buy_becomes_a_my_holdings_row_with_alert_levels(db_session, zerodha):
    pos = _bought(db_session, zerodha, qty=10, price=500.0)
    strategy = db_session.get(Strategy, pos.strategy_id)
    assert strategy.name == "real_trading" and strategy.execution_mode == "advisory"
    assert (pos.mode, pos.status, pos.quantity, pos.entry_price) == ("live", "OPEN", 10, 500.0)
    assert pos.stop_loss == pytest.approx(480.0) and pos.take_profit == pytest.approx(540.0)
    assert any("BUY" in m for m in zerodha.sent)


def test_a_rejected_buy_creates_no_holding(db_session, zerodha):
    order = real_orders.buy(db_session, "RELIANCE", "NSE", 1, "owner")
    zerodha.history[order.broker_order_id] = [{"status": "REJECTED", "status_message": "RMS block"}]
    execution.reconcile_pending_orders(db_session)
    assert db_session.get(Order, order.id).status == "REJECTED"
    assert db_session.execute(select(Position)).first() is None


# --- sells ------------------------------------------------------------------------------------------


def test_a_real_sell_of_everything_closes_the_holding(db_session, zerodha):
    pos = _bought(db_session, zerodha)
    zerodha.today["RELIANCE"] = 10  # bought today: Zerodha lists it under positions, not holdings
    order = real_orders.sell(db_session, pos.id, None, "owner")
    assert (order.transaction_type, order.quantity, order.position_id) == ("SELL", 10, pos.id)
    assert zerodha.placed[-1]["tag"] == f"stmlholds{order.id}"
    _fill(zerodha, order, 520.0)
    execution.reconcile_pending_orders(db_session)
    db_session.refresh(pos)
    assert pos.status == "CLOSED"
    trade = db_session.execute(select(Trade).where(Trade.position_id == pos.id)).scalar_one()
    assert trade.quantity == 10 and trade.exit_reason == "MANUAL"


def test_a_partial_sell_leaves_the_rest(db_session, zerodha):
    pos = _bought(db_session, zerodha)
    zerodha.hold["RELIANCE"] = 10
    order = real_orders.sell(db_session, pos.id, 4, "owner")
    _fill(zerodha, order, 510.0)
    execution.reconcile_pending_orders(db_session)
    db_session.refresh(pos)
    assert (pos.status, pos.quantity) == ("OPEN", 6)


def test_selling_more_than_zerodha_holds_is_refused(db_session, zerodha):
    pos = _bought(db_session, zerodha)
    zerodha.hold["RELIANCE"] = 3  # sold 7 in the Kite app; the row here is stale
    with pytest.raises(real_orders.RealOrderRefusedError, match="Zerodha shows you own 3"):
        real_orders.sell(db_session, pos.id, None, "owner")
    assert all(p["transaction_type"] == "BUY" for p in zerodha.placed)


def test_selling_more_than_the_row_holds_is_refused(db_session, zerodha):
    pos = _bought(db_session, zerodha)
    zerodha.hold["RELIANCE"] = 50
    with pytest.raises(real_orders.RealOrderRefusedError, match="between 1 and 10"):
        real_orders.sell(db_session, pos.id, 11, "owner")


def test_a_bot_position_cannot_be_sold_from_here(db_session, zerodha):
    bot = Strategy(name="bot_strategy", strategy_type="ml_swing", mode="paper")
    db_session.add(bot)
    db_session.flush()
    pos = Position(
        strategy_id=bot.id,
        instrument_id=zerodha.inst.id,
        mode="paper",
        status="OPEN",
        quantity=5,
        entry_price=500.0,
        entry_at=datetime.now(UTC),
    )
    db_session.add(pos)
    db_session.flush()
    with pytest.raises(real_orders.RealOrderRefusedError, match="not an open holding"):
        real_orders.sell(db_session, pos.id, None, "owner")


def test_the_kill_switch_never_blocks_a_real_sell(db_session, zerodha):
    pos = _bought(db_session, zerodha)
    zerodha.hold["RELIANCE"] = 10
    system_state.halt(db_session, reason="drill", by="test")
    assert real_orders.sell(db_session, pos.id, None, "owner").transaction_type == "SELL"


# --- the 15:48 sync and the API ---------------------------------------------------------------------


def test_the_holdings_sync_never_closes_a_holding_bought_today(db_session, zerodha):
    pos = _bought(db_session, zerodha)
    strategy = db_session.get(Strategy, pos.strategy_id)
    assert holdings_sync.close_positions_no_longer_held(db_session, strategy, set()) == []
    db_session.refresh(pos)
    assert pos.status == "OPEN"
    pos.entry_at = datetime.now(UTC) - timedelta(days=3)  # an older row really gone from Zerodha
    db_session.flush()
    closed = holdings_sync.close_positions_no_longer_held(db_session, strategy, set())
    assert [c["symbol"] for c in closed] == ["RELIANCE"]


def test_the_api_is_owner_only_and_reports_the_latch(client, db_session, monkeypatch):
    from swing_trade_ml.core.security import create_access_token
    from swing_trade_ml.db.models.session import User

    guest = User(username="real-guest", hashed_password="x", is_active=True, is_superuser=False, plan="free")
    db_session.add(guest)
    db_session.flush()
    g = {"Authorization": f"Bearer {create_access_token(guest.username, {'uid': guest.id})}"}
    assert (
        client.post(
            "/api/v1/portfolio/real/buy", json={"symbol": "RELIANCE", "quantity": 1}, headers=g
        ).status_code
        == 403
    )
    assert client.get("/api/v1/portfolio/real/orders-status", headers=g).status_code == 403

    monkeypatch.setattr(settings, "ALLOW_REAL_HOLDINGS_ORDERS", False)
    s = client.get("/api/v1/portfolio/real/orders-status", headers=OWNER).json()
    assert s["enabled"] is False and s["plain"] == "Real orders are switched off."
    r = client.post("/api/v1/portfolio/real/buy", json={"symbol": "RELIANCE", "quantity": 1}, headers=OWNER)
    assert r.status_code == 409 and "switched off" in r.json()["detail"]
