"""Server checks for the daily check: new kinds of error (qa9), disk, memory and database size (qa11).

They sit in the brain daily check (services/brain_daily_check.py) so they land in the same stored
record (/brain/daily-checks) and the same Telegram message, with no new job. Reads and reports only.

What is measured on the droplet (docker-compose.yml): this code runs in the worker container. The
disk figure is for the folder holding the trained models (MODEL_ARTIFACT_DIR, the `model_data` named
volume). Docker keeps named volumes - `postgres_data` too - under /var/lib/docker on the host's own
disk, so on the single-disk droplet this is the disk Postgres writes to; a full one stops Postgres.
/proc/meminfo inside a container without a memory limit (none is set) shows the host's memory.
On Windows there is no /proc/meminfo and the memory check is skipped.
"""

from __future__ import annotations

import shutil
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.orm import Session

DISK_WARN_USED = 0.80
DISK_BAD_USED = 0.90
MEMORY_WARN_AVAILABLE = 0.10
HISTORY_DAYS = 14  # a kind seen in these days before the window is "known"
MAX_WINDOW_DAYS = 10  # a long gap between checks is still read in full, up to this
MEMINFO = Path("/proc/meminfo")


def _check(name: str, ok: bool, detail: str, level: str | None = None) -> dict:
    from swing_trade_ml.services import brain_weekly_health as weekly

    return weekly._check(name, ok, detail, level)


def _gb(n: float) -> str:
    return f"{n / 1024**3:.1f} GB"


# ---------------------------------------------------------------------------------------- disk --


def disk_path() -> str:
    from swing_trade_ml.core.config import settings

    p = Path(settings.MODEL_ARTIFACT_DIR)
    return str(p if p.exists() else Path(p.resolve().anchor or "/"))


def check_disk(usage=None, path: str | None = None) -> dict:
    """WARN above 80% used, BAD (fail) above 90%: Postgres stops when the disk is full."""
    path = path or disk_path()
    total, used, free = usage if usage is not None else shutil.disk_usage(path)
    share = used / total if total else 1.0
    detail = f"{share:.0%} used ({_gb(free)} free of {_gb(total)})."
    name = "Server disk"
    if share > DISK_BAD_USED:
        return _check(name, False, f"{detail} Nearly full: Postgres stops when it fills. Free space now.")
    if share > DISK_WARN_USED:
        return _check(name, False, f"{detail} Getting full; free space soon.", "warn")
    return _check(name, True, detail)


# -------------------------------------------------------------------------------------- memory --


def read_meminfo(path: Path = MEMINFO) -> dict[str, int] | None:
    """{field: kB} from /proc/meminfo, or None where there is none (Windows, macOS)."""
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return None
    out: dict[str, int] = {}
    for line in lines:
        key, _, rest = line.partition(":")
        bits = rest.split()
        if bits and bits[0].isdigit():
            out[key.strip()] = int(bits[0])
    return out


def check_memory(meminfo: dict[str, int] | None) -> dict | None:
    """WARN when less than 10% of memory is available. None (skipped) without /proc/meminfo."""
    if not meminfo or not meminfo.get("MemTotal"):
        return None
    total = meminfo["MemTotal"]
    available = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
    share = available / total
    detail = f"{share:.0%} of memory available ({_gb(available * 1024)} of {_gb(total * 1024)})."
    if share < MEMORY_WARN_AVAILABLE:
        return _check(
            "Server memory", False, f"{detail} Very low; the server may start killing processes.", "warn"
        )
    return _check("Server memory", True, detail)


# ------------------------------------------------------------------------------- database size --


def check_database_size(db: Session) -> dict:
    size = db.execute(text("SELECT pg_database_size(current_database())")).scalar_one()
    return _check("Database size", True, f"The database uses {_gb(size)}.", "info")


# --------------------------------------------------------------------------- new kinds of error --


def error_window(db: Session, day: date) -> list[date]:
    """The error days this check covers: every day after the previous stored check, up to `day`.
    So the Monday check also reads Saturday's and Sunday's errors, and a rerun reads the same days."""
    from swing_trade_ml.db.models.brain import BrainDailyCheck

    prev = db.execute(
        select(BrainDailyCheck.day)
        .where(BrainDailyCheck.day < day)
        .order_by(BrainDailyCheck.day.desc())
        .limit(1)
    ).scalar_one_or_none()
    start = max(prev + timedelta(days=1), day - timedelta(days=MAX_WINDOW_DAYS - 1)) if prev else day
    return [start + timedelta(days=i) for i in range((day - start).days + 1)]


def new_error_kinds(counts: dict[date, dict[str, int]], window: list[date]) -> dict[str, int]:
    """Kinds seen in the window but in none of the days before it, with how often they came."""
    known: set[str] = set()
    for d, kinds in counts.items():
        if d not in window:
            known |= set(kinds)
    seen: dict[str, int] = {}
    for d in window:
        for kind, n in (counts.get(d) or {}).items():
            seen[kind] = seen.get(kind, 0) + n
    return {k: n for k, n in sorted(seen.items()) if k not in known}


def check_errors(db: Session, day: date, client=None) -> list[dict] | None:
    """An info line with the error count, plus one WARN per new kind (so each one reaches Telegram
    as "New kind of error: ... (n times)"). None when the error watch is switched off."""
    from swing_trade_ml.core import error_watch
    from swing_trade_ml.core.config import settings

    if not settings.ERROR_WATCH_ENABLED:
        return None
    window = error_window(db, day)
    history = [window[0] - timedelta(days=i) for i in range(HISTORY_DAYS, 0, -1)]
    try:
        counts = error_watch.counts_for(history + window, client)
    except Exception as exc:  # noqa: BLE001
        why = f"Could not read the error counts from Redis ({exc.__class__.__name__}); new errors go unseen."
        return [_check("Errors logged", False, why, "warn")]
    total = sum(sum((counts.get(d) or {}).values()) for d in window)
    kinds = len({k for d in window for k in (counts.get(d) or {})})
    span = (
        window[0].isoformat() if len(window) == 1 else f"{window[0].isoformat()} to {window[-1].isoformat()}"
    )
    out = [_check("Errors logged", True, f"{total} error(s) of {kinds} kind(s) for {span}.", "info")]
    for kind, n in new_error_kinds(counts, window).items():
        out.append(_check("New kind of error", False, f"{kind} ({n} times)", "warn"))
    return out


def checks(db: Session, day: date) -> list[dict]:
    """Every server check; a part that fails is a failed check, never an exception."""
    out: list[dict] = []
    parts = (
        ("Errors logged", lambda: check_errors(db, day)),
        ("Server disk", lambda: check_disk()),
        ("Server memory", lambda: check_memory(read_meminfo())),
        ("Database size", lambda: check_database_size(db)),
    )
    for label, fn in parts:
        try:
            found = fn()
        except Exception as exc:  # noqa: BLE001 - one bad part must not hide the rest
            found = _check(label, False, f"Could not check ({exc.__class__.__name__}).", "warn")
        if isinstance(found, list):
            out.extend(found)
        elif found is not None:
            out.append(found)
    return out
