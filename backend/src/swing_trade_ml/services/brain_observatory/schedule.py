"""Which brain runs were due on a day (R7): trading days only, and only after their deadline.

Times mirror workers/scheduler.py (nightly 15:50 IST; intraday every 15 minutes 09:00-15:45), checked by a
test. The nightly deadline is 16:20 IST, when the daily check runs. Holidays come from the listed NSE
holidays (core/market_session.is_trading_day); an unlisted closure would show as Not observed.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from swing_trade_ml.core.market_session import is_trading_day

IST = ZoneInfo("Asia/Kolkata")
__all__ = [
    "INTRADAY_SLOTS",
    "IST",
    "UTC",
    "day_window",
    "intraday_expectation",
    "is_trading_day",
    "nightly_expectation",
    "nightly_state",
    "run_day",
]
NIGHTLY_AT = time(15, 50)
NIGHTLY_DUE_BY = time(16, 20)
INTRADAY_SLOTS = tuple(time(h, m) for h in range(9, 16) for m in (0, 15, 30, 45))
INTRADAY_GRACE = timedelta(minutes=10)


def run_day(as_of: datetime) -> date:
    return as_of.astimezone(IST).date()


def day_window(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time(0), tzinfo=IST)
    return start, start + timedelta(days=1)


def nightly_expectation(day: date, now: datetime) -> str:
    if not is_trading_day(day):
        return "not_applicable"
    return "due" if now >= datetime.combine(day, NIGHTLY_DUE_BY, tzinfo=IST) else "not_due"


def intraday_expectation(day: date, now: datetime) -> dict:
    if not is_trading_day(day):
        return {"not_applicable": True}
    due = sum(1 for t in INTRADAY_SLOTS if now >= datetime.combine(day, t, tzinfo=IST) + INTRADAY_GRACE)
    return {"slots": len(INTRADAY_SLOTS), "due": due, "not_due": len(INTRADAY_SLOTS) - due}


def nightly_state(day: date, now: datetime, runs: list[dict]) -> dict:
    """The day's live nightly run, from all of that day's runs (never one results page).

    Only a `done` run counts as having run. Exactly one done run is the day's nightly even if a failed or
    queued rerun sits beside it; two done runs are a real conflict. With no done run, a queued or running
    run is 'in_progress' and a failed one is 'failed'; neither is ever shown as having run."""
    expectation = nightly_expectation(day, now)
    live = [r for r in runs if r["kind"] == "nightly" and r["live"] and r["status"] != "superseded"]
    done = [r for r in live if r["status"] == "done"]
    if len(done) > 1:
        return {"state": "conflicting", "run_ids": [r["id"] for r in done], "expectation": expectation}
    if done:
        return {"state": "observed", "run_id": done[0]["id"], "expectation": expectation}
    unfinished = [r for r in live if r["status"] in ("queued", "running")]
    if unfinished:
        return {"state": "in_progress", "run_ids": [r["id"] for r in unfinished], "expectation": expectation}
    failed = [r for r in live if r["status"] == "failed"]
    if failed:
        return {"state": "failed", "run_ids": [r["id"] for r in failed], "expectation": expectation}
    if expectation == "due":
        return {"state": "not_observed", "expectation": expectation}
    return {"state": expectation, "expectation": expectation}
