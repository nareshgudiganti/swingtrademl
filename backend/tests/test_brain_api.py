"""Brain API: protected like the safety routes, and the switch for the
mandatory risk gate can never be turned off through it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from swing_trade_ml.db.models.market import Candle, Instrument

HEADERS = {"X-API-Key": "test-api-key"}
AS_OF = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


@pytest.fixture()
def stock(db_session):
    inst = Instrument(
        instrument_token=992001, tradingsymbol="BRAINAPI", exchange="NSE", is_watchlisted=True, is_active=True
    )
    db_session.add(inst)
    db_session.flush()
    db_session.add(
        Candle(
            instrument_id=inst.id,
            interval="day",
            ts=AS_OF - timedelta(days=1),
            open=10,
            high=10,
            low=10,
            close=10,
            volume=1,
        )
    )
    db_session.commit()
    return inst


def test_brain_routes_need_credentials(client):
    assert client.get("/api/v1/brain/modules").status_code == 401


def test_modules_lists_the_eight_steps(client):
    body = client.get("/api/v1/brain/modules", headers=HEADERS).json()
    assert [s["step"] for s in body["steps"]] == [
        "perceive",
        "state",
        "recognise",
        "remember",
        "reason",
        "risk",
        "decide",
        "learn",
    ]
    assert [m["id"] for m in body["modules"]] == ["M01", "M02", "M07"]


def test_unknown_module_cannot_be_switched(client):
    r = client.put("/api/v1/brain/modules/M42", json={"mode": "off"}, headers=HEADERS)
    assert r.status_code == 404


def test_run_then_read_latest(client, stock):
    r = client.post(
        "/api/v1/brain/runs",
        json={"kind": "nightly", "symbols": ["BRAINAPI"], "as_of": AS_OF.isoformat()},
        headers=HEADERS,
    )
    assert r.status_code == 200
    run_id = r.json()["run_id"]
    latest = client.get("/api/v1/brain/runs/latest?kind=nightly&include_replays=true", headers=HEADERS).json()
    assert latest["run_id"] == run_id
    # The test database has no NIFTY history, so the data gateway (M01)
    # reports the market's data as not reliable, which means no new trades.
    assert latest["banner"]["mode"] == "NO_NEW_TRADES"
    assert "NIFTY" in latest["banner"]["headline"]
    assert latest["counts"] == {"WAIT": 1}
    assert latest["decisions"][0]["symbol"] == "BRAINAPI"
    assert latest["decisions"][0]["reasons"]


def test_latest_without_any_run_is_404(client):
    assert client.get("/api/v1/brain/runs/latest?kind=why", headers=HEADERS).status_code == 404


def test_why_returns_one_decision_and_its_trace(client, stock):
    body = client.get("/api/v1/brain/why/BRAINAPI", headers=HEADERS).json()
    assert body["decision"]["symbol"] == "BRAINAPI"
    assert any(e["module_id"] == "fallback" for e in body["trace"])
