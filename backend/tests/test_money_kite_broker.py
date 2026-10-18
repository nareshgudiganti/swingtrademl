"""KiteBroker against a fake Kite client — no network, no real orders (qa8 coverage floor).

Every test swaps `broker._kite` for an in-memory fake and, where the login flow is exercised, replaces
`requests` with a fake too. Nothing here can reach Zerodha. The tests pin the parts that protect money:
the live-mode latch at the point of no return, how a broker refusal is reported, and how unknown order
states are read (always as "still waiting", never as filled).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from kiteconnect.exceptions import KiteException

from swing_trade_ml.brokers.base import REAL_HOLDINGS_TAG_PREFIX, OrderRequest
from swing_trade_ml.brokers.kite import KiteAuthError, KiteBroker
from swing_trade_ml.core import config
from swing_trade_ml.core.enums import OrderStatus, OrderType, ProductType, TransactionType
from swing_trade_ml.db.models.session import BrokerSession

TOTP_SEED = "JBSWY3DPEHPK3PXP"  # a well-known dummy base32 seed, not a real credential


class FakeKite:
    VARIETY_REGULAR = "regular"

    def __init__(self) -> None:
        self.placed: list[dict] = []
        self.token: str | None = None
        self.fail_place: Exception | None = None
        self.fail_cancel = False
        self.fail_history = False
        self.history: list[dict] = []
        self.positions_data: dict = {"net": []}
        self.holdings_data: list[dict] = []
        self.session_data: dict = {}

    def login_url(self) -> str:
        return "https://kite.example/connect/login?v=3"

    def set_access_token(self, token: str) -> None:
        self.token = token

    def generate_session(self, request_token, api_secret=None):
        return self.session_data

    def place_order(self, **kwargs):
        if self.fail_place is not None:
            raise self.fail_place
        self.placed.append(kwargs)
        return 990001

    def cancel_order(self, variety, order_id):
        if self.fail_cancel:
            raise KiteException("cannot cancel")
        return order_id

    def order_history(self, order_id):
        if self.fail_history:
            raise KiteException("history unavailable")
        return self.history

    def positions(self):
        return self.positions_data

    def holdings(self):
        return self.holdings_data

    def trades(self):
        return [{"trade_id": "T1"}]

    def margins(self):
        return {"equity": {"available": {"live_balance": 5000.0}, "utilised": {"debits": 1500.0}}}

    def ltp(self, symbols):
        return {s: {"last_price": 101.5} for s in symbols}

    def quote(self, symbols):
        return {s: {"last_price": 99.0, "depth": {}} for s in symbols}

    def historical_data(self, **kwargs):
        return [{"date": kwargs["from_date"], "close": 10.0}]

    def instruments(self, exchange):
        return [{"tradingsymbol": "TCS", "exchange": exchange}]


@pytest.fixture
def broker(monkeypatch):
    b = KiteBroker()
    b._kite = FakeKite()
    # Latches closed by default — the paper configuration every test starts from.
    monkeypatch.setattr(config.settings, "TRADING_MODE", "paper", raising=False)
    monkeypatch.setattr(config.settings, "ALLOW_LIVE_TRADING", False, raising=False)
    monkeypatch.setattr(config.settings, "ALLOW_REAL_HOLDINGS_ORDERS", False, raising=False)
    return b


def _open_latches(monkeypatch):
    monkeypatch.setattr(config.settings, "TRADING_MODE", "live", raising=False)
    monkeypatch.setattr(config.settings, "ALLOW_LIVE_TRADING", True, raising=False)


def _req(order_type=OrderType.MARKET, tag=None, price=None) -> OrderRequest:
    return OrderRequest(
        tradingsymbol="INFY",
        exchange="NSE",
        transaction_type=TransactionType.BUY,
        quantity=3,
        order_type=order_type,
        product=ProductType.CNC,
        price=price,
        tag=tag,
    )


# ------------------------------------------------------------- order latch --


def test_paper_mode_refuses_to_place_a_live_order(broker):
    with pytest.raises(RuntimeError, match="Refusing to place a live order"):
        broker.place_order(_req(), db=None)
    assert broker._kite.placed == []


def test_live_mode_alone_is_not_enough(broker, monkeypatch):
    monkeypatch.setattr(config.settings, "TRADING_MODE", "live", raising=False)
    with pytest.raises(RuntimeError):
        broker.place_order(_req(), db=None)
    assert broker._kite.placed == []


def test_holdings_tag_without_its_latch_is_refused(broker):
    with pytest.raises(RuntimeError):
        broker.place_order(_req(tag=f"{REAL_HOLDINGS_TAG_PREFIX}b1"), db=None)
    assert broker._kite.placed == []


def test_holdings_tag_with_its_latch_passes_the_gate_but_still_needs_a_session(broker, monkeypatch):
    monkeypatch.setattr(config.settings, "ALLOW_REAL_HOLDINGS_ORDERS", True, raising=False)
    with pytest.raises(KiteAuthError):
        broker.place_order(_req(tag=f"{REAL_HOLDINGS_TAG_PREFIX}b1"), db=None)


def test_latches_open_but_no_session_refuses(broker, monkeypatch):
    _open_latches(monkeypatch)
    with pytest.raises(KiteAuthError):
        broker.place_order(_req(), db=None)
    assert broker._kite.placed == []


def test_market_order_is_sent_with_market_protection_and_returns_pending(broker, monkeypatch):
    _open_latches(monkeypatch)
    broker._token_loaded = True
    result = broker.place_order(_req(OrderType.MARKET, tag="stml-1"), db=None)
    assert result.status == OrderStatus.PENDING and result.broker_order_id == "990001"
    sent = broker._kite.placed[0]
    assert sent["market_protection"] == config.settings.KITE_MARKET_PROTECTION
    assert sent["transaction_type"] == "BUY" and sent["quantity"] == 3 and sent["product"] == "CNC"


def test_limit_order_carries_no_market_protection(broker, monkeypatch):
    _open_latches(monkeypatch)
    broker._token_loaded = True
    broker.place_order(_req(OrderType.LIMIT, price=100.0), db=None)
    assert broker._kite.placed[0]["market_protection"] is None
    assert broker._kite.placed[0]["price"] == 100.0


def test_broker_refusal_is_reported_as_rejected_not_raised(broker, monkeypatch):
    _open_latches(monkeypatch)
    broker._token_loaded = True
    broker._kite.fail_place = KiteException("Insufficient funds")
    result = broker.place_order(_req(), db=None)
    assert result.status == OrderStatus.REJECTED
    assert result.broker_order_id == ""
    assert "Insufficient funds" in result.message


# ---------------------------------------------------------- order handling --


def test_every_authenticated_call_requires_a_session(broker):
    for call in (
        lambda: broker.cancel_order("1", None),
        lambda: broker.get_order_status("1", None),
        lambda: broker.get_positions(None),
        lambda: broker.get_margins(None),
        lambda: broker.get_holdings(None),
        lambda: broker.get_trades(None),
        lambda: broker.owned_quantity("INFY", None),
    ):
        with pytest.raises(KiteAuthError):
            call()


def test_cancel_order_success_and_failure(broker):
    broker._token_loaded = True
    assert broker.cancel_order("42", None) is True
    broker._kite.fail_cancel = True
    assert broker.cancel_order("42", None) is False


def test_order_status_reads_latest_history_row(broker):
    broker._token_loaded = True
    broker._kite.history = [
        {"status": "OPEN"},
        {"status": "COMPLETE", "filled_quantity": 3, "average_price": 101.0, "status_message": None},
    ]
    result = broker.get_order_status("42", None)
    assert result.status == OrderStatus.COMPLETE
    assert result.filled_quantity == 3 and result.average_price == 101.0


def test_unknown_intermediate_status_reads_as_still_open(broker):
    broker._token_loaded = True
    broker._kite.history = [{"status": "TRIGGER PENDING", "filled_quantity": None}]
    result = broker.get_order_status("42", None)
    assert result.status == OrderStatus.OPEN
    assert result.filled_quantity == 0


def test_order_status_none_on_error_or_empty_history(broker):
    broker._token_loaded = True
    assert broker.get_order_status("42", None) is None
    broker._kite.fail_history = True
    assert broker.get_order_status("42", None) is None


# ---------------------------------------------------------------- portfolio --


def test_positions_skip_flat_rows(broker):
    broker._token_loaded = True
    broker._kite.positions_data = {
        "net": [
            {
                "tradingsymbol": "INFY",
                "exchange": "NSE",
                "quantity": 5,
                "average_price": 10.0,
                "last_price": 11.0,
                "pnl": 5.0,
            },
            {
                "tradingsymbol": "TCS",
                "exchange": "NSE",
                "quantity": 0,
                "average_price": 1.0,
                "last_price": 1.0,
                "pnl": 0.0,
            },
        ]
    }
    positions = broker.get_positions(None)
    assert [p.tradingsymbol for p in positions] == ["INFY"]


def test_owned_quantity_adds_settled_settling_and_todays_cnc_buys(broker):
    broker._token_loaded = True
    broker._kite.holdings_data = [
        {"tradingsymbol": "INFY", "quantity": 4, "t1_quantity": 2},
        {"tradingsymbol": "TCS", "quantity": 9, "t1_quantity": 0},
    ]
    broker._kite.positions_data = {
        "net": [
            {"tradingsymbol": "INFY", "quantity": 3, "product": "CNC"},
            {"tradingsymbol": "INFY", "quantity": 7, "product": "MIS"},  # intraday, not owned
        ]
    }
    assert broker.owned_quantity("INFY", None) == 9


def test_owned_quantity_never_negative(broker):
    broker._token_loaded = True
    broker._kite.positions_data = {"net": [{"tradingsymbol": "INFY", "quantity": -5, "product": "CNC"}]}
    assert broker.owned_quantity("INFY", None) == 0


def test_holdings_trades_margins(broker):
    broker._token_loaded = True
    broker._kite.holdings_data = [{"tradingsymbol": "INFY"}]
    assert broker.get_holdings(None) == [{"tradingsymbol": "INFY"}]
    assert broker.get_trades(None) == [{"trade_id": "T1"}]
    m = broker.get_margins(None)
    assert (m.available_cash, m.used_margin, m.total) == (5000.0, 1500.0, 6500.0)


# --------------------------------------------------------------- market data --


def test_market_data_calls(broker):
    broker._token_loaded = True
    assert broker.get_ltp([], None) == {}
    assert broker.get_ltp(["NSE:INFY"], None) == {"NSE:INFY": 101.5}
    assert broker.get_quote([], None) == {}
    assert broker.get_quote(["NSE:INFY"], None)["NSE:INFY"]["last_price"] == 99.0
    start = datetime(2026, 1, 1, tzinfo=UTC)
    assert broker.get_historical_data(1, start, start, "day", None)[0]["close"] == 10.0
    assert broker.get_instruments("NSE")[0]["tradingsymbol"] == "TCS"
    assert broker.login_url().startswith("https://")
    assert broker.client is broker._kite


def test_market_data_without_session_raises(broker):
    with pytest.raises(KiteAuthError):
        broker.get_ltp(["NSE:INFY"], None)


# ---------------------------------------------------------- reauth_and_retry --


def test_reauth_reraises_errors_that_are_not_a_rejected_token(broker):
    def boom():
        raise ValueError("network down")

    with pytest.raises(ValueError):
        broker.reauth_and_retry(None, boom)


def test_reauth_without_autologin_config_reraises(broker, monkeypatch):
    monkeypatch.setattr(config.settings, "KITE_USER_ID", "", raising=False)

    def rejected():
        raise KiteException("Incorrect `api_key` or `access_token`.")

    with pytest.raises(KiteException):
        broker.reauth_and_retry(None, rejected)


# ------------------------------------------------------------ session / login --


def test_complete_login_refuses_someone_elses_account(broker, monkeypatch):
    monkeypatch.setattr(config.settings, "KITE_USER_ID", "ab1234", raising=False)
    broker._kite.session_data = {"user_id": "ZZ9999", "access_token": "tok"}
    with pytest.raises(PermissionError):
        broker.complete_login("req", db=None)
    assert broker.is_authenticated is False


def test_complete_login_saves_session_and_loads_token(broker, monkeypatch, db_session):
    monkeypatch.setattr(config.settings, "KITE_USER_ID", "ab1234", raising=False)
    old = BrokerSession(broker="zerodha", access_token="old", is_active=True)
    db_session.add(old)
    db_session.flush()
    broker._kite.session_data = {"user_id": " AB1234 ", "user_name": "Owner", "access_token": "tok"}
    session = broker.complete_login("req", db_session)
    assert session.is_active and session.access_token == "tok"
    db_session.refresh(old)
    assert old.is_active is False
    assert broker.is_authenticated and broker._kite.token == "tok"


def _clear_sessions(db_session):
    db_session.query(BrokerSession).update({"is_active": False})
    db_session.flush()


def test_load_session_none_expired_and_restored(broker, db_session):
    _clear_sessions(db_session)
    broker._token_loaded = True
    assert broker.load_session(db_session) is False
    assert broker.is_authenticated is False and broker.loaded_session_id is None

    expired = BrokerSession(
        broker="zerodha",
        access_token="x",
        is_active=True,
        expires_at=datetime.now(UTC) - timedelta(hours=1),
    )
    db_session.add(expired)
    db_session.flush()
    assert broker.load_session(db_session) is False
    assert expired.is_active is False

    fresh = BrokerSession(
        broker="zerodha",
        access_token="fresh",
        is_active=True,
        expires_at=datetime.now(UTC) + timedelta(hours=5),
    )
    db_session.add(fresh)
    db_session.flush()
    assert broker.load_session(db_session) is True
    assert broker.loaded_session_id == fresh.id and broker._kite.token == "fresh"
    broker._kite.token = None
    assert broker.load_session(db_session) is True  # same session: no second set_access_token
    assert broker._kite.token is None


class _Resp:
    def __init__(self, status=200, data=None, headers=None):
        self.status_code = status
        self._data = data or {}
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._data


class _FakeHttp:
    def __init__(self, login_data, redirects):
        self.login_data = login_data
        self.redirects = list(redirects)
        self.posts: list[str] = []

    def post(self, url, data=None, timeout=None):
        self.posts.append(url)
        if url.endswith("/api/login"):
            return _Resp(data={"data": self.login_data})
        return _Resp()

    def get(self, url, allow_redirects=False, timeout=None):
        loc = self.redirects.pop(0) if self.redirects else None
        return _Resp(headers={"Location": loc} if loc else {})


def _autologin_settings(monkeypatch):
    monkeypatch.setattr(config.settings, "KITE_USER_ID", "AB1234", raising=False)
    monkeypatch.setattr(config.settings, "KITE_PASSWORD", "pw", raising=False)
    monkeypatch.setattr(config.settings, "KITE_TOTP_SECRET", TOTP_SEED, raising=False)


def test_auto_login_unconfigured_raises(broker, monkeypatch):
    monkeypatch.setattr(config.settings, "KITE_USER_ID", "", raising=False)
    with pytest.raises(RuntimeError, match="not configured"):
        broker.auto_login(None)


def test_auto_login_refuses_when_totp_not_offered(broker, monkeypatch):
    import requests

    _autologin_settings(monkeypatch)
    http = _FakeHttp({"request_id": "r1", "twofa_types": ["app_code", "sms"]}, [])
    monkeypatch.setattr(requests, "Session", lambda: http)
    with pytest.raises(KiteAuthError, match="TOTP"):
        broker.auto_login(None)
    assert not any(u.endswith("/api/twofa") for u in http.posts)


def test_auto_login_walks_redirects_to_request_token(broker, monkeypatch):
    import requests

    _autologin_settings(monkeypatch)
    http = _FakeHttp(
        {"request_id": "r1", "twofa_types": ["totp"]},
        [
            "https://kite.example/connect/finish?sess=1",
            "https://our.app/cb?request_token=RT42&status=success",
        ],
    )
    monkeypatch.setattr(requests, "Session", lambda: http)
    seen = {}
    monkeypatch.setattr(broker, "complete_login", lambda token, db: seen.setdefault("token", token))
    assert broker.auto_login(None) == "RT42"
    assert any(u.endswith("/api/twofa") for u in http.posts)


def test_walk_redirect_without_token_raises(broker):
    with pytest.raises(KiteAuthError, match="request_token"):
        broker._walk_authorize_redirect(_FakeHttp({}, ["https://kite.example/a"]))


def test_login_diagnostics_paths(broker, monkeypatch):
    import requests

    monkeypatch.setattr(config.settings, "KITE_USER_ID", "", raising=False)
    assert broker.login_diagnostics()["ok"] is False

    _autologin_settings(monkeypatch)
    monkeypatch.setattr(config.settings, "KITE_TOTP_SECRET", "not base32 !!", raising=False)
    out = broker.login_diagnostics()
    assert out["ok"] is False and out["totp_generates"] is False

    _autologin_settings(monkeypatch)

    def unreachable(*a, **kw):
        raise ConnectionError("no route")

    monkeypatch.setattr(requests, "post", unreachable)
    assert "Could not reach" in broker.login_diagnostics()["reason"]

    monkeypatch.setattr(requests, "post", lambda *a, **kw: _Resp(status=403))
    out = broker.login_diagnostics()
    assert out["ok"] is False and out["login_http_status"] == 403

    monkeypatch.setattr(
        requests, "post", lambda *a, **kw: _Resp(data={"data": {"twofa_types": ["sms"], "request_id": "r"}})
    )
    out = broker.login_diagnostics()
    assert out["ok"] is False and out["totp_available"] is False

    monkeypatch.setattr(
        requests, "post", lambda *a, **kw: _Resp(data={"data": {"twofa_types": ["totp"], "request_id": "r"}})
    )
    out = broker.login_diagnostics()
    assert out["ok"] is True and out["request_id_received"] is True
    assert TOTP_SEED not in str(out)


def test_token_rejected_matcher():
    assert KiteBroker._is_token_rejected(Exception("Incorrect `api_key` or `access_token`."))
    assert not KiteBroker._is_token_rejected(Exception("Insufficient funds"))
