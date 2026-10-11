"""GET /market-data/sectors — plain sector names for a list of stocks.

A pure lookup in ml/sector_map.py (no database read); it exists so the
dashboard can show a Sector column and filter by it.
"""

from __future__ import annotations

HEADERS = {"X-API-Key": "test-api-key"}


def test_requires_auth(client):
    resp = client.get("/api/v1/market-data/sectors?symbols=INFY")
    assert resp.status_code in (401, 403)


def test_known_symbols_get_plain_sector_names(client):
    resp = client.get("/api/v1/market-data/sectors?symbols=INFY,reliance", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json() == {"INFY": "IT", "RELIANCE": "Energy"}


def test_unmapped_symbol_is_null_not_a_guess(client):
    resp = client.get("/api/v1/market-data/sectors?symbols=NOTASTOCK", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json() == {"NOTASTOCK": None}


def test_empty_list_is_empty(client):
    resp = client.get("/api/v1/market-data/sectors?symbols=", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json() == {}
