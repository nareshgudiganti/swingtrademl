"""Step 1 of the one-app technical design: brain runs are queued, never run
inside a web request, and only one runs at a time per (kind, book).

Production showed why: a 304-stock run takes ~165 s while the web gateway
gives up after 60 s, so "Run the brain now" answered 504 although the run
carried on. Now the request only queues; the worker's queue job runs it."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest

from swing_trade_ml.brain import queue, service
from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
from swing_trade_ml.db.models.market import Candle, Instrument

HEADERS = {"X-API-Key": "test-api-key"}
AS_OF = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


@pytest.fixture()
def stock(db_session):
    inst = Instrument(
        instrument_token=994001, tradingsymbol="QUEUEABC", exchange="NSE", is_watchlisted=True, is_active=True
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


def _post(client, **body):
    payload = {"kind": "nightly", "symbols": ["QUEUEABC"], "as_of": AS_OF.isoformat(), **body}
    return client.post("/api/v1/brain/runs", json=payload, headers=HEADERS)


# --- the request only queues ------------------------------------------------


def test_starting_a_run_answers_at_once_and_does_not_run_the_brain(client, stock, monkeypatch):
    def must_not_run(*a, **k):
        raise AssertionError("the web request must never run the brain")

    monkeypatch.setattr(service, "execute", must_not_run)
    started = time.perf_counter()
    r = _post(client)
    assert time.perf_counter() - started < 2
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued" and body["run_id"] and body["already_running"] is False


def test_a_second_request_while_one_is_waiting_returns_the_same_run(client, stock):
    first = _post(client).json()
    second = _post(client).json()
    assert second["run_id"] == first["run_id"]
    assert second["already_running"] is True


def test_a_queued_run_can_be_read_with_its_status(client, stock):
    run_id = _post(client).json()["run_id"]
    body = client.get(f"/api/v1/brain/runs/{run_id}", headers=HEADERS).json()
    assert body["status"] == "queued" and body["decisions"] == []


def test_a_queued_or_running_run_never_counts_as_the_latest(client, db_session, stock):
    _post(client)
    assert service.latest_run(db_session, "nightly", include_replays=True) is None


# --- the worker runs the queue ----------------------------------------------


def test_the_worker_runs_the_queued_run_under_the_same_id(client, db_session, stock):
    run_id = _post(client).json()["run_id"]
    assert queue.process_next(db_session) == run_id
    run = db_session.get(BrainRun, run_id)
    assert run.status == "done" and run.finished_at is not None
    assert run.progress and run.progress["done"] == run.progress["total"]
    assert db_session.query(BrainRun).filter(BrainRun.id == run_id).count() == 1
    assert db_session.query(BrainDecision).filter(BrainDecision.run_id == run_id).count() == 1
    body = client.get(f"/api/v1/brain/runs/{run_id}", headers=HEADERS).json()
    assert body["status"] == "done" and len(body["decisions"]) == 1


def test_nothing_queued_means_nothing_runs(db_session):
    assert queue.process_next(db_session) is None


def test_a_failed_run_is_recorded_on_the_same_row(client, db_session, stock, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("database fell over")

    monkeypatch.setattr(service, "execute", boom)
    run_id = _post(client).json()["run_id"]
    assert queue.process_next(db_session) == run_id
    run = db_session.get(BrainRun, run_id)
    assert run.status == "failed" and "database fell over" in (run.error or "")
    assert run.finished_at is not None
    assert db_session.query(BrainRun).filter(BrainRun.id == run_id).count() == 1


# --- one at a time -----------------------------------------------------------


def test_the_worker_waits_while_another_run_of_the_same_kind_holds_the_lock(client, db_session, stock):
    run_id = _post(client).json()["run_id"]
    with queue.run_lock("nightly", "paper"):
        assert queue.process_next(db_session) is None
    assert db_session.get(BrainRun, run_id).status == "queued"
    assert queue.process_next(db_session) == run_id


def test_the_lock_refuses_a_second_holder(db_session):
    with (
        queue.run_lock("nightly", "paper"),
        pytest.raises(queue.RunBusyError),
        queue.run_lock("nightly", "paper"),
    ):
        pass
    with queue.run_lock("nightly", "paper"):  # released again
        pass


def test_the_lock_can_wait_for_the_holder(db_session):
    with (
        queue.run_lock("intraday", "paper"),
        pytest.raises(queue.RunBusyError),
        queue.run_lock("intraday", "paper", wait_seconds=0.3),
    ):
        pass


def test_different_kinds_do_not_block_each_other(db_session):
    with queue.run_lock("nightly", "paper"), queue.run_lock("intraday", "paper"):
        pass


def test_a_running_run_left_by_a_restart_is_marked_failed(db_session):
    db_session.add(
        BrainRun(
            id="nightly-orphan-1",
            kind="nightly",
            as_of=AS_OF,
            book="paper",
            live=False,
            status="running",
            started_at=datetime.now(UTC) - timedelta(minutes=5),
        )
    )
    db_session.commit()
    queue.process_next(db_session)
    run = db_session.get(BrainRun, "nightly-orphan-1")
    assert run.status == "failed"
    assert "restart" in run.error.lower()


# --- superseded runs ---------------------------------------------------------


def test_a_newer_live_nightly_run_supersedes_the_earlier_one_of_the_same_day(db_session, stock):
    _, first = service.run_brain(db_session, symbols=["QUEUEABC"], book="paper")
    _, second = service.run_brain(db_session, symbols=["QUEUEABC"], book="paper")
    assert db_session.get(BrainRun, first).status == "superseded"
    assert db_session.get(BrainRun, second).status == "done"
    assert service.latest_run(db_session, "nightly").id == second


def test_replays_never_supersede_anything(db_session, stock):
    _, live = service.run_brain(db_session, symbols=["QUEUEABC"], book="paper")
    service.run_brain(db_session, symbols=["QUEUEABC"], as_of=AS_OF, book="paper")
    assert db_session.get(BrainRun, live).status == "done"


def test_an_overrule_on_a_superseded_run_still_carries_to_the_newer_run(db_session, stock):
    _, first = service.run_brain(db_session, symbols=["QUEUEABC"], book="paper")
    d = db_session.query(BrainDecision).filter(BrainDecision.run_id == first).one()
    if d.word == "AVOID":
        pytest.skip("already the most careful word")
    service.overrule(db_session, d.id, "AVOID", "owner says no", by="owner")
    _, second = service.run_brain(db_session, symbols=["QUEUEABC"], book="paper")
    _, third = service.run_brain(db_session, symbols=["QUEUEABC"], book="paper")
    newest = db_session.query(BrainDecision).filter(BrainDecision.run_id == third).one()
    assert db_session.get(BrainRun, second).status == "superseded"
    assert newest.overruled_word == "AVOID"


# --- the worker's jobs -------------------------------------------------------


def test_the_queue_job_runs_every_few_seconds_and_one_at_a_time():
    from apscheduler.schedulers.background import BackgroundScheduler

    from swing_trade_ml.workers.scheduler import add_brain_jobs

    s = BackgroundScheduler()
    add_brain_jobs(s)
    job = s.get_job("brain_run_queue")
    assert job is not None and job.max_instances == 1
    assert job.trigger.interval.total_seconds() <= 15


def test_the_queue_job_never_raises(monkeypatch):
    from unittest.mock import MagicMock

    from swing_trade_ml.workers import jobs

    monkeypatch.setattr(queue, "process_next", MagicMock(side_effect=RuntimeError("x")))
    reported = MagicMock()
    monkeypatch.setattr(jobs, "_report_error", reported)
    jobs.job_brain_run_queue()
    reported.assert_called_once()


def test_the_scheduled_nightly_run_waits_for_a_run_in_progress_and_then_reports_it(monkeypatch):
    from unittest.mock import MagicMock

    from swing_trade_ml.workers import jobs

    ran = MagicMock()
    monkeypatch.setattr(service, "run_brain", ran)
    monkeypatch.setattr(jobs, "BRAIN_LOCK_WAIT_SECONDS", {"nightly": 0.2, "intraday": 0})
    reported = MagicMock()
    monkeypatch.setattr(jobs, "_report_error", reported)
    with queue.run_lock("nightly", "paper"):
        jobs.job_brain_nightly()
    ran.assert_not_called()
    reported.assert_called_once()


def test_the_intraday_check_skips_quietly_while_a_run_of_its_kind_is_in_progress(monkeypatch):
    from unittest.mock import MagicMock

    from swing_trade_ml.workers import jobs

    ran = MagicMock()
    monkeypatch.setattr(service, "run_brain", ran)
    reported = MagicMock()
    monkeypatch.setattr(jobs, "_report_error", reported)
    with queue.run_lock("intraday", "paper"):
        jobs._run_brain_job("intraday")
    ran.assert_not_called()
    reported.assert_not_called()


# --- superseded runs are hidden from Performance (owner decision 2026-10-04) --


def _run_with_idea(db, run_id: str, status: str, outcome: str | None = None) -> BrainDecision:
    db.add(
        BrainRun(
            id=run_id, kind="nightly", as_of=AS_OF, book="paper", live=True, status=status, started_at=AS_OF
        )
    )
    db.flush()
    d = BrainDecision(run_id=run_id, symbol="QUEUEABC", kind="idea", word="TRADE", outcome=outcome)
    db.add(d)
    db.flush()
    return d


def test_learning_does_not_score_ideas_from_superseded_runs(db_session):
    from swing_trade_ml.brain.modules.m09_learn import scoring

    kept = _run_with_idea(db_session, "nightly-keep-1", "done")
    hidden = _run_with_idea(db_session, "nightly-hide-1", "superseded")
    ids = {d.id for d, _ in scoring.pending_ideas(db_session)}
    assert kept.id in ids and hidden.id not in ids


def test_the_learning_report_leaves_out_superseded_runs(db_session):
    from swing_trade_ml.brain.modules.m09_learn import learn

    _run_with_idea(db_session, "nightly-keep-2", "done", outcome="target")
    _run_with_idea(db_session, "nightly-hide-2", "superseded", outcome="target")
    frame = learn._scored_rows(db_session, None)
    runs = set(frame["run_id"]) if "run_id" in frame else None
    assert runs is not None, "the report rows must say which run they came from"
    assert "nightly-keep-2" in runs and "nightly-hide-2" not in runs
