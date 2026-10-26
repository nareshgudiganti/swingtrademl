"""Last run of every scheduled job, for the owner's Admin > Jobs page. Observe only.

The worker and the API are separate processes, so the API cannot ask the worker's in-memory scheduler
what ran. The worker records each job's last run here through an APScheduler event listener and writes
it to Redis (one hash, `stml:job_runs`, field = job id, value = JSON); the API reads it back. The job
list with each job's schedule and next run time already reaches the API through the heartbeat snapshot
(workers/heartbeat.py), so it is not published again.

Rules:
- Nothing here may slow down or break a job. The listener only updates memory; a background thread
  writes to Redis. A Redis failure is logged as a warning and retried; it never reaches a job.
- Almost every job catches its own errors and reports them (jobs._report_error) instead of raising, so
  APScheduler alone would call those runs a success. _report_error therefore also calls
  note_failure(), and the run is shown as failed.
- Only the error's kind (its class name) is stored, never its message, which can hold secrets.
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import UTC, datetime
from typing import Any

from apscheduler.events import (
    EVENT_JOB_ERROR,
    EVENT_JOB_EXECUTED,
    EVENT_JOB_MAX_INSTANCES,
    EVENT_JOB_MISSED,
    EVENT_JOB_SUBMITTED,
)

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.logging import get_logger

log = get_logger(__name__)

REDIS_KEY = "stml:job_runs"
REDIS_TIMEOUT_SECONDS = 1.0
RETRY_SECONDS = 5.0
WARN_EVERY_SECONDS = 300.0

# Plain-English names, in the order of a trading day. The one place job ids get a name.
JOB_LABELS: dict[str, tuple[str, str]] = {
    "heartbeat": ("Worker heartbeat", "Proves the background worker is alive"),
    "check_kite_login": ("Zerodha login check", "Picks up a finished Zerodha login"),
    "flush_alerts": ("Held alerts", "Sends alerts held for quiet hours or the daily digest"),
    "server_watch": ("Server memory watch", "Records memory, warns when low, restarts a bloated process"),
    "brain_run_queue": ("Brain: queued runs", "Runs 'Run the brain now' requests one at a time"),
    "kite_auto_login": ("Zerodha auto-login", "Logs in to Zerodha before the market opens"),
    "nag_missing_session": ("Zerodha login reminder", "Alerts you if Zerodha is still not logged in"),
    "daily_market_feeds_morning": ("NSE morning files", "Surveillance lists and results calendar"),
    "brain_approvals_open": ("Brain: approved buys at the open", "Buys ideas you approved after the close"),
    "refresh_quotes": ("Live prices", "Refreshes prices during market hours"),
    "check_exits": ("Stop-loss and target check", "Checks open positions for exits"),
    "reconcile_orders": ("Order status check", "Matches orders with Zerodha"),
    "brain_intraday": ("Brain: holdings check", "Re-checks held stocks every 15 minutes"),
    "daily_ingest": ("Daily candles", "Downloads the day's prices after the close"),
    "predict_watchlist": ("Watchlist scores", "Scores the watchlist with the model"),
    "signal_scan": ("Daily scan", "Looks for new trades"),
    "sync_real_holdings": ("My Zerodha holdings sync", "Drops shares you sold by hand"),
    "brain_nightly": ("Brain: nightly run", "The brain's daily ideas"),
    "capture_fills": ("Save today's trades", "Saves the day's real trades from Zerodha"),
    "daily_summary": ("Daily summary", "Sends the end-of-day summary"),
    "evaluate_predictions": ("Check old predictions", "Marks past predictions right or wrong"),
    "evaluate_signals": ("Check old signals", "Marks past signals right or wrong"),
    "brain_daily_check": ("Brain: daily check", "Checks the brain's run and reports problems"),
    "backup_models": ("Model backup", "Copies trained models to the backup folder"),
    "daily_market_feeds": ("NSE evening files", "Delivery %, bulk deals, FII/DII"),
    "company_filings": ("Company filings", "Saves what tracked companies filed: announcements, shareholding"),
    "capture_fills_evening": ("Save today's trades (evening)", "Second try, in case Zerodha was logged out"),
    "score_experiments": ("Research experiments", "Scores the research picks"),
    "sync_mutual_fund_navs": ("Mutual fund prices", "Downloads mutual fund NAVs"),
    "daily_market_feeds_final": ("NSE files: final check", "Alerts if a day's NSE files are still missing"),
    "brain_learn": ("Brain: weekly learning", "The brain's weekly learning run"),
    "brain_weekly_health": ("Brain: weekly health report", "Weekly report on the brain"),
    "sync_instruments": ("Stock list refresh", "Refreshes Zerodha's list of stocks"),
}


def label_for(job_id: str) -> tuple[str, str]:
    return JOB_LABELS.get(job_id, (job_id.replace("_", " ").capitalize(), ""))


def order_key(job_id: str) -> tuple[int, str]:
    ids = list(JOB_LABELS)
    return (ids.index(job_id), "") if job_id in ids else (len(ids), job_id)


# ------------------------------------------------------------------ schedule in plain English --

_DAYS = {
    "mon-fri": "Weekdays",
    "sat": "Saturdays",
    "sun": "Sundays",
    "mon-sun": "Every day",
    "*": "Every day",
}


def _hm(hour: int, minute: int) -> str:
    return f"{hour:02d}:{minute:02d}"


def _ints(spec: str) -> list[int] | None:
    """'15' -> [15]; '6-15' -> [6..15]; '15,45' -> [15, 45]; anything else -> None."""
    out: list[int] = []
    for part in spec.split(","):
        if re.fullmatch(r"\d+", part):
            out.append(int(part))
        elif m := re.fullmatch(r"(\d+)-(\d+)", part):
            out.extend(range(int(m[1]), int(m[2]) + 1))
        else:
            return None
    return out


def _plural(n: int, word: str) -> str:
    return f"{word}" if n == 1 else f"{n} {word}s"


def describe_schedule(trigger: str) -> str:
    """APScheduler's trigger text in plain English. Unknown shapes come back unchanged."""
    if m := re.fullmatch(r"interval\[(\d+):(\d\d):(\d\d)\]", trigger):
        h, mi, s = int(m[1]), int(m[2]), int(m[3])
        total = h * 3600 + mi * 60 + s
        if total % 3600 == 0:
            return f"Every {_plural(total // 3600, 'hour')}"
        if total % 60 == 0:
            return f"Every {_plural(total // 60, 'minute')}"
        return f"Every {_plural(total, 'second')}"
    m = re.fullmatch(r"cron\[(.*)\]", trigger)
    if not m:
        return trigger
    fields = dict(re.findall(r"(\w+)='([^']*)'", m[1]))
    if set(fields) - {"day_of_week", "hour", "minute", "second"} or fields.get("second", "0") != "0":
        return trigger
    days = _DAYS.get(fields.get("day_of_week", "*"))
    hours = _ints(fields.get("hour", "*"))
    minutes = _ints(fields.get("minute", "0"))
    if days is None or not hours or not minutes:
        return trigger
    first, last = _hm(hours[0], minutes[0]), _hm(hours[-1], minutes[-1])
    if len(hours) == 1 and len(minutes) == 1:
        return f"{days} at {first}"
    if len(hours) == 1 and minutes == list(range(minutes[0], minutes[-1] + 1)):
        return f"{days}, every minute {first} to {last}"
    step = minutes[1] - minutes[0] if len(minutes) > 1 else 60
    even = minutes[0] == 0 and minutes == list(range(0, 60, step))
    if len(minutes) == 1:
        return f"{days}, hourly at :{minutes[0]:02d}, {first} to {last}"
    if even:
        return f"{days}, every {step} minutes, {first} to {last}"
    at = " and ".join(f":{mm:02d}" for mm in minutes)
    return f"{days}, at {at} past each hour, {first} to {last}"


# --------------------------------------------------------------------------- the recorder --


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(UTC).isoformat() if dt else None


def _redis_client():
    import redis

    return redis.Redis.from_url(
        settings.REDIS_URL,
        socket_timeout=REDIS_TIMEOUT_SECONDS,
        socket_connect_timeout=REDIS_TIMEOUT_SECONDS,
    )


class JobRunRecorder:
    """Keeps each job's last run in memory and hands it to Redis off the job's thread."""

    def __init__(self, client_factory=_redis_client) -> None:
        self._client_factory = client_factory
        self._client = None
        self._lock = threading.Lock()
        self._records: dict[str, dict[str, Any]] = {}
        self._running: dict[str, tuple[datetime, datetime]] = {}  # job id -> (run key, started)
        self._dirty: set[str] = set()
        # Failures a job reported itself (jobs._report_error), by thread: (error kind, when).
        self._reported: dict[int, tuple[str, datetime]] = {}
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_warning = 0.0

    # -- called by the job itself (through jobs._report_error) --
    def note_failure(self, exc: BaseException) -> None:
        try:
            with self._lock:
                self._reported[threading.get_ident()] = (type(exc).__name__, _now())
        except Exception:  # noqa: BLE001 - never disturb the job
            pass

    # -- the APScheduler listener --
    def listener(self, event) -> None:
        try:
            self._handle(event)
        except Exception as exc:  # noqa: BLE001 - a listener error must never reach the scheduler
            log.warning("job_runs.listener_failed", error_kind=type(exc).__name__)

    def _handle(self, event) -> None:
        code = event.code
        job_id = event.job_id
        now = _now()
        with self._lock:
            rec = self._records.setdefault(job_id, {"job_id": job_id})
            if code == EVENT_JOB_SUBMITTED:
                run_key = event.scheduled_run_times[-1]
                # The submitted event is sent after the job is handed to a thread; a very fast job
                # can already have finished. Don't mark a finished run as running again.
                if rec.get("_run_key") == run_key:
                    return
                self._running[job_id] = (run_key, now)
                rec["running_since"] = _iso(now)
            elif code in (EVENT_JOB_EXECUTED, EVENT_JOB_ERROR):
                run_key = event.scheduled_run_time
                started = run_key
                if (running := self._running.get(job_id)) and running[0] == run_key:
                    started = running[1]
                    del self._running[job_id]
                reported = self._reported.pop(threading.get_ident(), None)
                if code == EVENT_JOB_ERROR:
                    status, kind = "failed", type(event.exception).__name__
                elif reported and reported[1] >= run_key:
                    status, kind = "failed", reported[0]
                else:
                    status, kind = "ok", None
                rec.update(
                    _run_key=run_key,
                    last_started_at=_iso(started),
                    last_finished_at=_iso(now),
                    last_duration_s=round(max(0.0, (now - started).total_seconds()), 1),
                    last_status=status,
                    last_error_kind=kind,
                    running_since=None,
                )
            elif code == EVENT_JOB_MISSED:
                rec["last_missed_at"] = _iso(event.scheduled_run_time)
            elif code == EVENT_JOB_MAX_INSTANCES:
                rec["last_skipped_at"] = _iso(now)
            else:
                return
            self._dirty.add(job_id)
        self._wake.set()

    # -- writing to Redis --
    def flush(self) -> bool:
        """Write every changed record to Redis. Never raises; False when Redis could not be reached."""
        with self._lock:
            if not self._dirty:
                return True
            batch = {
                jid: json.dumps({k: v for k, v in self._records[jid].items() if not k.startswith("_")})
                for jid in self._dirty
            }
            self._dirty.clear()
        try:
            if self._client is None:
                self._client = self._client_factory()
            self._client.hset(REDIS_KEY, mapping=batch)
            return True
        except Exception as exc:  # noqa: BLE001 - Redis down must never break a job
            with self._lock:
                self._dirty |= set(batch)
            self._client = None
            if time.monotonic() - self._last_warning > WARN_EVERY_SECONDS:
                self._last_warning = time.monotonic()
                log.warning("job_runs.redis_write_failed", error_kind=type(exc).__name__)
            return False

    def _writer(self) -> None:
        while True:
            self._wake.wait()
            self._wake.clear()
            if not self.flush():
                time.sleep(RETRY_SECONDS)
                self._wake.set()

    def attach(self, scheduler, start_writer: bool = True) -> None:
        scheduler.add_listener(
            self.listener,
            EVENT_JOB_SUBMITTED
            | EVENT_JOB_EXECUTED
            | EVENT_JOB_ERROR
            | EVENT_JOB_MISSED
            | EVENT_JOB_MAX_INSTANCES,
        )
        if start_writer and self._thread is None:
            self._thread = threading.Thread(target=self._writer, name="job-runs-writer", daemon=True)
            self._thread.start()

    def snapshot(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            return {k: v for k, v in self._records.get(job_id, {}).items() if not k.startswith("_")}


recorder = JobRunRecorder()


def attach(scheduler) -> None:
    """Called once by the worker at scheduler start. Never raises."""
    try:
        recorder.attach(scheduler)
    except Exception as exc:  # noqa: BLE001 - observing must never stop the scheduler starting
        log.warning("job_runs.attach_failed", error_kind=type(exc).__name__)


def note_failure(exc: BaseException) -> None:
    recorder.note_failure(exc)


# --------------------------------------------------------------------------- reading (API) --


def read_runs(client_factory=_redis_client) -> tuple[dict[str, dict[str, Any]], bool]:
    """Every job's last-run record from Redis, and whether Redis could be read at all."""
    try:
        raw = client_factory().hgetall(REDIS_KEY)
    except Exception as exc:  # noqa: BLE001
        log.warning("job_runs.redis_read_failed", error_kind=type(exc).__name__)
        return {}, False
    out: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        jid = key.decode() if isinstance(key, bytes) else str(key)
        try:
            out[jid] = json.loads(value)
        except (TypeError, ValueError):
            continue
    return out, True
