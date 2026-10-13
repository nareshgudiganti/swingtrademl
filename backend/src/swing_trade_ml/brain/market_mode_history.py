"""The market mode (NORMAL / DEFENSIVE / NO_NEW_TRADES) the brain really reported on each day.

Every finished live nightly run already stores its banner (`brain_runs.banner_mode`), so history
accumulates without a new job. This reads it back, one mode per IST day, for replays that would
otherwise assume NORMAL every day. Days with no recorded run are simply absent: callers must
say how many days were covered rather than fill the gaps.

Read-only evidence helper; no module depends on it.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.brain import contracts as c
from swing_trade_ml.db.models.brain import BrainRun

IST = ZoneInfo("Asia/Kolkata")
VALID = {m.value for m in c.MarketMode}


def mode_history(db: Session) -> dict[date, str]:
    """Day of the run (IST) -> mode, from the newest finished live nightly run of that day."""
    rows = db.execute(
        select(BrainRun.as_of, BrainRun.started_at, BrainRun.banner_mode).where(
            BrainRun.kind == "nightly",
            BrainRun.status == "done",
            BrainRun.live.is_(True),
            BrainRun.banner_mode.isnot(None),
        )
    ).all()
    newest: dict[date, tuple] = {}
    for as_of, started, mode in rows:
        if mode not in VALID:
            continue
        day = as_of.astimezone(IST).date()
        if day not in newest or started > newest[day][0]:
            newest[day] = (started, mode)
    return {d: m for d, (_, m) in newest.items()}


def coverage(modes: dict[date, str], days: Iterable[date]) -> tuple[int, int]:
    """(days with a recorded mode, days asked about)."""
    days = list(days)
    return sum(d in modes for d in days), len(days)
