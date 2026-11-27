"""#316: the jobs that use the daily scan's day (brain nightly, brain daily check, daily summary) wait for it.

On a normal day nothing changes: the scan is done by 15:50 and each job runs at its own time. When prices
are late, a job that comes due before the scan finishes is put on hold and run, in order, the moment the
scan finishes. When the scan gives up, the summary and the health check still run (they report the
problem); the brain only runs if the day's prices were in. Each job runs at most once per session.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from datetime import date, datetime, time

import pytest
from sqlalchemy import text

from swing_trade_ml.core.market_session import IST
from swing_trade_ml.services import scan_readiness
from swing_trade_ml.workers import jobs, scan_claim

FRIDAY = date(2026, 11, 13)


def at(hh: int, mm: int, day: date = FRIDAY) -> datetime:
    return datetime.combine(day, time(hh, mm), tzinfo=IST)


class _Result:
    strategies_run, instruments_evaluated, signals_generated = 1, 2, 1
    buys = exits = executed = 0
    errors = ()


class World:
    def __init__(self, monkeypatch, db_session):
        self.record: dict | None = None
        self.prices_in = False
        self.ran: list[str] = []
        self.alerts: list[str] = []
        self.clock = at(15, 45)

        @contextmanager
        def scope():
            yield db_session

        monkeypatch.setattr(jobs, "session_scope", scope)
        monkeypatch.setattr(jobs.heartbeat, "read_last_scan", lambda: self.record)
        monkeypatch.setattr(jobs.heartbeat, "write_last_scan", self._write)
        monkeypatch.setattr(jobs.scan_readiness, "check", self._check)
        monkeypatch.setattr(jobs.engine, "run_all_active", lambda db, interval="day": _Result())
        monkeypatch.setattr(jobs.held_read, "score_tester_positions", lambda db: None)
        monkeypatch.setattr(jobs.held_read, "score_tracked_stocks", lambda db: None)
        monkeypatch.setattr(jobs.notifier, "send_sync", lambda msg, *a, **k: self.alerts.append(msg) or True)
        monkeypatch.setattr(jobs, "_now_ist", lambda: self.clock)
        for name in jobs.FOLLOWUPS:
            monkeypatch.setitem(jobs.FOLLOWUP_BODIES, name, lambda name=name: self.ran.append(name))

    def _write(self, data):
        self.record = dict(data)

    def _check(self, db, now=None):
        day = scan_readiness.target_session(now)
        if self.prices_in:
            return scan_readiness.Readiness(day, "complete", 2, 2, [])
        return scan_readiness.Readiness(day, "waiting", 2, 0, ["A", "B"], "prices not in yet")

    def scan(self, trigger: str, hh: int, mm: int) -> str:
        self.clock = at(hh, mm)
        return jobs.run_daily_scan(trigger, now=self.clock)

    def due(self, name: str, hh: int, mm: int, day: date = FRIDAY) -> str:
        self.clock = at(hh, mm, day)
        return jobs.run_followup(name)


@pytest.fixture()
def world(monkeypatch, db_session):
    return World(monkeypatch, db_session)


def test_a_normal_day_runs_each_job_at_its_own_time_once(world):
    world.prices_in = True
    assert world.scan("scheduled", 15, 45) == "complete"
    assert world.due("brain_nightly", 15, 50) == "ran"
    assert world.due("daily_summary", 16, 0) == "ran"
    assert world.due("brain_daily_check", 16, 20) == "ran"
    assert world.due("brain_nightly", 16, 30) == "already"
    assert world.ran == ["brain_nightly", "daily_summary", "brain_daily_check"]


def test_late_prices_hold_the_jobs_and_run_them_in_order_when_the_scan_finishes(world):
    assert world.scan("scheduled", 15, 45) == "waiting"
    assert world.due("brain_nightly", 15, 50) == "deferred"
    assert world.scan("retry", 15, 55) == "waiting"  # a waiting retry keeps the held jobs
    assert world.due("daily_summary", 16, 0) == "deferred"
    assert world.ran == []

    world.prices_in = True
    assert world.scan("retry", 16, 5) == "complete"
    assert world.ran == ["brain_nightly", "daily_summary"]  # brain first, then the summary

    assert world.due("brain_daily_check", 16, 20) == "ran"  # not yet due when the scan finished
    assert world.due("brain_nightly", 16, 25) == "already"
    assert world.ran == ["brain_nightly", "daily_summary", "brain_daily_check"]
    assert world.record["followups"] == dict.fromkeys(jobs.FOLLOWUPS, "done")


def test_when_prices_never_arrive_the_brain_is_skipped_and_the_reports_still_go_out(world):
    world.scan("scheduled", 15, 45)
    world.due("brain_nightly", 15, 50)
    world.due("daily_summary", 16, 0)
    world.due("brain_daily_check", 16, 20)
    assert world.ran == []

    assert world.scan("retry", 17, 0) == "gave_up"

    assert world.ran == ["brain_daily_check", "daily_summary"]
    assert world.record["followups"]["brain_nightly"] == "skipped"
    assert len(world.alerts) == 1  # the scan's own give-up alert, nothing more from here
    assert world.due("brain_nightly", 17, 10) == "already"


def test_after_a_scan_cut_off_part_way_the_held_jobs_still_run(world):
    # Prices were in, so the brain (which reads prices itself) can run even though v1's scan stopped.
    world.prices_in = True
    world.record = {
        "status": "running",
        "target_session": "2026-11-13",
        "attempts": 1,
        "prices_ready": True,
    }
    assert world.due("brain_nightly", 15, 50) == "deferred"
    assert world.scan("retry", 15, 55) == "interrupted"
    assert world.ran == ["brain_nightly"]


def _finished_with_held_jobs(world, **followups) -> None:
    # The scan finished, but the worker stopped before it ran the jobs held for it.
    world.prices_in = True
    world.record = {
        "status": "complete",
        "target_session": "2026-11-13",
        "attempts": 1,
        "prices_ready": True,
        "followups": followups,
    }


def test_after_a_restart_the_held_jobs_resume_even_though_the_scan_already_finished(world):
    _finished_with_held_jobs(world, daily_summary="deferred", brain_nightly="deferred")

    assert world.scan("recovery", 16, 10) == "already_done"
    assert world.ran == ["brain_nightly", "daily_summary"]  # once each, in order
    assert world.record["followups"] == {"brain_nightly": "done", "daily_summary": "done"}

    assert world.scan("recovery", 16, 15) == "already_done"
    assert world.ran == ["brain_nightly", "daily_summary"]  # nothing runs twice


def test_after_the_deadline_the_retry_still_resumes_held_jobs(world):
    _finished_with_held_jobs(world, daily_summary="deferred")
    assert world.scan("retry", 17, 30) == "already_done"
    assert world.ran == ["daily_summary"]


def test_a_job_cut_off_part_way_is_not_run_again(world):
    # "running" means it may already have written brain ideas or sent the digest: never repeat it.
    _finished_with_held_jobs(world, brain_nightly="running", daily_summary="deferred")
    assert world.scan("recovery", 16, 10) == "already_done"
    assert world.ran == ["daily_summary"]
    assert world.record["followups"]["brain_nightly"] == "running"


def test_jobs_that_come_due_before_any_scan_record_wait_for_the_scan(world):
    world.prices_in = True
    assert world.due("brain_nightly", 15, 50) == "deferred"  # worker restarted; no scan yet today
    assert world.record["status"] == "not_started"
    assert world.scan("recovery", 15, 52) == "complete"
    assert world.ran == ["brain_nightly"]
    assert world.record["attempts"] == 1


def test_on_a_day_with_no_session_the_jobs_run_as_before(world):
    saturday = date(2026, 11, 14)
    assert world.due("daily_summary", 16, 0, saturday) == "ran"
    assert world.ran == ["daily_summary"] and world.record is None


def test_a_job_waits_for_a_scan_in_progress_then_runs(world, db_session, monkeypatch):
    monkeypatch.setattr(jobs, "FOLLOWUP_POLL_SECONDS", 0.05)
    world.prices_in = True
    world.record = {"status": "running", "target_session": "2026-11-13", "attempts": 1}
    holder = db_session.get_bind().engine.connect()
    assert holder.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": scan_claim.LOCK_KEY}).scalar()
    out: list[str] = []
    t = threading.Thread(target=lambda: out.append(world.due("brain_nightly", 15, 50)))
    t.start()
    try:
        t.join(0.3)
        assert t.is_alive() and world.ran == []  # held back while the scan runs
        world.record = {**world.record, "status": "complete"}
    finally:
        holder.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": scan_claim.LOCK_KEY})
        holder.close()
    t.join(5)
    assert out == ["ran"] and world.ran == ["brain_nightly"]


def test_a_job_that_cannot_get_the_claim_in_time_does_not_run(world, db_session, monkeypatch):
    monkeypatch.setattr(jobs, "FOLLOWUP_POLL_SECONDS", 0.05)
    monkeypatch.setattr(jobs, "FOLLOWUP_WAIT_SECONDS", 0.2)
    world.prices_in = True
    holder = db_session.get_bind().engine.connect()
    assert holder.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": scan_claim.LOCK_KEY}).scalar()
    try:
        assert world.due("daily_summary", 16, 0) == "timeout"
    finally:
        holder.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": scan_claim.LOCK_KEY})
        holder.close()
    assert world.ran == []


def test_the_scheduled_jobs_go_through_the_gate(monkeypatch):
    seen = []
    monkeypatch.setattr(jobs, "run_followup", lambda name: seen.append(name) or "ran")
    jobs.job_brain_nightly()
    jobs.job_daily_summary()
    jobs.job_brain_daily_check()
    assert seen == ["brain_nightly", "daily_summary", "brain_daily_check"]
