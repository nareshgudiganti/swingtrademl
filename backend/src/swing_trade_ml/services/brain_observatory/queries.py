"""Every database read the Observatory makes. Each function issues one bounded statement (two for
`nightly_sessions`); nothing writes. Books, modes and categories are never summed here.
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
from sqlalchemy import func, literal, select, tuple_
from sqlalchemy.orm import Session

from swing_trade_ml.db.models.brain import (
    BrainAlert,
    BrainDecision,
    BrainLearningRun,
    BrainProposal,
    BrainRun,
    BrainTrack,
    FeatureSnapshot,
)
from swing_trade_ml.db.models.brain_golive import BrainStageChange
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.trading import Order, Signal, Strategy
from swing_trade_ml.services.brain_observatory.schedule import day_window, run_day

PAGE_MAX = 500
BAR_COLUMNS = ["day", "open", "high", "low", "close"]  # the shape of replay_score.load_bars


def _range(start: date, end: date) -> tuple[datetime, datetime]:
    lo, _ = day_window(start)
    _, hi = day_window(end)
    return lo, hi


# --- runs -------------------------------------------------------------------------------------------


def runs_between(db: Session, start: date, end: date) -> list:
    """Every run in the range, brief columns, no LIMIT (the range is at most 92 days)."""
    lo, hi = _range(start, end)
    return list(
        db.execute(
            select(
                BrainRun.id,
                BrainRun.kind,
                BrainRun.live,
                BrainRun.status,
                BrainRun.as_of,
                BrainRun.started_at,
            )
            .where(BrainRun.as_of >= lo, BrainRun.as_of < hi)
            .order_by(BrainRun.started_at, BrainRun.id)
        ).all()
    )


def runs_on(db: Session, day: date, after: tuple[datetime, str] | None, limit: int) -> list[BrainRun]:
    lo, hi = day_window(day)
    q = select(BrainRun).where(BrainRun.as_of >= lo, BrainRun.as_of < hi)
    if after is not None:
        q = q.where(tuple_(BrainRun.started_at, BrainRun.id) > tuple_(literal(after[0]), literal(after[1])))
    return list(db.scalars(q.order_by(BrainRun.started_at, BrainRun.id).limit(limit + 1)))


def nightly_runs_on(db: Session, day: date) -> list[dict]:
    """Every nightly run of the day (brief columns), so the day's nightly status never depends on a page."""
    lo, hi = day_window(day)
    rows = db.execute(
        select(BrainRun.id, BrainRun.kind, BrainRun.live, BrainRun.status).where(
            BrainRun.kind == "nightly", BrainRun.as_of >= lo, BrainRun.as_of < hi
        )
    ).all()
    return [{"id": r.id, "kind": r.kind, "live": r.live, "status": r.status} for r in rows]


def run(db: Session, run_id: str) -> BrainRun | None:
    return db.get(BrainRun, run_id)


def word_rows(db: Session, run_ids: list[str]) -> list[tuple[str, str, str, int]]:
    if not run_ids:
        return []
    return list(
        db.execute(
            select(BrainDecision.run_id, BrainDecision.kind, BrainDecision.word, func.count())
            .where(BrainDecision.run_id.in_(run_ids))
            .group_by(BrainDecision.run_id, BrainDecision.kind, BrainDecision.word)
        ).all()
    )


# --- decisions --------------------------------------------------------------------------------------


def decisions(
    db: Session, run_id: str, after_id: int | None, limit: int, symbol: str | None
) -> list[BrainDecision]:
    q = select(BrainDecision).where(BrainDecision.run_id == run_id)
    if after_id is not None:
        q = q.where(BrainDecision.id > after_id)
    if symbol:
        q = q.where(BrainDecision.symbol == symbol.strip().upper())
    return list(db.scalars(q.order_by(BrainDecision.id).limit(limit + 1)))


def decision(db: Session, decision_id: int) -> BrainDecision | None:
    return db.get(BrainDecision, decision_id)


def snapshot_for_run(db: Session, run_id: str, symbol: str) -> FeatureSnapshot | None:
    return db.scalars(
        select(FeatureSnapshot)
        .where(FeatureSnapshot.run_id == run_id, FeatureSnapshot.symbol == symbol)
        .limit(1)
    ).first()


def instruments(db: Session, symbol: str) -> list[Instrument]:
    return list(db.scalars(select(Instrument).where(Instrument.tradingsymbol == symbol).limit(10)))


def track_rows(db: Session, symbol: str, day: date, book: str) -> list[BrainTrack]:
    return list(
        db.scalars(
            select(BrainTrack)
            .where(BrainTrack.symbol == symbol, BrainTrack.day == day, BrainTrack.book == book)
            .limit(10)
        )
    )


def alerts_sent(db: Session, run_id: str) -> int:
    return db.scalar(select(func.count()).select_from(BrainAlert).where(BrainAlert.run_id == run_id)) or 0


# --- day aggregates (GROUP BY; books and modes kept apart) -----------------------------------------


def tracked_by_day(db: Session, start: date, end: date) -> dict[date, dict[str, int]]:
    rows = db.execute(
        select(BrainTrack.day, BrainTrack.book, func.count())
        .where(BrainTrack.day >= start, BrainTrack.day <= end)
        .group_by(BrainTrack.day, BrainTrack.book)
    ).all()
    out: dict[date, dict[str, int]] = {}
    for day, book, n in rows:
        out.setdefault(day, {})[book] = n
    return out


def _brain_by_day_and_mode(db: Session, model, ts_col, start: date, end: date) -> dict[date, dict[str, int]]:
    lo, hi = _range(start, end)
    day = func.date(func.timezone("Asia/Kolkata", ts_col))
    rows = db.execute(
        select(day, model.mode, func.count())
        .join(Strategy, Strategy.id == model.strategy_id)
        .where(Strategy.strategy_type == "brain", ts_col >= lo, ts_col < hi)
        .group_by(day, model.mode)
    ).all()
    out: dict[date, dict[str, int]] = {}
    for d, mode, n in rows:
        out.setdefault(d, {})[str(mode)] = n
    return out


def brain_signals_by_day(db: Session, start: date, end: date) -> dict[date, dict[str, int]]:
    return _brain_by_day_and_mode(db, Signal, Signal.generated_at, start, end)


def brain_orders_by_day(db: Session, start: date, end: date) -> dict[date, dict[str, int]]:
    return _brain_by_day_and_mode(db, Order, Order.placed_at, start, end)


def stage_on(db: Session, day: date) -> str | None:
    _, hi = day_window(day)
    return db.scalar(
        select(BrainStageChange.stage)
        .where(BrainStageChange.changed_at < hi)
        .order_by(BrainStageChange.changed_at.desc())
        .limit(1)
    )


def stage_history(db: Session) -> list[tuple[datetime, str]]:
    return [
        (r.changed_at, r.stage)
        for r in db.execute(
            select(BrainStageChange.changed_at, BrainStageChange.stage).order_by(BrainStageChange.changed_at)
        )
    ]


# --- learning and outcomes --------------------------------------------------------------------------


def learning_summary(db: Session, start: date, end: date, book: str) -> dict:
    """Results collected = graded ideas from LIVE, finished nightly runs of one book (never a replay or
    another book); changes proposed and learning checks are the learning loop's own records."""
    lo, hi = _range(start, end)
    graded = (
        db.scalar(
            select(func.count())
            .select_from(BrainDecision)
            .join(BrainRun, BrainRun.id == BrainDecision.run_id)
            .where(
                BrainDecision.resolved_on >= start,
                BrainDecision.resolved_on <= end,
                BrainDecision.outcome.is_not(None),
                BrainDecision.outcome != "noscore",
                BrainRun.live.is_(True),
                BrainRun.status == "done",
                BrainRun.book == book,
            )
        )
        or 0
    )
    proposals = dict(
        db.execute(
            select(BrainProposal.status, func.count())
            .where(BrainProposal.created_at >= lo, BrainProposal.created_at < hi)
            .group_by(BrainProposal.status)
        ).all()
    )
    learning_runs = (
        db.scalar(
            select(func.count())
            .select_from(BrainLearningRun)
            .where(BrainLearningRun.created_at >= lo, BrainLearningRun.created_at < hi)
        )
        or 0
    )
    return {
        "results_collected": graded,
        "results_collected_label": f"graded ideas from live runs of the {book} book",
        "changes_proposed": proposals,
        "learning_checks": learning_runs,
    }


def stored_grade_rows(
    db: Session, start: date, end: date, live: bool
) -> list[tuple[str, float | None, datetime, str, str]]:
    """Graded ideas of finished nightly runs. A replay (live=False) of the same day and book can be run
    many times; only the latest finished replay of each day counts, so a day is never counted twice."""
    lo, hi = _range(start, end)
    runs = (
        BrainRun.kind == "nightly",
        BrainRun.live.is_(live),
        BrainRun.status == "done",
        BrainRun.as_of >= lo,
        BrainRun.as_of < hi,
    )
    stmt = (
        select(
            BrainDecision.outcome,
            BrainDecision.outcome_return,
            BrainRun.as_of,
            BrainRun.book,
            func.coalesce(BrainDecision.overruled_word, BrainDecision.word),
        )
        .join(BrainRun, BrainRun.id == BrainDecision.run_id)
        .where(BrainDecision.kind == "idea", BrainDecision.outcome.is_not(None), *runs)
    )
    if not live:
        latest = (
            select(
                BrainRun.id,
                func.row_number()
                .over(
                    partition_by=(BrainRun.book, BrainRun.as_of),
                    order_by=(BrainRun.started_at.desc(), BrainRun.id.desc()),
                )
                .label("n"),
            )
            .where(*runs)
            .subquery()
        )
        stmt = stmt.where(BrainRun.id.in_(select(latest.c.id).where(latest.c.n == 1)))
    return list(db.execute(stmt).all())


def other_book_runs(db: Session, start: date, end: date, *, live: bool, book: str) -> int:
    lo, hi = _range(start, end)
    return (
        db.scalar(
            select(func.count())
            .select_from(BrainRun)
            .where(
                BrainRun.kind == "nightly",
                BrainRun.live.is_(live),
                BrainRun.status == "done",
                BrainRun.book != book,
                BrainRun.as_of >= lo,
                BrainRun.as_of < hi,
            )
        )
        or 0
    )


def nightly_sessions(db: Session, start: date, end: date, *, live: bool, book: str):
    """The trial journal's session rule (latest done nightly run per IST day, `book` filter, ideas with the
    owner's overrule word and the risk-blocked flag) in two statements, not one per day. A test proves it
    equals trial_journal.load_sessions on the same data."""
    from swing_trade_ml.brain.trial_journal import Idea
    from swing_trade_ml.brain.trial_journal import Session as JournalSession
    from swing_trade_ml.strategies.brain import blocked_by_risk

    lo, hi = _range(start, end)
    runs = db.execute(
        select(BrainRun.id, BrainRun.as_of, BrainRun.banner_mode)
        .where(
            BrainRun.kind == "nightly",
            BrainRun.live.is_(live),
            BrainRun.status == "done",
            BrainRun.book == book,
            BrainRun.as_of >= lo,
            BrainRun.as_of < hi,
        )
        .order_by(BrainRun.started_at.asc())
    ).all()
    latest = {}
    for r in runs:  # a later run of the same day replaces an earlier one
        latest[run_day(r.as_of)] = r
    ids = [r.id for r in latest.values()]
    by_run: dict[str, list] = {i: [] for i in ids}
    if ids:
        for d in db.scalars(
            select(BrainDecision)
            .where(BrainDecision.run_id.in_(ids), BrainDecision.kind == "idea")
            .order_by(BrainDecision.id)
        ):
            by_run[d.run_id].append(
                Idea(
                    d.symbol,
                    d.overruled_word or d.word,
                    d.confidence if d.score_source else None,
                    blocked=blocked_by_risk(d),
                )
            )
    return [
        JournalSession(day, latest[day].banner_mode, tuple(by_run[latest[day].id])) for day in sorted(latest)
    ]


def daily_bars(db: Session, symbols: list[str], lo: date, hi: date) -> dict[str, pd.DataFrame]:
    """Daily bars from `lo` to `hi` (IST days) for the given symbols, one statement, the same shape as
    replay_score.load_bars but bounded on both sides."""
    if not symbols:
        return {}
    lo_ts, hi_ts = _range(lo, hi)
    rows = db.execute(
        select(Instrument.tradingsymbol, Candle.ts, Candle.open, Candle.high, Candle.low, Candle.close)
        .join(Instrument, Instrument.id == Candle.instrument_id)
        .where(
            Instrument.tradingsymbol.in_(list(symbols)),
            Candle.interval == "day",
            Candle.ts >= lo_ts,
            Candle.ts < hi_ts,
        )
        .order_by(Instrument.tradingsymbol, Candle.ts)
    ).all()
    grouped: dict[str, list[dict]] = {}
    for sym, ts, o, h, low, c in rows:
        grouped.setdefault(sym, []).append(
            {"day": run_day(ts), "open": float(o), "high": float(h), "low": float(low), "close": float(c)}
        )
    return {s: pd.DataFrame(r, columns=BAR_COLUMNS) for s, r in grouped.items()}


def universe_by_run(db: Session, run_ids: list[str]) -> dict[str, int | None]:
    """The universe size each run stored in its data manifest (None when it stored none)."""
    if not run_ids:
        return {}
    rows = db.execute(
        select(BrainRun.id, BrainRun.context["data_manifest"]["universe_count"].as_integer()).where(
            BrainRun.id.in_(run_ids)
        )
    ).all()
    return dict(rows)
