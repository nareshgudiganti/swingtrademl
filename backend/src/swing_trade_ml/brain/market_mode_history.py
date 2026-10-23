"""The market mode (NORMAL / DEFENSIVE / NO_NEW_TRADES) the brain really reported on each day.

Every finished live nightly run already stores its banner (`brain_runs.banner_mode`), so history
accumulates without a new job. This reads it back, one mode per IST day, for replays that would
otherwise assume NORMAL every day. Days with no recorded run are simply absent: callers must
say how many days were covered rather than fill the gaps.

Days before banners were recorded (or with no finished run) can be filled by `history_for`, which
derives the mode M10 would have given from the data stored up to the end of that IST day (a replay
`DatedReader`, so no look-ahead). Every day says which it is: "recorded" or "derived". Limits of a
derived day (`DERIVED_LIMITS`): it is M10's mode only, so a live run's extra caution from situation
recognition (M04 can turn NORMAL into DEFENSIVE) is not in it; breadth is measured over today's
watchlist; data corrected after that day is read as corrected. A day that cannot be derived is left
out, never guessed.

Read-only evidence helper; no module depends on it. Nothing is stored: no new table, no new job.
Run (backend/): python -m swing_trade_ml.brain.market_mode_history --from 2026-07-01 --to 2026-10-21
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.modules.m10_market.judge import inputs_from, judge
from swing_trade_ml.brain.reader import DatedReader
from swing_trade_ml.db.models.brain import BrainRun

IST = ZoneInfo("Asia/Kolkata")
VALID = {m.value for m in c.MarketMode}
SOURCES = ("recorded", "derived")
DERIVED_LIMITS = (
    "A derived day is the market brain's (M10) mode only: a live run can also be made more careful by "
    "situation recognition (M04, NORMAL to DEFENSIVE), so a derived NORMAL may have been DEFENSIVE live.",
    "Derived breadth is measured over today's watchlist (survivor bias), and data corrected after the "
    "day is read as corrected.",
)


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


def _end_of_ist_day(day: date) -> datetime:
    """The same as_of a replay of `day` uses (replay_week.as_of_end_of_ist_day)."""
    return datetime.combine(day, time(23, 59), tzinfo=IST).astimezone(UTC)


def derived_mode(db: Session, day: date) -> str | None:
    """The mode M10 gives from the data stored up to the end of `day` (IST), or None when it cannot be
    worked out. Read-only: a replay reader (live=False), and the v1 context cache is not refreshed."""
    reader = DatedReader(db, as_of=_end_of_ist_day(day), live=False)
    try:
        mode = judge(inputs_from(reader)).mode
    except Exception:  # noqa: BLE001 - an unknown day is reported as missing, never filled with a guess
        return None
    return mode.value if mode is not None else None


def history_for(db: Session, days: Iterable[date], *, derive: bool = True) -> dict[date, tuple[str, str]]:
    """Day -> (mode, source) for each of `days`. A recorded banner always wins; otherwise, with
    `derive`, the point-in-time M10 mode. Days with neither are absent."""
    recorded = mode_history(db)
    out: dict[date, tuple[str, str]] = {}
    for day in days:
        if day in recorded:
            out[day] = (recorded[day], "recorded")
        elif derive:
            mode = derived_mode(db, day)
            if mode in VALID:
                out[day] = (mode, "derived")
    return out


def modes_only(history: dict[date, tuple[str, str]]) -> dict[date, str]:
    """The plain day -> mode map `portfolio_sim.simulate` takes."""
    return {d: m for d, (m, _) in history.items()}


def source_counts(history: dict[date, tuple[str, str]], days: Iterable[date]) -> dict[str, int]:
    days = list(days)
    out = {s: sum(1 for d in days if d in history and history[d][1] == s) for s in SOURCES}
    out["missing"] = sum(1 for d in days if d not in history)
    return out


def trading_days(start: date, end: date) -> list[date]:
    from swing_trade_ml.core.market_session import is_trading_day

    n = (end - start).days
    return [start + timedelta(days=i) for i in range(n + 1) if is_trading_day(start + timedelta(days=i))]


def _session():
    from swing_trade_ml.db.session import SessionLocal

    return SessionLocal()


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Market mode per past trading day (read-only)")
    p.add_argument("--from", dest="start", required=True)
    p.add_argument("--to", dest="end", required=True)
    p.add_argument("--recorded-only", action="store_true", help="do not derive days without a banner")
    a = p.parse_args(argv)
    days = trading_days(date.fromisoformat(a.start), date.fromisoformat(a.end))
    with _session() as db:
        history = history_for(db, days, derive=not a.recorded_only)
    for d in days:
        mode, source = history.get(d, ("-", "missing"))
        print(f"{d.isoformat()}  {mode}  {source}")
    n = source_counts(history, days)
    print(
        f"{len(days)} trading days: {n['recorded']} recorded, {n['derived']} derived, {n['missing']} missing."
    )
    if n["derived"]:
        for line in DERIVED_LIMITS:
            print(f"- {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
