"""ux11 "What changed since yesterday": read only, live nightly runs only, ranks not raw scores,
and never any result (outcome) of a brain idea."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event

from swing_trade_ml.core.plans import brain_route_access
from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
from swing_trade_ml.db.models.session import User
from swing_trade_ml.services import brain_changes
from swing_trade_ml.services.plans import set_plans_enabled

HEADERS = {"X-API-Key": "test-api-key"}
BOOK = "ux11t"  # its own book, so other tests' runs in the shared test database never match
# 15:50 IST on two trading days (Tue, Wed), far from any real run.
TUE = datetime(2031, 3, 11, 10, 20, tzinfo=UTC)
WED = datetime(2031, 3, 12, 10, 20, tzinfo=UTC)


def _run(db, rid, as_of, *, kind="nightly", live=True, status="done", book=BOOK, started=None):
    run = BrainRun(
        id=f"ux11-{rid}",
        kind=kind,
        as_of=as_of,
        book=book,
        live=live,
        status=status,
        started_at=started or as_of,
        banner_mode="NORMAL",
    )
    db.add(run)
    db.flush()
    return run


def _idea(db, run, symbol, word, confidence=None, *, kind="idea", source="model", **kw):
    db.add(
        BrainDecision(
            run_id=run.id,
            symbol=symbol,
            kind=kind,
            word=word,
            reasons=kw.pop("reasons", [f"{symbol} reason"]),
            confidence=confidence,
            score_source=source if confidence is not None else None,
            **kw,
        )
    )
    db.flush()


@pytest.fixture()
def two_days(db_session):
    tue = _run(db_session, "tue", TUE)
    _idea(db_session, tue, "AAA", "WAIT", 0.40, reasons=["Model score 40% is below the buy level 55%."])
    _idea(db_session, tue, "BBB", "TRADE", 0.70)
    _idea(db_session, tue, "CCC", "WATCH", 0.60)
    _idea(db_session, tue, "DDD", "WAIT", 0.50)
    wed = _run(db_session, "wed", WED)
    _idea(db_session, wed, "AAA", "TRADE", 0.72)
    _idea(db_session, wed, "BBB", "WATCH", 0.65, downgraded_from="TRADE", downgrade_reason="risk said no")
    _idea(db_session, wed, "CCC", "WATCH", 0.30)
    _idea(db_session, wed, "EEE", "WAIT", 0.10)
    _idea(db_session, wed, "DDD", "HOLD", kind="holding")
    return tue, wed


def test_compares_with_the_previous_days_live_nightly_run(db_session, two_days):
    tue, wed = two_days
    out = brain_changes.changes(db_session, run_id=wed.id)
    assert out["comparable"] is True
    assert out["current"]["run_id"] == wed.id and out["current"]["day"] == "2031-03-12"
    assert out["previous"]["run_id"] == tue.id and out["previous"]["day"] == "2031-03-11"
    rows = {r["symbol"]: r for r in out["ideas"]}
    assert set(rows) == {"AAA", "BBB", "CCC", "DDD", "EEE"}
    assert (rows["AAA"]["before"]["word"], rows["AAA"]["now"]["word"]) == ("WAIT", "TRADE")
    assert rows["AAA"]["before"]["reasons"] == ["Model score 40% is below the buy level 55%."]
    assert rows["BBB"]["now"]["downgraded_from"] == "TRADE"
    assert rows["EEE"]["before"] is None  # newly appeared
    assert rows["DDD"]["now"] is None and rows["DDD"]["held_now"] is True  # bought, not dropped


def test_scores_come_back_as_places_in_the_ranking_never_raw(db_session, two_days):
    _tue, wed = two_days
    rows = {r["symbol"]: r for r in brain_changes.changes(db_session, run_id=wed.id)["ideas"]}
    assert (rows["CCC"]["before"]["rank"], rows["CCC"]["before"]["rank_of"]) == (2, 4)
    assert (rows["CCC"]["now"]["rank"], rows["CCC"]["now"]["rank_of"]) == (3, 4)
    assert rows["AAA"]["now"]["rank"] == 1
    for row in rows.values():
        for side in (row["now"], row["before"]):
            assert side is None or "confidence" not in side


def test_never_includes_results_of_ideas(db_session, two_days):
    tue, wed = two_days
    db_session.query(BrainDecision).filter(BrainDecision.run_id == tue.id).update(
        {"outcome": "target", "outcome_return": 0.08, "outcome_days": 4, "max_up": 0.09, "max_down": -0.01}
    )
    text = str(brain_changes.changes(db_session, run_id=wed.id))
    for word in ("outcome", "max_up", "max_down", "resolved_on", "0.08"):
        assert word not in text


def test_replays_why_intraday_failed_and_other_books_are_never_the_previous_day(db_session):
    tue = _run(db_session, "tue", TUE)
    _idea(db_session, tue, "AAA", "WAIT", 0.4)
    later_tue = TUE + timedelta(hours=2)
    _run(db_session, "replay", later_tue, live=False)
    _run(db_session, "why", later_tue, kind="why")
    _run(db_session, "intraday", later_tue, kind="intraday")
    _run(db_session, "failed", later_tue, status="failed")
    _run(db_session, "superseded", later_tue, status="superseded")
    _run(db_session, "otherbook", later_tue, book="ux11o")
    wed = _run(db_session, "wed", WED)
    _idea(db_session, wed, "AAA", "WAIT", 0.4)
    assert brain_changes.changes(db_session, run_id=wed.id)["previous"]["run_id"] == tue.id


def test_a_second_run_on_the_same_day_is_not_yesterday(db_session):
    early = _run(db_session, "wed-early", WED - timedelta(hours=1))
    wed = _run(db_session, "wed", WED)
    out = brain_changes.changes(db_session, run_id=wed.id)
    assert early.id != wed.id
    assert out["comparable"] is False and out["note"] == brain_changes.NO_PREVIOUS


def test_a_non_nightly_run_is_not_compared(db_session, two_days):
    why = _run(db_session, "whyrun", WED + timedelta(hours=1), kind="why")
    out = brain_changes.changes(db_session, run_id=why.id)
    assert out["comparable"] is False and out["note"] == brain_changes.NOT_NIGHTLY and out["ideas"] == []


def test_without_a_run_id_uses_the_newest_live_nightly_run_of_the_book(db_session, two_days):
    _tue, wed = two_days
    assert brain_changes.changes(db_session, book=BOOK)["current"]["run_id"] == wed.id
    assert brain_changes.changes(db_session, book="ux11none")["note"] == brain_changes.NO_RUN


def test_an_owner_overrule_is_the_word_shown(db_session, two_days):
    _tue, wed = two_days
    db_session.query(BrainDecision).filter(
        BrainDecision.run_id == wed.id, BrainDecision.symbol == "AAA"
    ).update({"overruled_word": "WAIT", "overrule_reason": "not sure"})
    rows = {r["symbol"]: r for r in brain_changes.changes(db_session, run_id=wed.id)["ideas"]}
    assert rows["AAA"]["now"]["word"] == "WAIT" and rows["AAA"]["now"]["brain_word"] == "TRADE"


def test_reading_changes_writes_nothing(db_session, two_days):
    _tue, wed = two_days
    writes: list[str] = []

    def spy(conn, cursor, statement, *args):
        if statement.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    engine = db_session.get_bind().engine
    event.listen(engine, "before_cursor_execute", spy)
    try:
        brain_changes.changes(db_session, run_id=wed.id)
    finally:
        event.remove(engine, "before_cursor_execute", spy)
    assert writes == []


def test_api_answers_with_the_comparison(client, two_days):
    _tue, wed = two_days
    resp = client.get(f"/api/v1/brain/changes?run_id={wed.id}", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json()["comparable"] is True
    assert client.get("/api/v1/brain/changes").status_code == 401
    assert client.post("/api/v1/brain/changes", headers=HEADERS).status_code == 405


def test_api_is_a_trademind_read_for_pro_plans(client, db_session, two_days):
    assert brain_route_access("GET", "/brain/changes") == "trademind"
    set_plans_enabled(db_session, True)
    _tue, wed = two_days

    def user(name, plan):
        u = User(username=name, hashed_password="x", is_active=True, is_superuser=False, plan=plan)
        db_session.add(u)
        db_session.flush()
        return {"Authorization": f"Bearer {create_access_token(u.username, {'uid': u.id})}"}

    assert (
        client.get(f"/api/v1/brain/changes?run_id={wed.id}", headers=user("ux11pro", "pro")).status_code
        == 200
    )
    assert (
        client.get(f"/api/v1/brain/changes?run_id={wed.id}", headers=user("ux11free", "free")).status_code
        == 403
    )


def test_api_is_hidden_while_the_brain_is_off(client, monkeypatch):
    from swing_trade_ml.core.config import settings

    monkeypatch.setattr(settings, "BRAIN_ENABLED", False)
    assert client.get("/api/v1/brain/changes", headers=HEADERS).status_code == 404
