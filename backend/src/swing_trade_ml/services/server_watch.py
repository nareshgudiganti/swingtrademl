"""Server watch: memory samples, an early warning, and a safe restart before the server runs out.

Why: on 2026-10-26 the 4 GB server ran out of memory twice (the API and the worker each grew to about
2 GB while idle, with no swap), which stalled the stop/target check and the holdings check. Nothing
showed it until the daily check at 16:20, after the fact. This keeps a record, warns early, and
restarts the one process that has grown too big at a safe moment, so the host never gets that far.

Housekeeping only: it reads memory figures and may restart this process. It never places, changes or
blocks an order, and it never touches the brain, sizing, stops or limits.

Both processes run it every five minutes: the worker through the scheduler (workers/jobs.py), the API
through a background task (main.py). Samples go to one Redis list the owner-only endpoint reads
(api/v1/endpoints/server_watch.py). A restart is a normal shutdown: Docker's `restart: unless-stopped`
starts the container again within seconds.
"""

from __future__ import annotations

import json
import os
import signal
import time
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.logging import get_logger

log = get_logger(__name__)

IST = ZoneInfo("Asia/Kolkata")

SAMPLES_KEY = "stml:server_samples"
WARNED_KEY = "stml:server_watch_warned"
MAX_SAMPLES = 2016  # a week at one sample every five minutes
SAMPLE_EVERY_SECONDS = 300
REDIS_TIMEOUT_SECONDS = 1.0

# Warn when less than this share of the server's memory is available (the daily check warns at 10%).
WARN_AVAILABLE = 0.12
WARN_COOLDOWN_SECONDS = 3600

# One process at about 2.0 to 2.1 GB is what the kernel killed on 2026-10-26.
RESTART_RSS_BYTES = int(1.7 * 1024**3)
CRITICAL_RSS_BYTES = int(1.95 * 1024**3)
# A fresh process is never restarted at once, so a low limit could not cause a restart loop.
MIN_UPTIME_SECONDS = 1800

PROC_STATUS = Path("/proc/self/status")
_started = time.monotonic()


# ------------------------------------------------------------------------------------ the figures --


def process_rss(path: Path = PROC_STATUS) -> int | None:
    """This process's resident memory in bytes, or None where there is no /proc (Windows, macOS)."""
    try:
        for line in path.read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def uptime_seconds() -> float:
    return time.monotonic() - _started


def _mb(kb: int | None) -> int | None:
    return None if kb is None else round(kb / 1024)


def take_sample(
    role: str,
    *,
    now: datetime | None = None,
    meminfo: dict[str, int] | None = None,
    rss: int | None = None,
    uptime: float | None = None,
) -> dict[str, Any]:
    """One reading. Memory figures are in MB. Inside the container /proc/meminfo is the host's, since no
    memory limit is set on the containers (see services/server_health.py)."""
    from swing_trade_ml.services import server_health

    info = meminfo if meminfo is not None else server_health.read_meminfo()
    info = info or {}
    rss = rss if rss is not None else process_rss()
    return {
        "ts": (now or datetime.now(UTC)).astimezone(UTC).isoformat(),
        "role": role,
        "rss_mb": None if rss is None else round(rss / 1024**2),
        "mem_total_mb": _mb(info.get("MemTotal")),
        "mem_available_mb": _mb(info.get("MemAvailable", info.get("MemFree"))),
        "swap_total_mb": _mb(info.get("SwapTotal")),
        "swap_free_mb": _mb(info.get("SwapFree")),
        "uptime_s": round(uptime if uptime is not None else uptime_seconds()),
    }


# ----------------------------------------------------------------------------------------- Redis --


def _redis_client():
    import redis

    return redis.Redis.from_url(
        settings.REDIS_URL,
        socket_timeout=REDIS_TIMEOUT_SECONDS,
        socket_connect_timeout=REDIS_TIMEOUT_SECONDS,
    )


def store_sample(sample: dict[str, Any], client_factory=_redis_client) -> bool:
    """Keep the newest MAX_SAMPLES. A Redis failure is logged and never reaches the caller."""
    try:
        client = client_factory()
        client.lpush(SAMPLES_KEY, json.dumps(sample))
        client.ltrim(SAMPLES_KEY, 0, MAX_SAMPLES - 1)
        return True
    except Exception as exc:  # noqa: BLE001 - monitoring must never break the job that calls it
        log.warning("server_watch.store_failed", error_kind=type(exc).__name__)
        return False


def read_samples(limit: int = 300, client_factory=_redis_client) -> list[dict[str, Any]]:
    """Newest first. Empty when Redis is down."""
    try:
        raw = client_factory().lrange(SAMPLES_KEY, 0, max(limit, 1) - 1)
        return [json.loads(r) for r in raw]
    except Exception as exc:  # noqa: BLE001
        log.warning("server_watch.read_failed", error_kind=type(exc).__name__)
        return []


def _first_warning(client_factory=_redis_client, cooldown: int = WARN_COOLDOWN_SECONDS) -> bool:
    """True once per cooldown: the first low-memory sample sends the message, the rest stay quiet."""
    try:
        return bool(client_factory().set(WARNED_KEY, "1", nx=True, ex=cooldown))
    except Exception:  # noqa: BLE001 - if Redis is down, one warning per sample is better than none
        return True


# ------------------------------------------------------------------------------------- decisions --


def low_memory_text(sample: dict[str, Any]) -> str | None:
    """The warning message, or None while memory is fine or unknown."""
    total, avail = sample.get("mem_total_mb"), sample.get("mem_available_mb")
    if not total or avail is None or avail / total >= WARN_AVAILABLE:
        return None
    swap_total, swap_free = sample.get("swap_total_mb") or 0, sample.get("swap_free_mb") or 0
    swap = f"Swap in use: {swap_total - swap_free} of {swap_total} MB." if swap_total else "There is no swap."
    return (
        "⚠️ <b>Server memory is low</b>\n\n"
        f"{avail} MB of {total} MB available ({avail / total:.0%}). {swap}\n"
        f"Seen by the {sample.get('role', '?')} (using {sample.get('rss_mb', '?')} MB). "
        "A process may be killed soon; the watcher restarts a process that grows too big."
    )


def _in_market_window(now_ist: datetime) -> bool:
    """Weekdays 09:00 to 16:30 IST: market hours and the nightly brain run. Nothing is restarted here."""
    if now_ist.weekday() >= 5:
        return False
    minutes = now_ist.hour * 60 + now_ist.minute
    return 9 * 60 <= minutes < 16 * 60 + 30


def restart_reason(
    role: str,
    rss: int | None,
    uptime: float,
    now_ist: datetime,
    *,
    job_running: bool = False,
) -> str | None:
    """Why this process should restart now, or None.

    Past the critical size it restarts at once: the kernel would kill it anyway, and a clean restart is
    better than being killed in the middle of a job. Past the normal limit the API restarts any time (it
    holds no state); the worker waits for a quiet moment: outside market hours and the nightly run, and
    with no job running.
    """
    if rss is None or uptime < MIN_UPTIME_SECONDS:
        return None
    gb = rss / 1024**3
    if rss >= CRITICAL_RSS_BYTES:
        return f"memory critical ({gb:.2f} GB)"
    if rss >= RESTART_RSS_BYTES:
        if role == "worker" and (_in_market_window(now_ist) or job_running):
            return None
        return f"memory high ({gb:.2f} GB)"
    return None


def _job_running() -> bool:
    """Any scheduled job running right now, from the job-run record. Unknown counts as not running."""
    try:
        from swing_trade_ml.workers import job_runs

        runs, available = job_runs.read_runs()
        return available and any(r.get("running_since") for jid, r in runs.items() if jid != "server_watch")
    except Exception:  # noqa: BLE001
        return False


def restart_self(reason: str) -> None:
    """A normal shutdown of this process (SIGTERM): uvicorn stops its scheduler cleanly, the container
    exits and Docker starts it again."""
    log.warning("server_watch.restarting", reason=reason)
    os.kill(os.getpid(), signal.SIGTERM)


# ---------------------------------------------------------------------------------- the one entry --


def run_watch(
    role: str,
    *,
    now: datetime | None = None,
    sample: dict[str, Any] | None = None,
    notify=None,
    kill=restart_self,
    client_factory=_redis_client,
) -> dict[str, Any]:
    """Take a sample, store it, warn if memory is low, restart this process if it grew too big.
    Returns what happened, for tests and logs."""
    sample = sample or take_sample(role, now=now)
    stored = store_sample(sample, client_factory)
    out: dict[str, Any] = {"sample": sample, "stored": stored, "warned": False, "restart": None}

    if notify is None:
        from swing_trade_ml.notifications import notifier

        notify = lambda text: notifier.send_sync(text, "system")  # noqa: E731

    text = low_memory_text(sample)
    if text and _first_warning(client_factory):
        try:
            notify(text)
            out["warned"] = True
        except Exception as exc:  # noqa: BLE001
            log.warning("server_watch.notify_failed", error_kind=type(exc).__name__)

    rss = None if sample.get("rss_mb") is None else sample["rss_mb"] * 1024**2
    now_ist = (now or datetime.now(UTC)).astimezone(IST)
    reason = restart_reason(
        role,
        rss,
        float(sample.get("uptime_s") or 0),
        now_ist,
        job_running=_job_running() if role == "worker" else False,
    )
    if reason:
        out["restart"] = reason
        with suppress(Exception):  # the restart goes ahead whether or not the message is sent
            notify(f"🔄 <b>Restarting the {role} to free memory</b>\n\n{reason}. Back in a few seconds.")
        kill(reason)
    return out


# ------------------------------------------------------------------------------------ for the API --


def summarize(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Per role: the latest reading, how fast the process has been growing since its last restart, and
    how many restarts show in the samples. `samples` is newest first."""
    roles: dict[str, list[dict[str, Any]]] = {}
    for s in reversed(samples):  # oldest first
        roles.setdefault(s.get("role", "?"), []).append(s)
    out: dict[str, Any] = {}
    for role, rows in roles.items():
        restarts, start = 0, 0
        for i in range(1, len(rows)):
            if (rows[i].get("uptime_s") or 0) < (rows[i - 1].get("uptime_s") or 0):
                restarts += 1
                start = i
        run = [r for r in rows[start:] if r.get("rss_mb") is not None]
        growth = None
        if len(run) >= 2 and run[-1]["uptime_s"] > run[0]["uptime_s"]:
            hours = (run[-1]["uptime_s"] - run[0]["uptime_s"]) / 3600
            growth = round((run[-1]["rss_mb"] - run[0]["rss_mb"]) / hours, 1) if hours else None
        out[role] = {"latest": rows[-1], "growth_mb_per_hour": growth, "restarts_in_window": restarts}
    return out
