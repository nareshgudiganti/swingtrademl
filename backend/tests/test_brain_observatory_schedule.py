"""R7: a missing run is 'Not observed' only on a trading day after its deadline."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from swing_trade_ml.services.brain_observatory import schedule as sch

IST = sch.IST
THU = date(2026, 10, 15)


def at(d, h, m):
    return datetime(d.year, d.month, d.day, h, m, tzinfo=IST)


def test_weekend_and_listed_holiday_are_not_applicable(monkeypatch):
    sat = date(2026, 10, 17)
    assert sch.nightly_expectation(sat, at(sat, 20, 0)) == "not_applicable"
    assert (
        sch.nightly_expectation(date(2026, 10, 20), at(date(2026, 10, 20), 20, 0)) == "not_applicable"
    )  # Dussehra
    monkeypatch.setattr(sch, "is_trading_day", lambda d: False)
    assert sch.nightly_expectation(THU, at(THU, 20, 0)) == "not_applicable"


def test_before_the_deadline_is_not_due():
    assert sch.nightly_expectation(THU, at(THU, 16, 0)) == "not_due"
    assert sch.nightly_expectation(THU, at(THU, 16, 20)) == "due"


def test_missing_after_deadline_is_not_observed():
    assert sch.nightly_state(THU, at(THU, 17, 0), [])["state"] == "not_observed"
    assert sch.nightly_state(THU, at(THU, 16, 5), [])["state"] == "not_due"


def test_superseded_runs_are_ignored_and_two_live_runs_conflict():
    runs = [
        {"id": "a", "kind": "nightly", "live": True, "status": "superseded"},
        {"id": "b", "kind": "nightly", "live": True, "status": "done"},
    ]
    assert sch.nightly_state(THU, at(THU, 17, 0), runs) == {
        "state": "observed",
        "run_id": "b",
        "expectation": "due",
    }
    runs.append({"id": "c", "kind": "nightly", "live": True, "status": "done"})
    assert sch.nightly_state(THU, at(THU, 17, 0), runs)["state"] == "conflicting"


def test_replay_runs_do_not_count_as_the_live_nightly():
    runs = [{"id": "r", "kind": "nightly", "live": False, "status": "done"}]
    assert sch.nightly_state(THU, at(THU, 17, 0), runs)["state"] == "not_observed"


def test_intraday_slots_due_by_time():
    assert len(sch.INTRADAY_SLOTS) == 28
    assert sch.intraday_expectation(THU, at(THU, 9, 20)) == {"slots": 28, "due": 1, "not_due": 27}
    assert sch.intraday_expectation(date(2026, 10, 17), at(THU, 9, 20)) == {"not_applicable": True}


def test_run_day_uses_ist_not_utc():
    utc_evening = datetime(2026, 10, 14, 19, 0, tzinfo=sch.UTC)  # 00:30 IST on 15 Oct
    assert sch.run_day(utc_evening) == THU


def test_schedule_constants_match_the_scheduler_source():
    src = (Path(sch.__file__).resolve().parents[2] / "workers" / "scheduler.py").read_text(encoding="utf-8")
    assert "jobs.job_brain_nightly,\n        CronTrigger(day_of_week=WEEKDAYS, hour=15, minute=50" in src
    assert 'hour="9-15", minute="0,15,30,45"' in src


# --- review finding 1: an unfinished or failed nightly is not "Ran" ---------------------------------


def _run(rid, status):
    return {"id": rid, "kind": "nightly", "live": True, "status": status}


def test_a_failed_nightly_is_failed_not_observed():
    s = sch.nightly_state(THU, at(THU, 17, 0), [_run("f", "failed")])
    assert s["state"] == "failed" and s["run_ids"] == ["f"] and "run_id" not in s


def test_a_queued_or_running_nightly_is_in_progress_not_observed():
    for status in ("queued", "running"):
        assert sch.nightly_state(THU, at(THU, 17, 0), [_run("q", status)])["state"] == "in_progress"


def test_one_done_run_wins_over_a_failed_or_queued_rerun():
    runs = [_run("f", "failed"), _run("d", "done"), _run("q", "queued")]
    s = sch.nightly_state(THU, at(THU, 17, 0), runs)
    assert s["state"] == "observed" and s["run_id"] == "d"


def test_two_done_runs_are_still_a_conflict():
    s = sch.nightly_state(THU, at(THU, 17, 0), [_run("a", "done"), _run("b", "done")])
    assert s["state"] == "conflicting"
