"""GET /brain/trial-journal: the forward trial's journal read from the database, so it can be checked
remotely with the API key. Read-only."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
from swing_trade_ml.db.models.market import Candle, Instrument

API_KEY = {"X-API-Key": "test-api-key"}
IST = ZoneInfo("Asia/Kolkata")
DECIDED = date(2026, 1, 5)  # a Monday


def _trading_days(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _seed(db) -> None:
    inst = Instrument(instrument_token=424242, tradingsymbol="TJUP", exchange="NSE", is_watchlisted=True)
    db.add(inst)
    db.flush()
    price = 100.0
    for d in _trading_days(DECIDED, 25):
        nxt = price * 1.02
        db.add(
            Candle(
                instrument_id=inst.id, interval="day", ts=datetime.combine(d, time(0, 0), tzinfo=IST),
                open=price, high=nxt * 1.001, low=price * 0.999, close=nxt, volume=1000,
            )
        )
        price = nxt
    db.add(
        BrainRun(
            id="tj-run-1", kind="nightly", live=True, status="done", book="paper",
            as_of=datetime(2026, 1, 5, 10, 20, tzinfo=UTC), banner_mode="NORMAL",
        )
    )
    db.flush()
    db.add(
        BrainDecision(
            run_id="tj-run-1", symbol="TJUP", kind="idea", word="TRADE", confidence=0.7, score_source="model",
            stop=96.0, target=108.0,
        )
    )
    db.flush()


def test_the_journal_reads_a_recorded_session_and_scores_its_trade(client, db_session):
    _seed(db_session)
    r = client.get("/api/v1/brain/trial-journal?from=2026-01-05&to=2026-01-05", headers=API_KEY)
    assert r.status_code == 200
    body = r.json()
    j = body["journal"]
    assert j["sessions"] == 1 and j["source"] == "live"
    trade = j["summaries"]["brain_trade"]
    assert trade["picked"] == 1 and trade["ideas"] == 1 and trade["hit_rate"] == 1.0
    assert j["gate"]["word"] == "too early"
    assert "Gate answer: too early" in body["report"]


def test_no_sessions_is_a_plain_answer(client):
    r = client.get("/api/v1/brain/trial-journal?from=2026-10-14", headers=API_KEY)
    assert r.status_code == 200
    assert r.json()["journal"]["sessions"] == 0


def test_dates_are_checked(client):
    url = "/api/v1/brain/trial-journal"
    assert client.get(f"{url}?from=2026-10-20&to=2026-10-14", headers=API_KEY).status_code == 422  # backwards
    assert client.get(f"{url}?from=2024-01-01&to=2026-10-14", headers=API_KEY).status_code == 422  # too long
    assert client.get(url, headers=API_KEY).status_code == 422  # no start


def test_it_writes_nothing(client, db_session):
    _seed(db_session)
    before = (db_session.query(BrainRun).count(), db_session.query(BrainDecision).count())
    client.get("/api/v1/brain/trial-journal?from=2026-01-05&to=2026-01-05", headers=API_KEY)
    after = (db_session.query(BrainRun).count(), db_session.query(BrainDecision).count())
    assert before == after
    assert db_session.query(BrainDecision).one().outcome is None  # the journal never grades stored ideas


def test_a_risk_blocked_idea_is_read_as_blocked(client, db_session):
    _seed(db_session)
    db_session.add(
        BrainDecision(
            run_id="tj-run-1", symbol="TJUP", kind="idea", word="WATCH", downgraded_from="TRADE",
            downgrade_reason="Good idea, but the risk check said no: market stress", confidence=0.6,
            score_source="model", stop=96.0, target=108.0,
        )
    )
    db_session.flush()
    r = client.get("/api/v1/brain/trial-journal?from=2026-01-05&to=2026-01-05", headers=API_KEY)
    assert r.json()["journal"]["summaries"]["brain_blocked"]["picked"] == 1
