"""What the brain console needs from the API: a run list, the data quality of
each run, failed runs that are kept rather than lost, health, and an overrule
that can only make a decision more cautious."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from swing_trade_ml.brain import service
from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
from swing_trade_ml.db.models.market import Candle, Instrument

HEADERS = {"X-API-Key": "test-api-key"}
AS_OF = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


@pytest.fixture()
def stock(db_session):
    inst = Instrument(
        instrument_token=995001, tradingsymbol="CONSOLE1", exchange="NSE", is_watchlisted=True, is_active=True
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


def _run(client):
    r = client.post(
        "/api/v1/brain/runs",
        json={"kind": "nightly", "symbols": ["CONSOLE1"], "as_of": AS_OF.isoformat()},
        headers=HEADERS,
    )
    assert r.status_code == 200
    return r.json()


def test_runs_are_listed_newest_first_with_counts(client, stock):
    first = _run(client)["run_id"]
    second = _run(client)["run_id"]
    runs = client.get("/api/v1/brain/runs?kind=nightly&limit=5", headers=HEADERS).json()
    assert [r["run_id"] for r in runs[:2]] == [second, first]
    assert runs[0]["counts"] == {"WAIT": 1}
    assert "decisions" not in runs[0]


def test_one_run_can_be_read_by_id(client, stock):
    run_id = _run(client)["run_id"]
    body = client.get(f"/api/v1/brain/runs/{run_id}", headers=HEADERS).json()
    assert body["run_id"] == run_id and body["decisions"][0]["id"]


def test_each_run_stores_its_data_quality(client, stock):
    body = _run(client)
    assert body["quality"]["overall"]["fresh"] is False
    assert "CONSOLE1" in body["quality"]["stale"]


def test_overrule_lowers_a_decision_and_records_who_and_why(client, stock):
    decision = _run(client)["decisions"][0]  # WAIT
    r = client.post(
        f"/api/v1/brain/decisions/{decision['id']}/overrule",
        json={"word": "AVOID", "reason": "Promoter selling", "by": "owner"},
        headers=HEADERS,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["word"] == "WAIT" and body["overruled_word"] == "AVOID"
    assert body["overrule_reason"] == "Promoter selling" and body["overruled_by"] == "owner"


def test_overrule_to_a_bolder_word_is_refused(client, stock):
    decision = _run(client)["decisions"][0]  # WAIT
    r = client.post(
        f"/api/v1/brain/decisions/{decision['id']}/overrule",
        json={"word": "TRADE", "reason": "I like it"},
        headers=HEADERS,
    )
    assert r.status_code == 409


def test_overrule_to_a_word_from_the_other_vocabulary_is_refused(client, stock):
    decision = _run(client)["decisions"][0]
    r = client.post(
        f"/api/v1/brain/decisions/{decision['id']}/overrule",
        json={"word": "EXIT", "reason": "x"},
        headers=HEADERS,
    )
    assert r.status_code == 409


def test_overrule_needs_a_reason(client, stock):
    decision = _run(client)["decisions"][0]
    r = client.post(
        f"/api/v1/brain/decisions/{decision['id']}/overrule",
        json={"word": "AVOID", "reason": "  "},
        headers=HEADERS,
    )
    assert r.status_code == 422


def test_overrule_of_an_unknown_decision_is_404(client):
    r = client.post(
        "/api/v1/brain/decisions/999999999/overrule", json={"word": "AVOID", "reason": "x"}, headers=HEADERS
    )
    assert r.status_code == 404


def test_a_crashing_run_is_kept_as_failed_and_counted(db_session, stock, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("database went away")

    monkeypatch.setattr(service, "execute", boom)
    with pytest.raises(RuntimeError):
        service.run_brain(db_session, kind="nightly", as_of=AS_OF, symbols=["CONSOLE1"])
    failed = db_session.query(BrainRun).filter_by(status="failed").all()
    assert failed and "database went away" in failed[-1].error
    assert service.health(db_session)["failed_runs_7d"] >= 1


def test_health_reports_the_last_run_and_data_problems(client, stock, db_session):
    service.run_brain(db_session, kind="nightly", symbols=["CONSOLE1"])  # a live run
    body = client.get("/api/v1/brain/health", headers=HEADERS).json()
    assert body["last_run"]["status"] == "done"
    assert body["data"]["fresh"] is False and body["data"]["issues"]


def test_decision_rows_keep_overrule_columns(db_session):
    assert {"overruled_word", "overrule_reason", "overruled_by", "overruled_at"} <= set(
        BrainDecision.__table__.columns.keys()
    )


def test_latest_skips_replays_unless_asked(client, stock, db_session):
    _ctx, live_id = service.run_brain(db_session, kind="nightly", symbols=["CONSOLE1"])
    replay_id = _run(client)["run_id"]  # a replay, started later
    latest = client.get("/api/v1/brain/runs/latest?kind=nightly", headers=HEADERS).json()
    assert latest["run_id"] == live_id
    with_replays = client.get("/api/v1/brain/runs/latest?kind=nightly&include_replays=true", headers=HEADERS)
    assert with_replays.json()["run_id"] == replay_id


def test_the_stale_list_counts_stocks_not_the_nifty_index():
    from brain_fakes import FakeReader, request
    from swing_trade_ml.brain import contracts as c
    from swing_trade_ml.brain.context import BrainContext
    from swing_trade_ml.core.config import settings

    ctx = BrainContext.start(request(), FakeReader())
    ctx.quality = {
        "ABC": c.DataQuality(symbol="ABC", score=0.2, fresh=False),
        settings.BENCHMARK_INDEX_SYMBOL: c.DataQuality(
            symbol=settings.BENCHMARK_INDEX_SYMBOL, score=0.2, fresh=False
        ),
        "*": c.DataQuality(symbol="*", score=0.2, fresh=False),
    }
    assert service._quality_summary(ctx)["stale"] == ["ABC"]
