"""The "Your Zerodha account" summary on My Holdings: live, read-only totals
for the whole Zerodha account, the way Zerodha's own dashboard shows them."""

from __future__ import annotations

import pytest

from swing_trade_ml.brokers import BrokerMargins
from swing_trade_ml.brokers.kite import kite_broker

HEADERS = {"X-API-Key": "test-api-key"}
URL = "/api/v1/portfolio/real/account"

HOLDINGS = [
    {
        "tradingsymbol": "SETTLED", "exchange": "NSE", "quantity": 5, "t1_quantity": 0,
        "average_price": 100.0, "last_price": 110.0, "day_change": 2.0,
    },
    {
        # Bought in the last day or two: Zerodha reports it only in t1_quantity.
        "tradingsymbol": "JUSTBOUGHT", "exchange": "NSE", "quantity": 0, "t1_quantity": 4,
        "average_price": 200.0, "last_price": 190.0, "day_change": -5.0,
    },
    {
        "tradingsymbol": "SOLDOUT", "exchange": "NSE", "quantity": 0, "t1_quantity": 0,
        "average_price": 50.0, "last_price": 60.0, "day_change": 1.0,
    },
]


@pytest.fixture
def zerodha(monkeypatch):
    monkeypatch.setattr(kite_broker, "load_session", lambda db: True)
    monkeypatch.setattr(kite_broker, "_token_loaded", True)
    monkeypatch.setattr(kite_broker, "get_holdings", lambda db: [dict(h) for h in HOLDINGS])
    monkeypatch.setattr(
        kite_broker, "get_margins",
        lambda db: BrokerMargins(available_cash=12_345.5, used_margin=0.0, total=12_345.5),
    )


def test_the_summary_adds_up_the_whole_account(client, zerodha):
    r = client.get(URL, headers=HEADERS)
    assert r.status_code == 200, r.text
    s = r.json()

    assert s["cash_available"] == 12_345.5
    assert s["invested"] == 5 * 100.0 + 4 * 200.0  # 1,300
    assert s["current_value"] == 5 * 110.0 + 4 * 190.0  # 1,310
    assert s["total_pnl"] == 10.0
    assert s["total_pnl_pct"] == pytest.approx(10.0 / 1300.0)
    assert s["day_pnl"] == 5 * 2.0 + 4 * -5.0  # -10
    assert s["account_value"] == 12_345.5 + 1310.0
    assert s["stocks"] == 2


def test_no_zerodha_session_is_a_plain_400(client, monkeypatch):
    monkeypatch.setattr(kite_broker, "load_session", lambda db: False)
    monkeypatch.setattr(kite_broker, "_token_loaded", False)
    r = client.get(URL, headers=HEADERS)
    assert r.status_code == 400 and "log in" in r.json()["detail"].lower()


def test_an_empty_account_shows_zeros_not_an_error(client, zerodha, monkeypatch):
    monkeypatch.setattr(kite_broker, "get_holdings", lambda db: [])
    s = client.get(URL, headers=HEADERS).json()
    assert s["invested"] == 0 and s["total_pnl_pct"] is None and s["account_value"] == 12_345.5


def test_no_credentials_is_refused(client, zerodha):
    assert client.get(URL).status_code in (401, 403)
