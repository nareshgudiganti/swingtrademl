"""The daily brain check: after every trading day's nightly run, store one record of the brain's health,
its wiring (dropped modules, intraday too) and the trial so far, so any day can be looked up later."""

from __future__ import annotations

from datetime import UTC, date, datetime

from swing_trade_ml.db.models.brain import BrainDailyCheck, BrainRun
from swing_trade_ml.services import brain_daily_check as daily
from swing_trade_ml.workers import jobs

API_KEY = {"X-API-Key": "test-api-key"}
DAY = date(2026, 10, 14)  # a Wednesday, a trading day
NOW = datetime(2026, 10, 14, 10, 50, tzinfo=UTC)  # 16:20 IST


def _run(db, run_id, kind, trace, modules, started=NOW):
    db.add(
        BrainRun(
            id=run_id, kind=kind, status="done", live=True, book="paper", as_of=started, started_at=started,
            modules=modules, trace=trace, banner_mode="DEFENSIVE", ms=360000,
        )
    )
    db.flush()


def _ev(module_id, status, reason=""):
    return {"step": "x", "module_id": module_id, "status": status, "reason": reason, "ms": 1, "version": "1"}


def test_compute_has_checks_run_summary_and_trial(db_session, tmp_path):
    _run(db_session, "dc-n", "nightly", [_ev("M02", "used")], {"M02": "on"})
    r = daily.compute(db_session, NOW, backup_dir=str(tmp_path))
    assert r["day"] == DAY.isoformat() and r["status"] in ("ok", "check")
    assert any(c["name"] == "Modules ran" for c in r["checks"])
    assert r["run"]["run_id"] == "dc-n" and r["run"]["modules_dropped"] == []
    assert r["trial"]["start"] == "2026-10-14" and "gate" in r["trial"]


def test_intraday_drops_today_make_the_day_a_check(db_session, tmp_path):
    _run(db_session, "dc-n2", "nightly", [_ev("M02", "used")], {"M02": "on"})
    _run(db_session, "dc-i1", "intraday", [_ev("M08", "fallback", "too slow: 1.6 s")], {"M08": "on"})
    r = daily.compute(db_session, NOW, backup_dir=str(tmp_path))
    assert r["status"] == "check"
    assert {"module": "M08", "reason": "too slow: 1.6 s", "runs": 1} in r["intraday"]["dropped"]


def test_store_keeps_one_row_per_day(db_session, tmp_path):
    _run(db_session, "dc-n3", "nightly", [], {})
    first = daily.compute(db_session, NOW, backup_dir=str(tmp_path))
    daily.store(db_session, first)
    daily.store(db_session, {**first, "status": "check"})
    rows = db_session.query(BrainDailyCheck).filter(BrainDailyCheck.day == DAY).all()
    assert len(rows) == 1 and rows[0].status == "check"


def test_message_only_when_something_is_wrong():
    ok = {"day": "2026-10-14", "status": "ok", "checks": [], "intraday": {"dropped": []}}
    assert daily.message_if_problem(ok) is None
    bad = {
        "day": "2026-10-14",
        "status": "check",
        "checks": [{"name": "Modules ran", "ok": False, "detail": "M02 dropped"}],
        "intraday": {"dropped": [{"module": "M08", "reason": "too slow", "runs": 3}]},
    }
    text = daily.message_if_problem(bad)
    assert "Modules ran" in text and "M08" in text


def test_job_skips_days_without_trading(db_session, monkeypatch):
    monkeypatch.setattr(jobs, "_ist_today", lambda: date(2026, 10, 17))  # a Saturday
    called = []
    monkeypatch.setattr(daily, "compute", lambda *a, **k: called.append(1))
    jobs.job_brain_daily_check()
    assert called == []


def test_job_never_raises(monkeypatch):
    monkeypatch.setattr(jobs, "_ist_today", lambda: DAY)
    monkeypatch.setattr(daily, "compute", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    jobs.job_brain_daily_check()  # must not raise


def test_endpoints_list_and_latest(client, db_session, tmp_path):
    _run(db_session, "dc-n4", "nightly", [], {})
    daily.store(db_session, daily.compute(db_session, NOW, backup_dir=str(tmp_path)))
    latest = client.get("/api/v1/brain/daily-checks/latest", headers=API_KEY)
    assert latest.status_code == 200 and latest.json()["day"] == "2026-10-14"
    listed = client.get("/api/v1/brain/daily-checks?days=30", headers=API_KEY).json()
    assert [r["day"] for r in listed] == ["2026-10-14"]
