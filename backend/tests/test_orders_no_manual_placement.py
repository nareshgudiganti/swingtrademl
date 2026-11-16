"""Codex audit finding 2: `POST /orders` placed an order with no sizing, no kill-switch check, no entry
risk check and no stop-loss. The endpoint is removed. Reading, cancelling and syncing orders still work.
"""

from __future__ import annotations

from swing_trade_ml.db.models.trading import Order

HEADERS = {"X-API-Key": "test-api-key"}
API = "/api/v1/orders"
BODY = {
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "transaction_type": "BUY",
    "order_type": "MARKET",
    "product": "CNC",
    "quantity": 1,
}


def test_post_orders_is_not_available_and_places_nothing(client, db_session):
    before = db_session.query(Order).count()
    for body in (BODY, {}):
        response = client.post(API, json=body, headers=HEADERS)
        assert response.status_code == 405, response.text
    assert db_session.query(Order).count() == before


def test_the_api_description_lists_no_way_to_place_an_order():
    from swing_trade_ml.main import app

    paths = app.openapi()["paths"]
    orders = paths.get("/api/v1/orders")
    assert orders is not None and "get" in orders, "the orders list route should still exist"
    assert "post" not in orders
    assert "/api/v1/orders/{order_id}/cancel" in paths and "/api/v1/orders/sync" in paths


def test_reading_cancelling_and_syncing_orders_still_work(client):
    assert client.get(API, headers=HEADERS).status_code == 200
    assert client.get(f"{API}/999999999", headers=HEADERS).status_code == 404
    assert client.post(f"{API}/999999999/cancel", headers=HEADERS).status_code == 404
    assert client.post(f"{API}/sync", headers=HEADERS).status_code == 200
