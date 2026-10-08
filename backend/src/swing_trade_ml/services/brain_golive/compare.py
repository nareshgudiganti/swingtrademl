"""M18: the brain strategy vs version 1 on the same days, from Signal outcomes
(scored by ml/predict.py::evaluate_pending_signals — the same scorer for both).
Pure functions on `Row`s plus one loader."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from swing_trade_ml.core.enums import SignalType
from swing_trade_ml.core.strategy_policy import STAGED_TYPES
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Signal, Strategy
from swing_trade_ml.strategies.brain import IST, ist_day_bounds

TARGET = "TARGET_HIT"
STOP = "STOP_LOSS_HIT"
NEEDED_FINISHED = 30
MIN_FINISHED_TO_COMPARE = 10
# Practice ideas that version 1's risk limits (market-stress cap, slots, cash...) refused are still
# recorded and scored, tagged in Signal.features (execution.BLOCKED_BY_RISK_KEY). They are counted
# SEPARATELY and, conservatively, do NOT count toward the 30-idea gate: only ideas that could really
# have been placed do. Flip this one switch (owner's call) to count them toward the gate as well.
COUNT_BLOCKED_TOWARD_GATE = False
BLOCKED_KEY = "blocked_by_risk_limit"  # == services.execution.BLOCKED_BY_RISK_KEY (not imported: cycle)
EXCLUDED_TYPES = ("long_term_value",)  # a one-year horizon is not comparable


@dataclass(frozen=True, slots=True)
class Row:
    strategy: str
    is_brain: bool
    symbol: str
    day: date
    generated_at: datetime
    outcome: str | None
    outcome_pct: float | None
    blocked: bool = False  # brain idea refused by a v1 risk limit (practice evidence only)


def one_per_day(rows: list[Row]) -> list[Row]:
    latest: dict[tuple[str, str, date], Row] = {}
    for r in rows:
        key = (r.strategy, r.symbol, r.day)
        if key not in latest or r.generated_at > latest[key].generated_at:
            latest[key] = r
    return sorted(latest.values(), key=lambda r: (r.day, r.strategy, r.symbol))


def summarise(rows: list[Row]) -> dict:
    finished = [r for r in rows if r.outcome is not None]
    n = len(finished)
    pcts = [r.outcome_pct for r in finished if r.outcome_pct is not None]
    return {
        "ideas": len(rows),
        "finished": n,
        "hit_rate": sum(r.outcome == TARGET for r in finished) / n if n else None,
        "stopped": sum(r.outcome == STOP for r in finished) / n if n else None,
        "avg_outcome_pct": sum(pcts) / len(pcts) if pcts else None,
    }


def _week(day: date) -> str:
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def _note(n_days: int, brain: dict, v1: dict, min_finished: int) -> str:
    if n_days == 0:
        return (
            "The brain strategy has not run yet. Once it runs after the nightly brain run, "
            "its ideas appear here and are scored as they finish."
        )
    if brain["finished"] < min_finished or v1["finished"] < min_finished:
        return (
            f"Only {brain['finished']} of the brain's ideas and {v1['finished']} of version 1's have "
            "finished on the same days — too few to compare yet."
        )
    days = f"{n_days} day" + ("s" if n_days != 1 else "")
    return (
        f"On the same {days}, the brain's ideas reached their target {brain['hit_rate']:.0%} of the time "
        f"(average result {brain['avg_outcome_pct'] or 0.0:+.1%}); "
        f"version 1's reached it {v1['hit_rate']:.0%} of the time "
        f"(average {v1['avg_outcome_pct'] or 0.0:+.1%})."
    )


def compare(rows: list[Row], brain_days: set[date], min_finished: int = MIN_FINISHED_TO_COMPARE) -> dict:
    rows = [r for r in one_per_day(rows) if r.day in brain_days]
    brain = [r for r in rows if r.is_brain and not r.blocked]
    blocked = [r for r in rows if r.is_brain and r.blocked]
    v1 = [r for r in rows if not r.is_brain]
    names = sorted({r.strategy for r in brain}) + sorted({r.strategy for r in v1})
    brain_names = {r.strategy for r in brain}
    days = sorted(brain_days)
    b, v = summarise(brain), summarise(v1)
    return {
        "days": len(days),
        "first_day": days[0].isoformat() if days else None,
        "last_day": days[-1].isoformat() if days else None,
        "strategies": [
            {"name": n, "is_brain": n in brain_names, **summarise([r for r in rows if r.strategy == n])}
            for n in names
        ],
        "brain": b,
        "brain_blocked": summarise(blocked),
        "version1": v,
        "by_week": [
            {
                "week": w,
                "brain": summarise([r for r in brain if _week(r.day) == w]),
                "version1": summarise([r for r in v1 if _week(r.day) == w]),
            }
            for w in sorted({_week(r.day) for r in rows})
        ],
        "note": _note(len(days), b, v, min_finished),
    }


def load(db: Session, since: date | None = None) -> tuple[list[Row], set[date]]:
    staged = sorted(STAGED_TYPES)
    stmt = (
        select(
            Signal.generated_at,
            Signal.outcome,
            Signal.outcome_pct,
            Signal.features,
            Strategy.name,
            Strategy.strategy_type,
            Instrument.tradingsymbol,
        )
        .join(Strategy, Strategy.id == Signal.strategy_id)
        .join(Instrument, Instrument.id == Signal.instrument_id)
        .where(
            Signal.signal_type == SignalType.BUY,
            Signal.stop_loss.isnot(None),
            Signal.take_profit.isnot(None),
            Strategy.strategy_type.not_in(EXCLUDED_TYPES),
        )
    )
    ist_date = func.date(func.timezone("Asia/Kolkata", Signal.generated_at))
    days_stmt = (
        select(distinct(ist_date))
        .join(Strategy, Strategy.id == Signal.strategy_id)
        .where(Strategy.strategy_type.in_(staged))
    )
    if since is not None:
        start = ist_day_bounds(since)[0]
        stmt = stmt.where(Signal.generated_at >= start)
        days_stmt = days_stmt.where(Signal.generated_at >= start)
    rows = [
        Row(
            strategy=name,
            is_brain=stype in STAGED_TYPES,
            symbol=symbol,
            day=generated.astimezone(IST).date(),
            generated_at=generated,
            outcome=outcome,
            outcome_pct=pct,
            blocked=bool(stype in STAGED_TYPES and isinstance(features, dict) and features.get(BLOCKED_KEY)),
        )
        for generated, outcome, pct, features, name, stype, symbol in db.execute(stmt)
    ]
    return rows, {d for (d,) in db.execute(days_stmt)}


def _finished_brain(db: Session, blocked: bool) -> int:
    rows, _ = load(db)
    return sum(
        1 for r in one_per_day(rows) if r.is_brain and r.outcome is not None and r.blocked == blocked
    )


def finished_placeable_brain_ideas(db: Session) -> int:
    """Finished brain ideas that could really have been placed (not blocked by a risk limit)."""
    return _finished_brain(db, False)


def finished_blocked_brain_ideas(db: Session) -> int:
    """Finished practice ideas that a v1 risk limit blocked (shown separately)."""
    return _finished_brain(db, True)


def finished_brain_ideas(db: Session) -> int:
    """The number the go-live gate uses (see COUNT_BLOCKED_TOWARD_GATE)."""
    n = finished_placeable_brain_ideas(db)
    return n + finished_blocked_brain_ideas(db) if COUNT_BLOCKED_TOWARD_GATE else n


def report(db: Session, since: date | None = None) -> dict:
    rows, days = load(db, since)
    return {**compare(rows, days), "brain_finished": finished_brain_ideas(db),
        "brain_finished_placeable": finished_placeable_brain_ideas(db),
        "brain_finished_blocked": finished_blocked_brain_ideas(db),
        "needed": NEEDED_FINISHED}
