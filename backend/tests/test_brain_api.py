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
    ids = [m["id"] for m in body["modules"]]
    assert ids == ["M01", "M02", "M03", "M04", "M05", "M06", "M07", "M08", "M10", "M11", "M12", "M13", "M14"]


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


def test_a_run_shows_its_sector_table(client, db_session, stock):
    from brain_fakes import make_module, registry
    from swing_trade_ml.brain import contracts as c
    from swing_trade_ml.brain import service
    from swing_trade_ml.brain.module import Step

    def sectors(view):
        return c.Contribution(
            sectors=(
                c.SectorState(sector="NIFTY IT", rank=1, of_total=2, strength_20d=0.03, rotation="leading"),
                c.SectorState(
                    sector="NIFTY BANK", rank=2, of_total=2, strength_20d=-0.01, rotation="lagging"
                ),
            )
        )

    plug = make_module("M11", Step.STATE, writes=("SectorState@1",), run=sectors, kind="plugin")
    _, run_id = service.run_brain(db_session, symbols=["BRAINAPI"], as_of=AS_OF, registry=registry(plug))
    db_session.commit()
    body = client.get(f"/api/v1/brain/runs/{run_id}", headers=HEADERS).json()
    assert [(s["rank"], s["name"], s["rotation"]) for s in body["sectors"]] == [
        (1, "IT", "leading"),
        (2, "Banks", "lagging"),
    ]
    assert body["sectors"][0]["strength_20d"] == 0.03


def test_runs_without_context_show_no_sectors(client, stock):
    r = client.post(
        "/api/v1/brain/runs",
        json={"kind": "nightly", "symbols": ["BRAINAPI"], "as_of": AS_OF.isoformat()},
        headers=HEADERS,
    )
    body = client.get(f"/api/v1/brain/runs/{r.json()['run_id']}", headers=HEADERS).json()
    assert body["sectors"] == []


def test_market_episodes_are_listed_newest_first(client, db_session):
    from datetime import date

    from swing_trade_ml.db.models.brain import BrainEpisode

    db_session.add_all(
        [
            BrainEpisode(
                scope="market",
                label="correction",
                start_day=date(2026, 3, 2),
                end_day=date(2026, 4, 10),
                stats={"days": 28, "nifty_change": -0.08},
            ),
            BrainEpisode(
                scope="market",
                label="up-trend",
                start_day=date(2026, 4, 13),
                end_day=None,
                stats={"days": 100, "nifty_change": 0.05},
            ),
        ]
    )
    db_session.commit()
    body = client.get("/api/v1/brain/episodes", headers=HEADERS).json()
    assert [(e["label"], e["start_day"], e["end_day"]) for e in body] == [
        ("up-trend", "2026-04-13", None),
        ("correction", "2026-03-02", "2026-04-10"),
    ]
    assert body[1]["days"] == 28 and body[1]["nifty_change"] == -0.08
