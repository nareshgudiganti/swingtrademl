"""A brain that silently runs on fallbacks is not stable, even when every run "finishes".

Found on prod 2026-10-13: every live nightly since 10-05 dropped M02 (features), M05 (memory) and M15
(tracker) for running over their time budgets, and the weekly health report still said everything was ok.
Now: the budgets fit what the modules need, a module dropped in the last nightly run turns the weekly report
and /brain/health red, and a backup older than a week is a warning.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from swing_trade_ml.brain import service
from swing_trade_ml.brain.modules.m02_perception.module import Perception
from swing_trade_ml.brain.modules.m05_memory.module import Memory
from swing_trade_ml.brain.modules.m15_tracker.module import Tracker
from swing_trade_ml.db.models.brain import BrainRun
from swing_trade_ml.services import brain_weekly_health as w

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


def _run(db, run_id: str, trace: list[dict], modules: dict[str, str], started=NOW) -> None:
    db.add(
        BrainRun(
            id=run_id,
            kind="nightly",
            status="done",
            live=True,
            book="paper",
            as_of=started,
            started_at=started,
            modules=modules,
            trace=trace,
        )
    )
    db.flush()


def _event(module_id: str, status: str, reason: str = "") -> dict:
    base = {"step": "perceive", "ms": 1, "version": "1"}
    return {**base, "module_id": module_id, "status": status, "reason": reason}


# --- budgets that fit what the modules need on prod -------------------------------------------------


def test_m02_and_m15_have_room_for_their_measured_nightly_time():
    # Measured on prod 10-05..10-13: M02 44-50 s, M15 16-23 s.
    assert Perception.manifest.budget("nightly") >= 90
    assert Tracker.manifest.budget("nightly") >= 45


def test_m05_has_room_for_its_measured_nightly_time():
    # Measured on prod 2026-10-14 (first night after its speed-up): 49.8 s against a 20 s budget, so its
    # shadow recall was dropped from the trial record.
    assert Memory.manifest.budget("nightly") >= 90


# --- the weekly check sees dropped modules ----------------------------------------------------------


def test_a_dropped_switched_on_module_fails_the_check(db_session):
    _run(
        db_session,
        "stab-1",
        [_event("M02", "fallback", "too slow: 47.30 s against a 30.00 s budget"), _event("M07", "used")],
        {"M02": "on", "M07": "on"},
    )
    c = w.check_modules_ran(db_session)
    assert not c["ok"] and c["level"] == "fail"
    assert "M02" in c["detail"] and "too slow" in c["detail"]


def test_a_dropped_trial_module_is_a_warning(db_session):
    _run(db_session, "stab-2", [_event("M05", "fallback", "too slow: 212 s")], {"M05": "shadow"})
    c = w.check_modules_ran(db_session)
    assert not c["ok"] and c["level"] == "warn" and "M05" in c["detail"]


def test_every_module_running_is_ok_and_step_fallbacks_are_not_counted(db_session):
    _run(
        db_session,
        "stab-3",
        [
            _event("M02", "used"),
            _event("M06", "shadow"),
            _event("fallback", "fallback", "no module answered"),
        ],
        {"M02": "on", "M06": "shadow"},
    )
    assert w.check_modules_ran(db_session)["ok"]


def test_only_the_latest_live_nightly_run_is_judged(db_session):
    yesterday = NOW - timedelta(days=1)
    _run(db_session, "stab-old", [_event("M02", "fallback", "too slow")], {"M02": "on"}, yesterday)
    _run(db_session, "stab-new", [_event("M02", "used")], {"M02": "on"}, NOW)
    assert w.check_modules_ran(db_session)["ok"]


def test_compute_checks_includes_the_module_check(db_session, tmp_path):
    names = [c["name"] for c in w.compute_checks(db_session, NOW, backup_dir=str(tmp_path))["checks"]]
    assert "Modules ran" in names


# --- /brain/health shows the same thing every day ---------------------------------------------------


def test_health_lists_modules_dropped_in_the_last_nightly_run(db_session):
    reason = "too slow: 22.89 s against a 15.00 s budget"
    _run(db_session, "stab-h", [_event("M15", "fallback", reason)], {"M15": "on"})
    dropped = service.health(db_session)["modules_dropped"]
    assert dropped == [{"module": "M15", "mode": "on", "reason": reason}]


# --- backups ------------------------------------------------------------------------------------------


def test_a_backup_older_than_a_week_is_a_warning(tmp_path):
    f = tmp_path / "m.joblib"
    f.write_bytes(b"x")
    made = datetime.fromtimestamp(os.stat(f).st_ctime, UTC)
    assert w.check_backup(str(tmp_path), now=made + timedelta(days=3))["ok"]
    old = w.check_backup(str(tmp_path), now=made + timedelta(days=8))
    assert not old["ok"] and old["level"] == "warn" and "8 days" in old["detail"]


def _record(folder, at: datetime, *, present: int = 20, missing: list[str] | None = None) -> None:
    from swing_trade_ml.ml.backup import write_run_record

    write_run_record(folder, {"copied": 0, "already_present": present, "missing": missing or []}, at=at)


def test_a_daily_run_with_nothing_new_to_copy_is_ok_even_when_every_file_is_old(tmp_path):
    # Found on prod 2026-10-14: models are frozen, the last one was trained 28 Aug, so the newest copy was
    # weeks old and the check cried "the daily backup may have stopped" although the job ran every day.
    f = tmp_path / "m.joblib"
    f.write_bytes(b"x")
    made = datetime.fromtimestamp(os.stat(f).st_ctime, UTC)
    _record(tmp_path, made + timedelta(days=29))
    c = w.check_backup(str(tmp_path), now=made + timedelta(days=30))
    assert c["ok"] and "20 model files" in c["detail"]


def test_a_backup_job_that_stopped_running_is_a_warning(tmp_path):
    _record(tmp_path, NOW)
    c = w.check_backup(str(tmp_path), now=NOW + timedelta(days=w.BACKUP_RUN_MAX_AGE_DAYS + 1))
    assert not c["ok"] and c["level"] == "warn" and "last ran" in c["detail"]


def test_a_backup_run_that_found_missing_model_files_is_a_warning(tmp_path):
    _record(tmp_path, NOW, present=19, missing=["swing_classifier:v2"])
    c = w.check_backup(str(tmp_path), now=NOW + timedelta(hours=2))
    assert not c["ok"] and c["level"] == "warn" and "swing_classifier:v2" in c["detail"]


def test_intraday_budgets_fit_what_prod_needs():
    from swing_trade_ml.brain.modules.m08_decide.module import DecisionEngine

    # Measured on prod intraday runs 2026-10-13: M08 1.4-1.7 s, M15 26-28 s.
    assert DecisionEngine.manifest.budget("intraday") >= 5
    assert Tracker.manifest.budget("intraday") >= 45
