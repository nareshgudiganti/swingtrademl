"""The Saturday health check: pure checks, the stored result, the job (which
never raises and still stores with Telegram off) and the read-only endpoint."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock

from swing_trade_ml.core.holidays import NSE_HOLIDAYS
from swing_trade_ml.core.market_session import is_trading_day, last_closed_trading_day
from swing_trade_ml.db.models.brain import BrainLearningRun, BrainRun, BrainWeeklyHealth
from swing_trade_ml.services import brain_weekly_health as w
from swing_trade_ml.workers import jobs

HEADERS = {"X-API-Key": "test-api-key"}
SAT = datetime(2026, 10, 10, 5, 30, tzinfo=UTC)  # Saturday 11:00 IST
FRI = date(2026, 10, 9)


def _ist(d: date, hh: int = 16) -> datetime:
    return datetime(d.year, d.month, d.day, hh, 0, tzinfo=w.IST).astimezone(UTC)


def test_nightly_from_last_trading_day_is_ok():
    assert is_trading_day(FRI) and last_closed_trading_day(SAT) == FRI
    assert w.check_last_nightly({"last_nightly_ok": _ist(FRI)}, FRI)["ok"]


def test_stale_or_missing_nightly_is_flagged():
    assert not w.check_last_nightly({"last_nightly_ok": _ist(FRI - timedelta(days=2))}, FRI)["ok"]
    assert not w.check_last_nightly({"last_nightly_ok": None}, FRI)["ok"]


def test_a_holiday_friday_does_not_false_alarm():
    holiday = next(d for d in sorted(NSE_HOLIDAYS[2026]) if d.weekday() == 4)
    saturday = datetime.combine(holiday + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    expected = last_closed_trading_day(saturday)
    assert expected < holiday
    assert w.check_last_nightly({"last_nightly_ok": _ist(expected)}, expected)["ok"]


def test_failed_runs_and_data():
    assert w.check_failed_runs({"failed_runs_7d": 0})["ok"]
    assert not w.check_failed_runs({"failed_runs_7d": 2})["ok"]
    assert w.check_data_fresh({"data": {"fresh": True}})["ok"]
    assert not w.check_data_fresh({"data": {"fresh": False}, "stale_count": 3})["ok"]
    assert not w.check_data_fresh({"data": {"fresh": None}})["ok"]


def test_feeds_recent_old_and_missing():
    feeds = [
        {"name": "delivery", "latest": FRI.isoformat()},
        {"name": "bulk_deals", "latest": (FRI - timedelta(days=30)).isoformat()},
        {"name": "fii_dii", "latest": None},
    ]
    ok = [c["ok"] for c in w.check_feeds({"feeds": feeds}, FRI)]
    assert ok == [True, False, False]


def test_modules_and_stage():
    on = [{"id": m, "mode": "on"} for m in w.REQUIRED_MODULES]
    assert w.check_modules(on)["ok"]
    off = [{"id": "M01", "mode": "off"}, *on[1:]]
    assert not w.check_modules(off)["ok"] and "M01" in w.check_modules(off)["detail"]
    assert not w.check_modules([])["ok"]
    assert w.check_stage({"stage": "shadow"})["ok"]
    assert not w.check_stage({"stage": "approval"})["ok"]


def test_progress_is_information_not_failure():
    c = w.check_progress({"finished": 4, "needed": 30})
    assert c["ok"] and c["level"] == "info" and "4 of 30" in c["detail"]


def test_backup_without_record_is_a_warning(tmp_path):
    assert w.check_backup("")["level"] == "warn" and not w.check_backup("")["ok"]
    assert w.check_backup(str(tmp_path / "nope"))["level"] == "warn"
    assert w.check_backup(str(tmp_path))["level"] == "warn"
    (tmp_path / "m.joblib").write_bytes(b"x")
    assert w.check_backup(str(tmp_path))["ok"]


def test_learning_not_checked_yet_then_checked(db_session):
    assert w.check_learning(db_session, SAT)["detail"] == "Not checked yet."
    db_session.add(BrainLearningRun(created_at=SAT - timedelta(hours=2), drift_lines=["RSI moved"]))
    db_session.flush()
    c = w.check_learning(db_session, SAT)
    assert c["ok"] and "RSI moved" in c["detail"]


def test_banner_reads_the_last_live_nightly(db_session):
    db_session.add(
        BrainRun(
            id="wh-banner",
            kind="nightly",
            status="done",
            live=True,
            banner_mode="NO_NEW_TRADES",
            started_at=SAT,
            as_of=SAT,
            book="paper",
        )
    )
    db_session.flush()
    assert "NO NEW TRADES" in w.check_banner(db_session)["detail"]


def test_compute_checks_returns_every_check_and_never_raises(db_session, monkeypatch, tmp_path):
    result = w.compute_checks(db_session, SAT, backup_dir=str(tmp_path))
    names = [c["name"] for c in result["checks"]]
    for expected in (
        "Nightly run",
        "Failed runs",
        "Data freshness",
        "Key modules",
        "Trading stage",
        "Banner",
    ):
        assert expected in names
    assert result["status"] in ("ok", "check")
    assert all(set(c) >= {"name", "ok", "detail"} for c in result["checks"])

    from swing_trade_ml.brain import service

    monkeypatch.setattr(service, "health", MagicMock(side_effect=RuntimeError("boom")))
    broken = w.compute_checks(db_session, SAT, backup_dir=str(tmp_path))
    assert broken["status"] == "check"
    assert any(c["name"] == "Brain health" and not c["ok"] for c in broken["checks"])


def test_message_lines_and_escaping():
    result = {"checks": [w._check("A", True, "fine"), w._check("B", False, "x < y")]}
    text = w.format_message(result)
    assert "OK A: fine" in text and "CHECK B: x &lt; y" in text and "1 thing" in text


def test_store_and_latest_result(db_session):
    assert w.latest_result(db_session)["run"] is False
    w.store_result(db_session, {"status": "ok", "checks": [w._check("A", True, "fine")]})
    w.store_result(db_session, {"status": "check", "checks": [w._check("B", False, "bad")]})
    last = w.latest_result(db_session)
    assert last["run"] and last["status"] == "check" and last["checks"][0]["name"] == "B"


def _patch_session(monkeypatch, db_session):
    @contextmanager
    def scope():
        yield db_session

    monkeypatch.setattr(jobs, "session_scope", scope)


def test_job_stores_and_sends_one_message_and_survives_telegram_off(db_session, monkeypatch):
    _patch_session(monkeypatch, db_session)
    sent = MagicMock(return_value=False)  # Telegram disabled answers False, never raises
    monkeypatch.setattr(jobs.notifier, "send_sync", sent)
    jobs.job_brain_weekly_health()
    sent.assert_called_once()
    assert db_session.query(BrainWeeklyHealth).count() == 1


def test_job_never_raises(db_session, monkeypatch):
    _patch_session(monkeypatch, db_session)
    monkeypatch.setattr(w, "compute_checks", MagicMock(side_effect=RuntimeError("x")))
    reported = MagicMock()
    monkeypatch.setattr(jobs, "_report_error", reported)
    jobs.job_brain_weekly_health()
    reported.assert_called_once()


def test_endpoint_not_run_yet_then_last_result(client, db_session):
    first = client.get("/api/v1/brain/weekly-health", headers=HEADERS)
    assert first.status_code == 200 and first.json()["run"] is False
    w.store_result(db_session, {"status": "ok", "checks": [w._check("A", True, "fine")]})
    body = client.get("/api/v1/brain/weekly-health", headers=HEADERS).json()
    assert body["run"] and body["status"] == "ok"


def test_endpoint_needs_the_key(client):
    assert client.get("/api/v1/brain/weekly-health").status_code in (401, 403)
