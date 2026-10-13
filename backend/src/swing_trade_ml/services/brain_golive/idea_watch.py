"""Silent-failure watch: the brain ran, but no idea reached the practice counter.

From 4 to 9 Oct 2026 the brain recorded no countable ideas and every health check stayed green,
because each check looked at a run, never at what the run produced. This looks at the end of the
chain: nightly runs finished in the last few trading days versus brain ideas that actually landed
in `compare.load` (placeable and risk-blocked both count, since both are scored practice evidence).

Read-only. A zero can be real (nothing qualified for several days in a row), so the message says
what to look at rather than claiming a bug.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.core.market_session import is_trading_day, previous_trading_day
from swing_trade_ml.db.models.brain import BrainRun
from swing_trade_ml.services.brain_golive import compare

IST = ZoneInfo("Asia/Kolkata")
WINDOW_TRADING_DAYS = 3


def window_start(today: date, n: int = WINDOW_TRADING_DAYS) -> date:
    """The first of the last `n` trading days, counting `today` when it is one."""
    day = today if is_trading_day(today) else previous_trading_day(today)
    for _ in range(n - 1):
        day = previous_trading_day(day)
    return day


def recent_counts(db: Session, today: date, n: int = WINDOW_TRADING_DAYS) -> dict:
    start = window_start(today, n)
    start_ts = datetime.combine(start, datetime.min.time(), tzinfo=IST)
    nightly = [
        t
        for (t,) in db.execute(
            select(BrainRun.as_of).where(
                BrainRun.kind == "nightly",
                BrainRun.status == "done",
                BrainRun.live.is_(True),
                BrainRun.as_of >= start_ts,
            )
        )
    ]
    nightly_days = {t.astimezone(IST).date() for t in nightly}
    rows, _ = compare.load(db, since=start)
    brain = [r for r in compare.one_per_day(rows) if r.is_brain and r.day >= start]
    return {
        "since": start,
        "nightly_days": len(nightly_days),
        "ideas": len(brain),
        "blocked": sum(r.blocked for r in brain),
    }


def check(db: Session, today: date, n: int = WINDOW_TRADING_DAYS) -> dict:
    """{name, ok, detail, level} like the weekly health checks."""
    c = recent_counts(db, today, n)
    name = "Counted ideas"
    if c["nightly_days"] == 0:
        return {
            "name": name,
            "ok": True,
            "detail": (
                f"No finished nightly brain run since {c['since']:%a %d %b}; the nightly check covers that."
            ),
            "level": "info",
        }
    if c["ideas"] == 0:
        return {
            "name": name,
            "ok": False,
            "detail": (
                f"The brain finished {c['nightly_days']} nightly run(s) since {c['since']:%a %d %b} "
                "but no idea reached the practice counter. Either nothing qualified, "
                "or something is stopping ideas from being recorded. "
                "Open the Why screen and the brain compare report."
            ),
            "level": "fail",
        }
    return {
        "name": name,
        "ok": True,
        "detail": (
            f"{c['ideas']} brain idea(s) recorded since {c['since']:%a %d %b} "
            f"({c['blocked']} blocked by limits)."
        ),
        "level": "ok",
    }
