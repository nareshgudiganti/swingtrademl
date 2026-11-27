"""#316 slices 2-3: bounded retries and restart recovery for the daily scan.

One scan per session, whoever starts it (the 15:45 job, a retry, the start-up recovery): a session that
is done is never scanned again, two runs never scan at once, a scan cut off part-way is not re-run
automatically (it could duplicate signals), and a session whose prices never arrive ends with exactly
one alert at the deadline.
"""

from __future__ import annotations

import importlib
from contextlib import contextmanager
from datetime import date, datetime, time

import pytest
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import text

from swing_trade_ml.core.market_session import IST
from swing_trade_ml.services import scan_readiness
from swing_trade_ml.workers import job_runs, jobs, scan_claim

scheduler_module = importlib.import_module("swing_trade_ml.workers.scheduler")

FRIDAY = date(2026, 11, 13)


def at(hh: int, mm: int, day: date = FRIDAY) -> datetime:
    return datetime.combine(day, time(hh, mm), tzinfo=IST)


class _Result:
    strategies_run, instruments_evaluated, signals_generated = 1, 2, 1
    buys = exits = executed = 0
    errors = ()


class World:
    """The scan job's surroundings: stored scan record, prices in or not, scans run, alerts sent."""

    def __init__(self, monkeypatch, db_session):
        self.record: dict | None = None
        self.prices_in = False
        self.scans = 0
        self.alerts: list[str] = []

        @contextmanager
        def scope():
            yield db_session

        monkeypatch.setattr(jobs, "session_scope", scope)
        monkeypatch.setattr(jobs.heartbeat, "read_last_scan", lambda: self.record)
        monkeypatch.setattr(jobs.heartbeat, "write_last_scan", self._write)
        monkeypatch.setattr(jobs.scan_readiness, "check", self._check)
        monkeypatch.setattr(jobs.engine, "run_all_active", self._scan)
        monkeypatch.setattr(jobs.held_read, "score_tester_positions", lambda db: None)
        monkeypatch.setattr(jobs.held_read, "score_tracked_stocks", lambda db: None)
        monkeypatch.setattr(jobs.notifier, "send_sync", lambda msg, *a, **k: self.alerts.append(msg) or True)

    def _write(self, data):
        self.record = dict(data)

    def _check(self, db, now=None):
        day = scan_readiness.target_session(now)
        if self.prices_in:
            return scan_readiness.Readiness(day, "complete", 2, 2, [])
        return scan_readiness.Readiness(day, "waiting", 2, 0, ["A", "B"], "prices not in yet")

    def _scan(self, db, interval="day"):
        self.scans += 1
        assert self.record["status"] == "running"  # marked before any signal can be written
        return _Result()


@pytest.fixture()
def world(monkeypatch, db_session):
    return World(monkeypatch, db_session)


def test_late_prices_are_picked_up_by_a_retry_and_scanned_once(world):
    assert jobs.run_daily_scan("scheduled", now=at(15, 45)) == "waiting"
    assert world.record["status"] == "waiting" and world.record["attempts"] == 1
    assert world.scans == 0

    assert jobs.run_daily_scan("retry", now=at(15, 50)) == "waiting"
    world.prices_in = True
    assert jobs.run_daily_scan("retry", now=at(15, 55)) == "complete"

    assert world.scans == 1
    assert world.record["status"] == "complete" and world.record["attempts"] == 3
    assert world.alerts == []  # recovered: no missing-data alert


def test_a_finished_session_is_never_scanned_again(world):
    world.prices_in = True
    assert jobs.run_daily_scan("scheduled", now=at(15, 45)) == "complete"
    for trigger, now in (("retry", at(15, 50)), ("recovery", at(16, 10)), ("scheduled", at(16, 30))):
        assert jobs.run_daily_scan(trigger, now=now) == "already_done"
    assert world.scans == 1


def test_prices_that_never_arrive_end_with_one_alert_at_the_deadline(world):
    jobs.run_daily_scan("scheduled", now=at(15, 45))
    jobs.run_daily_scan("retry", now=at(16, 55))
    assert world.alerts == []

    assert jobs.run_daily_scan("retry", now=at(17, 0)) == "gave_up"
    assert jobs.run_daily_scan("retry", now=at(17, 5)) == "gave_up"
    assert jobs.run_daily_scan("recovery", now=at(17, 30)) == "gave_up"

    assert world.scans == 0
    assert len(world.alerts) == 1 and "13 Nov" in world.alerts[0]
    assert world.record["status"] == "gave_up" and world.record["waiting_reason"] == "prices not in yet"


def test_a_worker_down_at_1545_is_recovered_inside_the_window(world):
    world.prices_in = True
    assert jobs.run_daily_scan("recovery", now=at(16, 20)) == "complete"
    assert world.scans == 1


def test_a_worker_down_for_the_whole_window_alerts_once_and_does_not_scan_late(world):
    world.prices_in = True
    assert jobs.run_daily_scan("recovery", now=at(18, 0)) == "gave_up"
    assert jobs.run_daily_scan("retry", now=at(17, 55)) == "gave_up"
    assert world.scans == 0 and len(world.alerts) == 1
    assert "did not run" in world.alerts[0]


@pytest.mark.parametrize(
    "now",
    [
        at(15, 30),  # before the session's bar is final
        at(15, 44),  # before the scan time
        at(16, 0, date(2026, 11, 14)),  # Saturday: no session today
    ],
)
def test_retries_and_recovery_do_nothing_outside_the_window(world, now):
    world.prices_in = True
    for trigger in ("retry", "recovery"):
        assert jobs.run_daily_scan(trigger, now=now) == "outside_window"
    assert world.scans == 0 and world.record is None and world.alerts == []


def test_a_scan_cut_off_part_way_is_not_rerun_and_alerts_once(world):
    world.prices_in = True
    world.record = {"status": "running", "target_session": "2026-11-13", "attempts": 1}

    assert jobs.run_daily_scan("retry", now=at(16, 0)) == "interrupted"
    assert jobs.run_daily_scan("retry", now=at(16, 5)) == "interrupted"
    assert jobs.run_daily_scan("scheduled", now=at(16, 10)) == "interrupted"

    assert world.scans == 0
    assert world.record["status"] == "interrupted"
    assert len(world.alerts) == 1 and "part-way" in world.alerts[0]


def test_yesterdays_record_does_not_count_as_today_done(world):
    world.prices_in = True
    world.record = {"status": "complete", "target_session": "2026-11-12", "attempts": 1}
    assert jobs.run_daily_scan("scheduled", now=at(15, 45)) == "complete"
    assert world.scans == 1 and world.record["attempts"] == 1


def test_a_scan_already_running_elsewhere_is_left_alone(world, db_session):
    world.prices_in = True
    other = db_session.get_bind().engine.connect()
    try:
        assert other.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": scan_claim.LOCK_KEY}).scalar()
        assert jobs.run_daily_scan("retry", now=at(15, 50)) == "busy"
        assert world.scans == 0 and world.record is None
    finally:
        other.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": scan_claim.LOCK_KEY})
        other.close()
    assert jobs.run_daily_scan("retry", now=at(15, 55)) == "complete"  # and the claim was released


def test_the_claim_is_released_when_the_scan_raises(world, db_session, monkeypatch):
    world.prices_in = True
    monkeypatch.setattr(jobs.engine, "run_all_active", lambda db, interval="day": 1 / 0)
    jobs.run_daily_scan("scheduled", now=at(15, 45))  # reported, not raised
    probe = db_session.get_bind().engine.connect()
    try:
        assert probe.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": scan_claim.LOCK_KEY}).scalar()
        probe.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": scan_claim.LOCK_KEY})
    finally:
        probe.close()
    # The record still says "running", so the next retry treats it as cut off, not as a fresh scan.
    assert jobs.run_daily_scan("retry", now=at(15, 50)) == "interrupted"


def test_the_scheduler_registers_the_retry_and_the_start_up_recovery(monkeypatch):
    fresh = BackgroundScheduler(timezone="UTC")
    real_start = fresh.start
    monkeypatch.setattr(fresh, "start", lambda *a, **k: real_start(paused=True))
    monkeypatch.setattr(scheduler_module.settings, "ENABLE_SCHEDULER", True)
    monkeypatch.setattr(scheduler_module.job_runs, "attach", lambda s: None)
    monkeypatch.setattr(scheduler_module, "scheduler", fresh)
    scheduler_module.start_scheduler()
    try:
        retry, recovery = fresh.get_job("scan_retry"), fresh.get_job("scan_recovery")
        assert retry is not None and recovery is not None
        assert "hour='15-17'" in str(retry.trigger) and "minute='0,5,10" in str(retry.trigger)
        assert retry.func is jobs.job_scan_retry and recovery.func is jobs.job_scan_recovery
    finally:
        fresh.shutdown(wait=False)
    assert "scan_retry" in job_runs.JOB_LABELS and "scan_recovery" in job_runs.JOB_LABELS


def test_the_scan_record_is_replaced_in_one_step(tmp_path, monkeypatch):
    from swing_trade_ml.workers import heartbeat

    path = tmp_path / ".last_scan.json"
    monkeypatch.setattr(heartbeat, "_LAST_SCAN_PATH", path)
    heartbeat.write_last_scan({"status": "running", "target_session": "2026-11-13"})
    heartbeat.write_last_scan({"status": "complete", "target_session": "2026-11-13"})
    assert heartbeat.read_last_scan() == {"status": "complete", "target_session": "2026-11-13"}
    assert [p.name for p in tmp_path.iterdir()] == [".last_scan.json"]  # no temp file left behind


def test_a_scan_recorded_by_the_old_code_today_counts_as_done(world):
    """First deploy after 16:30 IST: the 15:45 scan already ran under the old code, whose record has no
    session marker. The start-up recovery must not scan the same session a second time (review 27 Nov)."""
    world.record = {"ts": at(15, 46).isoformat(), "strategies_run": 3, "signals_generated": 2}
    world.prices_in = True
    assert jobs.run_daily_scan("recovery", now=at(16, 31)) == "already_done"
    assert world.scans == 0 and world.alerts == []


def test_an_old_code_record_from_before_todays_scan_time_does_not_count(world):
    world.record = {"ts": at(15, 46, date(2026, 11, 12)).isoformat(), "strategies_run": 3}
    world.prices_in = True
    assert jobs.run_daily_scan("recovery", now=at(16, 31)) == "complete"
    assert world.scans == 1
