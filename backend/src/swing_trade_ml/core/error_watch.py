"""Error watch (qa9): the app counts its own errors, so a NEW kind of error reaches the owner.

No new infrastructure: every log record at ERROR or above adds 1 to a per-day counter in the Redis
the stack already runs. Only a short, stable "kind" and a count are stored - never the message, so
no symbol, amount, token or password can end up in Redis. The daily check
(services/server_health.py) compares the newest days with the 14 before them and warns on a kind it
has not seen.

A kind is the logger name plus the structlog event name (digits replaced by '#'), the job name for
"job.failed", and the exception class when there is one. For example:
    swing_trade_ml.workers.jobs: job.failed job=brain_learn
    apscheduler.executors.default (ValueError)

Counting must never break logging: Redis down, slow or missing is swallowed, and after one failure
the counter rests for a minute so a burst of errors does not wait on a dead Redis each time.

"Error days" end at 16:20 IST, the time the daily check reads them: an error at 16:25 counts toward
tomorrow's check, so nothing falls between two checks.
"""

from __future__ import annotations

import logging
import re
import sys
import threading
import time as _time
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
KEY_PREFIX = "errwatch:day:"
KEEP_DAYS = 35  # comfortably more than the 14-day comparison window plus long holidays
ERROR_DAY_ENDS = time(16, 20)  # the brain daily check's time (workers/scheduler.py)
KIND_MAX = 160
EVENT_MAX = 80
# Extra fields whose value is a fixed name in the code, so they split kinds usefully and safely.
STABLE_FIELDS = ("job",)
RETRY_AFTER_SECONDS = 60.0

_DIGITS = re.compile(r"\d+")
_SPACES = re.compile(r"\s+")


def _clean(text: object, limit: int) -> str:
    s = _DIGITS.sub("#", str(text))
    s = _SPACES.sub(" ", s).strip()
    return s[:limit]


def error_kind(
    logger: str | None, event: object = None, exc_name: str | None = None, fields: dict | None = None
) -> str:
    """A short, stable name for one kind of error. Numbers never split a kind; messages never
    enter it."""
    parts = [_clean(logger or "unknown", 60)]
    if event:
        parts[0] += ":"
        parts.append(_clean(event, EVENT_MAX))
    for key in STABLE_FIELDS:
        value = (fields or {}).get(key)
        if isinstance(value, str) and value:
            parts.append(f"{key}={_clean(value, 40)}")
    if exc_name:
        parts.append(f"({_clean(exc_name, 60)})")
    return " ".join(parts)[:KIND_MAX]


def _exc_name(exc_info: object) -> str | None:
    if exc_info is True:
        exc_info = sys.exc_info()
    if isinstance(exc_info, BaseException):
        return type(exc_info).__name__
    if isinstance(exc_info, tuple) and exc_info and exc_info[0] is not None:
        return getattr(exc_info[0], "__name__", None)
    return None


def error_day(now: datetime | None = None) -> date:
    """The daily check this moment belongs to: today's until 16:20 IST, tomorrow's after."""
    local = (now or datetime.now(UTC)).astimezone(IST)
    return local.date() + timedelta(days=1) if local.time() >= ERROR_DAY_ENDS else local.date()


def day_key(day: date) -> str:
    return f"{KEY_PREFIX}{day.isoformat()}"


class _Counter:
    """Adds one error to Redis. Never raises; rests after a failure."""

    def __init__(self) -> None:
        self._client = None
        self._resting_until = 0.0
        self._local = threading.local()

    def _redis(self):
        if self._client is None:
            import redis

            from swing_trade_ml.core.config import settings

            # Short timeouts: this runs inside a log call, on the API's request path too.
            self._client = redis.Redis.from_url(
                settings.REDIS_URL, socket_timeout=0.25, socket_connect_timeout=0.25
            )
        return self._client

    def record(self, kind: str, now: datetime | None = None, client=None) -> bool:
        if getattr(self._local, "busy", False):
            return False  # an error logged while counting an error (e.g. by redis itself)
        if client is None and _time.monotonic() < self._resting_until:
            return False
        self._local.busy = True
        try:
            r = client if client is not None else self._redis()
            key = day_key(error_day(now))
            pipe = r.pipeline(transaction=False)
            pipe.hincrby(key, kind, 1)
            pipe.expire(key, KEEP_DAYS * 86400)
            pipe.execute()
            return True
        except Exception:  # noqa: BLE001 - counting must never break logging
            self._resting_until = _time.monotonic() + RETRY_AFTER_SECONDS
            return False
        finally:
            self._local.busy = False


_counter = _Counter()


def record_error(kind: str, now: datetime | None = None, client=None) -> bool:
    return _counter.record(kind, now, client)


def tag_error_kind(logger, method_name: str, event_dict: dict) -> dict:
    """structlog processor (before format_exc_info): name the kind of an ERROR event while the
    event name and exception are still at hand. The renderer wrapper hands it to stdlib."""
    try:
        if event_dict.get("level") in ("error", "critical"):  # add_log_level runs first
            event_dict["_error_kind"] = error_kind(
                event_dict.get("logger") or getattr(logger, "name", None),
                event_dict.get("event"),
                _exc_name(event_dict.get("exc_info")),
                event_dict,
            )
    except Exception:  # noqa: BLE001
        pass
    return event_dict


def with_error_kind(renderer):
    """Wrap the final structlog renderer so the kind travels to stdlib as `extra`, out of the
    rendered line."""

    def render(logger, method_name: str, event_dict: dict):
        kind = event_dict.pop("_error_kind", None)
        out = renderer(logger, method_name, event_dict)
        if kind is None:
            return out
        return (out,), {"extra": {"error_kind": kind}}

    return render


class ErrorWatchHandler(logging.Handler):
    """On the root logger at ERROR: counts structlog and plain stdlib errors alike (apscheduler's
    "job raised an exception", for one). Reads the kind, never the message."""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            kind = getattr(record, "error_kind", None) or error_kind(
                record.name, None, _exc_name(record.exc_info)
            )
            record_error(kind)
        except Exception:  # noqa: BLE001
            pass


def install(root: logging.Logger | None = None) -> None:
    root = root or logging.getLogger()
    if not any(isinstance(h, ErrorWatchHandler) for h in root.handlers):
        root.addHandler(ErrorWatchHandler())


# ------------------------------------------------------------------ reading (the daily check) --


def counts_for(days: list[date], client=None) -> dict[date, dict[str, int]]:
    """{day: {kind: count}} for each day. Raises if Redis cannot be read (the check says so)."""
    if client is None:
        import redis

        from swing_trade_ml.core.config import settings

        client = redis.Redis.from_url(settings.REDIS_URL, socket_timeout=2, socket_connect_timeout=2)
    pipe = client.pipeline(transaction=False)
    for d in days:
        pipe.hgetall(day_key(d))
    out: dict[date, dict[str, int]] = {}
    for d, raw in zip(days, pipe.execute(), strict=True):
        out[d] = {(k.decode() if isinstance(k, bytes) else str(k)): int(v) for k, v in (raw or {}).items()}
    return out
