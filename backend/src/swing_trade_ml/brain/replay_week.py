"""Historical nightly replays over a range of IST trading days (Phase 1 gate)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from swing_trade_ml.brain import queue as brain_queue
from swing_trade_ml.brain import service
from swing_trade_ml.core.holidays import is_trading_holiday
from swing_trade_ml.core.market_session import last_closed_trading_day, previous_trading_day
from swing_trade_ml.db.models.brain import BrainRun

IST = ZoneInfo("Asia/Kolkata")


def is_ist_trading_day(d: date) -> bool:
    return d.weekday() < 5 and not is_trading_holiday(d)


def iter_ist_trading_days(start: date, end: date):
    """Inclusive range, chronological."""
    if start > end:
        raise ValueError(f"start {start} is after end {end}")
    d = start
    while d <= end:
        if is_ist_trading_day(d):
            yield d
        d += timedelta(days=1)


def as_of_end_of_ist_day(day: date) -> datetime:
    return datetime.combine(day, time(23, 59), tzinfo=IST).astimezone(UTC)


def resolve_replay_range(
    *,
    from_day: date | None,
    to_day: date | None,
    days: int | None,
    now: datetime | None = None,
) -> tuple[date, date]:
    """Pick an inclusive IST date range from --from/--to or --days."""
    if days is not None and (from_day is not None or to_day is not None):
        raise ValueError("Use either --days or --from/--to, not both.")
    if days is not None:
        if days < 1:
            raise ValueError("--days must be at least 1")
        end = last_closed_trading_day(now or datetime.now(UTC))
        start = end
        remaining = days - 1
        while remaining:
            start = previous_trading_day(start)
            remaining -= 1
        return start, end
    if from_day is None or to_day is None:
        raise ValueError("Provide --from and --to, or --days.")
    return from_day, to_day


@dataclass(frozen=True)
class ReplayDayResult:
    day: date
    run_id: str
    banner: str
    counts: dict[str, int]
    universe_size: int


def _counts_from_run(db: Session, run_id: str, ctx_counts: Counter[str] | None = None) -> dict[str, int]:
    if ctx_counts is not None:
        return dict(ctx_counts)
    from swing_trade_ml.brain import service as brain_service

    return dict(Counter(d.word for d in brain_service.decisions_for(db, run_id)))


def run_replay_week(
    db: Session,
    *,
    start: date,
    end: date,
    book: str = "paper",
    kind: str = "nightly",
    symbols: list[str] | None = None,
    wait_seconds: float = 0,
) -> list[ReplayDayResult]:
    """Replay each IST trading day in [start, end]. Raises RunBusyError if the lock is held."""
    results: list[ReplayDayResult] = []
    with brain_queue.run_lock(kind, book, wait_seconds=wait_seconds):
        for day in iter_ist_trading_days(start, end):
            as_of = as_of_end_of_ist_day(day)
            ctx, run_id = service.run_brain(db, kind=kind, as_of=as_of, symbols=symbols, book=book)
            run = db.get(BrainRun, run_id)
            banner = (run.banner_mode if run else None) or ctx.banner.mode.value
            decisions = ctx.decisions.values() if hasattr(ctx.decisions, "values") else ctx.decisions
            counts = _counts_from_run(db, run_id, Counter(d.word for d in decisions))
            universe_size = len(ctx.request.universe)
            results.append(
                ReplayDayResult(
                    day=day,
                    run_id=run_id,
                    banner=banner,
                    counts=counts,
                    universe_size=universe_size,
                )
            )
    return results


def format_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "—"
    order = ("TRADE", "WATCH", "WAIT", "AVOID", "HOLD", "MONITOR", "REDUCE", "EXIT")
    parts = [f"{w}={counts[w]}" for w in order if counts.get(w)]
    for w in sorted(counts):
        if w not in order:
            parts.append(f"{w}={counts[w]}")
    return " ".join(parts)
