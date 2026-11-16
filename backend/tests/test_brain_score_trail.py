"""The brain's own score, day by day, for one stock (GET /brain/score-trail/{symbol}).

The stock page's headline is the brain's score. Its day-by-day line must come from the SAME model, so this
series is read from the brain's stored decisions, never from the cap-tier daily check (a different model).
"""

from __future__ import annotations

from datetime import UTC, datetime

from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
from swing_trade_ml.services.brain_score_trail import model_from_reasons

HEADERS = {"X-API-Key": "test-api-key"}
MODEL_LINE = "The active model (swing_classifier v2) scores this stock {p}; its buy level is 60%."


def _run(db, run_id, started_at, *, status="done", live=True):
    db.add(BrainRun(id=run_id, kind="nightly", as_of=started_at, book="paper", live=live,
                    started_at=started_at, status=status))
    db.flush()


def _idea(db, run_id, symbol, confidence, reasons=None):
    if reasons is None:
        reasons = [MODEL_LINE.format(p=f"{confidence:.0%}")]
    db.add(BrainDecision(run_id=run_id, symbol=symbol, kind="idea", word="WAIT", confidence=confidence,
                         reasons=reasons))
    db.flush()


def test_model_is_read_from_the_brains_own_line():
    assert model_from_reasons(["x", MODEL_LINE.format(p="82%")]) == "swing_classifier v2"
    assert model_from_reasons(["no model named here"]) is None


def test_one_point_per_indian_day_newest_run_wins_and_ends_on_the_latest(client, db_session):
    # 13 Nov 18:00 IST, then two runs on 16 Nov (07:00 IST and 17:00 IST): the later one is that day's score.
    _run(db_session, "r13", datetime(2026, 11, 13, 12, 30, tzinfo=UTC))
    _idea(db_session, "r13", "DEEPAKNTR", 0.39)
    _run(db_session, "r16a", datetime(2026, 11, 16, 1, 30, tzinfo=UTC))
    _idea(db_session, "r16a", "DEEPAKNTR", 0.70)
    _run(db_session, "r16b", datetime(2026, 11, 16, 11, 30, tzinfo=UTC))
    _idea(db_session, "r16b", "DEEPAKNTR", 0.82)
    _idea(db_session, "r16b", "OTHER", 0.50)
    db_session.commit()

    body = client.get("/api/v1/brain/score-trail/deepakntr", headers=HEADERS).json()
    assert body["symbol"] == "DEEPAKNTR"
    assert body["score_trail"] == [
        {"date": "2026-11-13", "score": 0.39, "model_version": "swing_classifier v2"},
        {"date": "2026-11-16", "score": 0.82, "model_version": "swing_classifier v2"},
    ]


def test_skips_failed_superseded_and_replay_runs_and_scoreless_rows(client, db_session):
    _run(db_session, "ok", datetime(2026, 11, 10, 12, 30, tzinfo=UTC))
    _idea(db_session, "ok", "DEEPAKNTR", 0.29)
    _run(db_session, "failed", datetime(2026, 11, 11, 12, 30, tzinfo=UTC), status="failed")
    _idea(db_session, "failed", "DEEPAKNTR", 0.99)
    _run(db_session, "old", datetime(2026, 11, 12, 10, 0, tzinfo=UTC), status="superseded")
    _idea(db_session, "old", "DEEPAKNTR", 0.98)
    _run(db_session, "replay", datetime(2026, 11, 12, 12, 30, tzinfo=UTC), live=False)
    _idea(db_session, "replay", "DEEPAKNTR", 0.97)
    _run(db_session, "noscore", datetime(2026, 11, 13, 12, 30, tzinfo=UTC))
    _idea(db_session, "noscore", "DEEPAKNTR", None, reasons=[])
    db_session.commit()

    trail = client.get("/api/v1/brain/score-trail/DEEPAKNTR", headers=HEADERS).json()["score_trail"]
    assert [(t["date"], t["score"]) for t in trail] == [("2026-11-10", 0.29)]


def test_a_day_whose_row_names_no_model_takes_the_model_its_run_loaded(client, db_session):
    # One run loads one model for every stock, so another row of the same run names it.
    _run(db_session, "r", datetime(2026, 11, 14, 12, 30, tzinfo=UTC))
    _idea(db_session, "r", "DEEPAKNTR", 0.45, reasons=["Below the buy level."])
    _idea(db_session, "r", "OTHER", 0.81)
    db_session.commit()

    trail = client.get("/api/v1/brain/score-trail/DEEPAKNTR", headers=HEADERS).json()["score_trail"]
    assert trail == [{"date": "2026-11-14", "score": 0.45, "model_version": "swing_classifier v2"}]


def test_unknown_stock_is_an_empty_line(client):
    body = client.get("/api/v1/brain/score-trail/NOPE", headers=HEADERS).json()
    assert body == {"symbol": "NOPE", "score_trail": []}
