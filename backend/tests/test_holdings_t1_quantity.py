"""Regression test for the T1 (unsettled) holdings bug.

Kite reports a stock bought in the last day or two with `quantity: 0` and
the real count sitting in `t1_quantity` until it settles into demat. Filtering
or importing on `quantity` alone silently dropped every recent buy from the
holdings list, the import, and every P&L total built from them.
"""

from swing_trade_ml.api.v1.endpoints.portfolio import _held_quantity


def test_held_quantity_adds_unsettled_t1_shares():
    settled = {"tradingsymbol": "ABC", "quantity": 5, "t1_quantity": 0}
    just_bought = {"tradingsymbol": "XYZ", "quantity": 0, "t1_quantity": 4}
    partially_settled = {"tradingsymbol": "PQR", "quantity": 2, "t1_quantity": 3}

    assert _held_quantity(settled) == 5
    assert _held_quantity(just_bought) == 4
    assert _held_quantity(partially_settled) == 5


def test_held_quantity_defaults_t1_to_zero_when_field_missing():
    assert _held_quantity({"tradingsymbol": "ABC", "quantity": 5}) == 5


def test_holdings_endpoint_includes_unsettled_t1_only_stocks(client, monkeypatch):
    from swing_trade_ml.brokers.kite import kite_broker

    monkeypatch.setattr(kite_broker, "load_session", lambda db: None)
    monkeypatch.setattr(kite_broker, "_token_loaded", True)
    monkeypatch.setattr(
        kite_broker,
        "get_holdings",
        lambda db: [
            {
                "tradingsymbol": "SETTLED",
                "exchange": "NSE",
                "quantity": 5,
                "t1_quantity": 0,
                "average_price": 100.0,
                "last_price": 110.0,
                "close_price": 108.0,
                "pnl": 50.0,
                "day_change": 2.0,
                "day_change_percentage": 1.85,
            },
            {
                "tradingsymbol": "JUSTBOUGHT",
                "exchange": "NSE",
                "quantity": 0,
                "t1_quantity": 4,
                "average_price": 200.0,
                "last_price": 210.0,
                "close_price": 205.0,
                "pnl": 0.0,
                "day_change": 5.0,
                "day_change_percentage": 2.5,
            },
        ],
    )

    resp = client.get("/api/v1/portfolio/holdings", headers={"X-API-Key": "test-api-key"})

    assert resp.status_code == 200
    by_symbol = {h["symbol"]: h for h in resp.json()}
    assert set(by_symbol) == {"SETTLED", "JUSTBOUGHT"}
    assert by_symbol["JUSTBOUGHT"]["quantity"] == 4
    assert by_symbol["JUSTBOUGHT"]["pnl"] == (210.0 - 200.0) * 4
