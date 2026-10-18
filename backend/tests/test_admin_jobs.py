"""Admin > Jobs (tracker ux9): the worker's job-run listener and the owner-only endpoint. Observe only."""

from __future__ import annotations

import importlib
import json
import threading
from datetime import UTC, datetime, timedelta

import pytest
from apscheduler.events import (
    EVENT_JOB_ERROR,
    EVENT_JOB_EXECUTED,
    EVENT_JOB_MAX_INSTANCES,
    EVENT_JOB_MISSED,
    EVENT_JOB_SUBMITTED,
    JobExecutionEvent,
    JobSubmissionEvent,
)
from apscheduler.schedulers.background import BackgroundScheduler

from swing_trade_ml.api.v1.endpoints import jobs as jobs_endpoint
from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.session import User
from swing_trade_ml.workers import job_runs
from swing_trade_ml.workers.job_runs import JobRunRecorder, describe_schedule

# `from swing_trade_ml.workers import scheduler` would give the BackgroundScheduler instance, not the module.
scheduler_module = importlib.import_module("swing_trade_ml.workers.scheduler")
_REAL_READ = job_runs.read_runs  # kept before any test monkeypatches it


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, dict[str, str]] = {}

    def hset(self, key, mapping):
        self.data.setdefault(key, {}).update(mapping)

    def hgetall(self, key):
        return {k.encode(): v.encode() for k, v in self.data.get(key, {}).items()}


class DownRedis:
    def hset(self, key, mapping):
        raise ConnectionError("redis is down")

    def hgetall(self, key):
        raise ConnectionError("redis is down")


def _t(minutes: int = 0) -> datetime:
    return datetime(2026, 10, 19, 10, 10, tzinfo=UTC) + timedelta(minutes=minutes)


def _submitted(job_id: str, run: datetime):
    return JobSubmissionEvent(EVENT_JOB_SUBMITTED, job_id, "default", [run])


def _done(code: int, job_id: str, run: datetime, exc: BaseException | None = None):
    return JobExecutionEvent(code, job_id, "default", run, exception=exc)


# ---------------------------------------------------------------- the listener --


def test_executed_run_is_recorded_ok_with_start_and_duration():
    fake = FakeRedis()
    rec = JobRunRecorder(client_factory=lambda: fake)
    rec.listener(_submitted("daily_ingest", _t()))
    assert rec.snapshot("daily_ingest")["running_since"]
    rec.listener(_done(EVENT_JOB_EXECUTED, "daily_ingest", _t()))
    snap = rec.snapshot("daily_ingest")
    assert snap["last_status"] == "ok"
    assert snap["last_error_kind"] is None
    assert snap["running_since"] is None
    assert snap["last_started_at"] and snap["last_finished_at"]
    assert snap["last_duration_s"] >= 0
    assert rec.flush() is True
    stored = json.loads(fake.data[job_runs.REDIS_KEY]["daily_ingest"])
    assert stored["last_status"] == "ok"
    assert "_run_key" not in stored


def test_raised_error_is_recorded_failed_with_kind_only_no_message():
    rec = JobRunRecorder(client_factory=FakeRedis)
    rec.listener(_submitted("signal_scan", _t()))
    rec.listener(_done(EVENT_JOB_ERROR, "signal_scan", _t(), ValueError("token=SECRET123")))
    snap = rec.snapshot("signal_scan")
    assert snap["last_status"] == "failed"
    assert snap["last_error_kind"] == "ValueError"
    assert "SECRET123" not in json.dumps(snap)


def test_failure_reported_by_the_job_itself_counts_as_failed():
    """Jobs catch their own errors and call _report_error; APScheduler sees success."""
    rec = JobRunRecorder(client_factory=FakeRedis)
    run = datetime.now(UTC) - timedelta(seconds=1)
    rec.listener(_submitted("brain_nightly", run))
    rec.note_failure(TimeoutError("db password in here"))
    rec.listener(_done(EVENT_JOB_EXECUTED, "brain_nightly", run))
    snap = rec.snapshot("brain_nightly")
    assert snap["last_status"] == "failed"
    assert snap["last_error_kind"] == "TimeoutError"
    # The note is used once: the next clean run on this thread is OK again.
    run2 = datetime.now(UTC)
    rec.listener(_submitted("brain_nightly", run2))
    rec.listener(_done(EVENT_JOB_EXECUTED, "brain_nightly", run2))
    assert rec.snapshot("brain_nightly")["last_status"] == "ok"


def test_missed_and_skipped_runs_are_recorded():
    rec = JobRunRecorder(client_factory=FakeRedis)
    rec.listener(_done(EVENT_JOB_MISSED, "backup_models", _t()))
    rec.listener(JobSubmissionEvent(EVENT_JOB_MAX_INSTANCES, "backup_models", "default", [_t()]))
    snap = rec.snapshot("backup_models")
    assert snap["last_missed_at"] == _t().isoformat()
    assert snap["last_skipped_at"]
    assert "last_status" not in snap


def test_submitted_after_a_fast_run_finished_does_not_mark_it_running_again():
    rec = JobRunRecorder(client_factory=FakeRedis)
    rec.listener(_done(EVENT_JOB_EXECUTED, "heartbeat", _t()))
    rec.listener(_submitted("heartbeat", _t()))
    snap = rec.snapshot("heartbeat")
    assert snap["running_since"] is None
    assert snap["last_status"] == "ok"


def test_listener_swallows_its_own_errors():
    rec = JobRunRecorder(client_factory=FakeRedis)
    rec.listener(object())  # not an event at all: must not raise


def test_redis_down_never_raises_and_retries_later():
    state = {"down": True}
    fake = FakeRedis()

    def factory():
        return DownRedis() if state["down"] else fake

    rec = JobRunRecorder(client_factory=factory)
    rec.listener(_done(EVENT_JOB_EXECUTED, "daily_summary", _t()))
    assert rec.flush() is False  # no exception
    state["down"] = False
    assert rec.flush() is True  # the record was kept and written once Redis is back
    assert "daily_summary" in fake.data[job_runs.REDIS_KEY]


def test_a_real_scheduler_job_runs_normally_with_redis_down():
    ran = threading.Event()
    rec = JobRunRecorder(client_factory=DownRedis)
    sched = BackgroundScheduler(timezone="UTC")
    rec.attach(sched)  # also starts the writer thread, which keeps failing against DownRedis
    sched.add_job(ran.set, "date", run_date=datetime.now(UTC) + timedelta(milliseconds=50), id="probe")
    sched.start()
    try:
        assert ran.wait(5), "the job did not run"
        for _ in range(50):
            if rec.snapshot("probe").get("last_status"):
                break
            threading.Event().wait(0.05)
        assert rec.snapshot("probe")["last_status"] == "ok"
    finally:
        sched.shutdown(wait=False)


def test_report_error_marks_the_run_failed(monkeypatch):
    from swing_trade_ml.workers import jobs

    seen = []
    monkeypatch.setattr(jobs.notifier, "send_sync", lambda *a, **k: None)
    monkeypatch.setattr(job_runs.recorder, "note_failure", lambda exc: seen.append(type(exc).__name__))
    jobs._report_error("daily_ingest", RuntimeError("boom"))
    assert seen == ["RuntimeError"]


def test_scheduler_attaches_the_listener_once_at_start(monkeypatch):
    calls = []
    monkeypatch.setattr(scheduler_module.settings, "ENABLE_SCHEDULER", True)
    monkeypatch.setattr(scheduler_module.job_runs, "attach", lambda s: calls.append(s))
    fresh = _paused_scheduler(monkeypatch)
    monkeypatch.setattr(scheduler_module, "scheduler", fresh)
    scheduler_module.start_scheduler()
    try:
        assert calls == [fresh]
        assert len(fresh.get_jobs()) >= 20
    finally:
        fresh.shutdown(wait=False)


def test_every_registered_job_has_a_plain_english_name(monkeypatch):
    monkeypatch.setattr(scheduler_module.settings, "BRAIN_ENABLED", True)
    fresh = _paused_scheduler(monkeypatch)
    for job in _registered_ids(monkeypatch, fresh):
        assert job in job_runs.JOB_LABELS, f"{job} has no name in job_runs.JOB_LABELS"


def _paused_scheduler(monkeypatch) -> BackgroundScheduler:
    """A scheduler that registers jobs but never runs one."""
    fresh = BackgroundScheduler(timezone="UTC")
    real_start = fresh.start
    monkeypatch.setattr(fresh, "start", lambda *a, **k: real_start(paused=True))
    return fresh


def _registered_ids(monkeypatch, fresh):
    monkeypatch.setattr(scheduler_module.settings, "ENABLE_SCHEDULER", True)
    monkeypatch.setattr(scheduler_module.job_runs, "attach", lambda s: None)
    monkeypatch.setattr(scheduler_module, "scheduler", fresh)
    scheduler_module.start_scheduler()
    try:
        return [j.id for j in fresh.get_jobs()]
    finally:
        fresh.shutdown(wait=False)


@pytest.mark.parametrize(
    ("trigger", "text"),
    [
        ("interval[0:01:00]", "Every minute"),
        ("interval[0:00:10]", "Every 10 seconds"),
        ("interval[0:05:00]", "Every 5 minutes"),
        ("cron[day_of_week='mon-fri', hour='15', minute='40']", "Weekdays at 15:40"),
        ("cron[day_of_week='sun', hour='8', minute='0']", "Sundays at 08:00"),
        ("cron[day_of_week='mon-fri', hour='9', minute='15-19']", "Weekdays, every minute 09:15 to 09:19"),
        (
            "cron[day_of_week='mon-fri', hour='9-15', minute='0,15,30,45']",
            "Weekdays, every 15 minutes, 09:00 to 15:45",
        ),
        (
            "cron[day_of_week='mon-fri', hour='6-15', minute='15,45']",
            "Weekdays, at :15 and :45 past each hour, 06:15 to 15:45",
        ),
        ("date[2026-10-19 10:00:00 UTC]", "date[2026-10-19 10:00:00 UTC]"),
    ],
)
def test_describe_schedule(trigger, text):
    assert describe_schedule(trigger) == text


# ---------------------------------------------------------------- the endpoint --

URL = "/api/v1/admin/jobs"


def _as(db, username: str, role: str) -> dict[str, str]:
    user = User(username=username, hashed_password="x", is_active=True, role=role, plan="free")
    db.add(user)
    db.flush()
    return {"Authorization": f"Bearer {create_access_token(user.username, {'uid': user.id, 'tv': 0})}"}


@pytest.fixture()
def _worker_state(monkeypatch):
    monkeypatch.setattr(
        jobs_endpoint,
        "list_jobs",
        lambda: [
            {
                "id": "signal_scan",
                "name": "job_signal_scan",
                "trigger": "cron[day_of_week='mon-fri', hour='15', minute='45']",
                "next_run": "2026-10-19T15:45:00+05:30",
            },
            {
                "id": "daily_ingest",
                "name": "job_daily_ingest",
                "trigger": "cron[day_of_week='mon-fri', hour='15', minute='40']",
                "next_run": "2026-10-19T15:40:00+05:30",
            },
        ],
    )
    fake = FakeRedis()
    fake.hset(
        job_runs.REDIS_KEY,
        {
            "daily_ingest": json.dumps(
                {"last_status": "failed", "last_error_kind": "OperationalError", "last_duration_s": 3.2}
            ),
            "old_removed_job": json.dumps({"last_status": "ok"}),
        },
    )
    monkeypatch.setattr(job_runs, "read_runs", lambda: _REAL_READ(lambda: fake))
    monkeypatch.setattr(jobs_endpoint.heartbeat, "is_alive", lambda: True)


def test_owner_gets_every_job_in_day_order(client, db_session, _worker_state):
    r = client.get(URL, headers=_as(db_session, "jobs-owner", "owner"))
    assert r.status_code == 200
    body = r.json()
    assert body["worker_alive"] is True and body["runs_available"] is True
    ids = [j["id"] for j in body["jobs"]]
    assert ids == ["daily_ingest", "signal_scan", "old_removed_job"]
    ingest = body["jobs"][0]
    assert ingest["name"] == "Daily candles"
    assert ingest["schedule"] == "Weekdays at 15:40"
    assert ingest["next_run"] == "2026-10-19T15:40:00+05:30"
    assert ingest["last_status"] == "failed" and ingest["last_error_kind"] == "OperationalError"
    assert body["jobs"][1]["last_status"] is None  # never ran yet
    assert body["jobs"][2]["registered"] is False


def test_api_key_counts_as_owner(client, _worker_state):
    assert client.get(URL, headers={"X-API-Key": "test-api-key"}).status_code == 200


@pytest.mark.parametrize("role", ["member", "tester"])
def test_non_owner_is_refused(client, db_session, role, _worker_state):
    assert client.get(URL, headers=_as(db_session, f"jobs-{role}", role)).status_code == 403


def test_no_credentials_is_refused(client, _worker_state):
    assert client.get(URL).status_code == 401


def test_redis_down_still_lists_jobs(client, monkeypatch, _worker_state):
    monkeypatch.setattr(job_runs, "read_runs", lambda: _REAL_READ(DownRedis))
    body = client.get(URL, headers={"X-API-Key": "test-api-key"}).json()
    assert body["runs_available"] is False
    assert [j["id"] for j in body["jobs"]] == ["daily_ingest", "signal_scan"]
