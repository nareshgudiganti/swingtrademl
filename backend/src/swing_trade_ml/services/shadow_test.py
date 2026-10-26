"""Shadow Test: follow every ranked stock for its 15-trading-day window, bought or not.

Read-only. It answers "do higher-ranked stocks do better?" from what the brain already stored: every nightly
live run's ranked ideas, graded by the learning loop (M09: +8% target, -4% stop, or timeout at day 15). It
changes no pick, order, size, stop or limit and writes nothing.

Honesty rules (the Atlas Shadow Test tab):
  * only FINISHED ideas count in results; a running idea is shown, never counted as a win;
  * one record per stock at a time: a stock that stays on the list is counted once, and a new record starts
    only after the previous one has finished;
  * rank groups are fixed up front (1-5, 6-20, 21+) and rank is the rank on the day the record started;
  * fewer than 30 completed ranking days: no verdict, only "too early";
  * a stock whose last candle is not the last closed trading day says "price not updated" instead of showing
    an old move as today's.
Daily candles are stamped IST midnight, so every bar day is read in IST.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.core.market_session import last_closed_trading_day
from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.trading import Position

IST = ZoneInfo("Asia/Kolkata")

HORIZON = 15
TARGET = 0.08
STOP = 0.04
#: Completed ranking days needed before the page says anything beyond "too early".
DAYS_NEEDED = 30
GROUPS: tuple[tuple[str, int, int | None], ...] = (
    ("Top 5", 1, 5),
    ("Ranks 6-20", 6, 20),
    ("Rank 21+", 21, None),
)
LABEL = "Exploring, not part of the sealed 6-month test. Passive tracking only: nothing here places an order."
FINISHED_SHOWN = 200


@dataclass
class Idea:
    """One ranked idea of a live nightly run."""

    decision_id: int
    symbol: str
    day: date
    rank: int
    score: float
    word: str
    outcome: str | None  # target | stop | timeout | None while still running
    ret: float | None = None
    days: int | None = None
    resolved_on: date | None = None


def rank_ideas(scored: list[tuple[int, float]]) -> dict[int, int]:
    """decision id -> rank on the day. Highest score is rank 1; equal scores share a place (1, 2, 2, 4)."""
    ordered = sorted(scored, key=lambda x: x[1], reverse=True)
    ranks: dict[int, int] = {}
    place = 0
    previous: float | None = None
    for i, (decision_id, score) in enumerate(ordered, start=1):
        if previous is None or score != previous:
            place = i
            previous = score
        ranks[decision_id] = place
    return ranks


def group_of(rank: int) -> str:
    for name, low, high in GROUPS:
        if rank >= low and (high is None or rank <= high):
            return name
    return GROUPS[-1][0]


def build_records(ideas: list[Idea]) -> list[Idea]:
    """One record per stock at a time (no-repeat counting). Ideas are taken oldest first; while a stock's
    record is running, or on/before the day it finished, later ideas for it are not counted again."""
    records: list[Idea] = []
    current: dict[str, Idea] = {}
    for idea in sorted(ideas, key=lambda i: (i.day, i.rank)):
        held = current.get(idea.symbol)
        if held is not None and (held.outcome is None or (held.resolved_on and idea.day <= held.resolved_on)):
            continue
        current[idea.symbol] = idea
        records.append(idea)
    return records


def running_progress(
    entry: float, bars: list[tuple[date, float]], decision_day: date, last_closed: date
) -> dict:
    """Where a running idea stands. `bars` is (IST day, close) ascending. Day N counts trading bars after the
    ranking day. 'Today' is shown only when the newest bar is the last closed trading day."""
    after = [(d, c) for d, c in bars if d > decision_day and d <= last_closed]
    day_n = min(len(after), HORIZON)
    if not after:
        return {"day": 0, "today_pct": None, "since_pct": None, "position": None, "price_not_updated": True}
    last_day, last_close = after[-1]
    fresh = last_day == last_closed
    previous = after[-2][1] if len(after) >= 2 else entry
    since = last_close / entry - 1
    position = (min(max(since, -STOP), TARGET) + STOP) / (TARGET + STOP)
    return {
        "day": day_n,
        "today_pct": round((last_close / previous - 1) * 100, 2) if fresh else None,
        "since_pct": round(since * 100, 2),
        "position": round(position, 3),
        "price_not_updated": not fresh,
    }


def group_table(finished: list[Idea]) -> list[dict]:
    """Per rank group: finished, reached +8%, hit -4%, average result. Finished ideas only."""
    rows = []
    for name, _, _ in GROUPS:
        mine = [i for i in finished if group_of(i.rank) == name]
        n = len(mine)
        rows.append(
            {
                "group": name,
                "finished": n,
                "target": sum(1 for i in mine if i.outcome == "target"),
                "stop": sum(1 for i in mine if i.outcome == "stop"),
                "average_pct": round(sum(i.ret or 0 for i in mine) / n * 100, 2) if n else None,
            }
        )
    return rows


def verdict(finished: list[Idea], days_done: int, groups: list[dict]) -> dict:
    """A plain sentence. Under 30 completed ranking days it only says it is too early."""
    top = groups[0]
    base = {"days_done": days_done, "days_needed": DAYS_NEEDED}
    if days_done < DAYS_NEEDED:
        return {
            **base,
            "state": "too_early",
            "headline": "Too early to tell",
            "detail": f"Only {top['finished']} top-ranked ideas have finished. The ranking is not proven.",
        }
    rest = [i for i in finished if group_of(i.rank) != GROUPS[0][0]]
    rest_avg = sum(i.ret or 0 for i in rest) / len(rest) * 100 if rest else None
    if top["average_pct"] is None or rest_avg is None:
        return {
            **base,
            "state": "too_early",
            "headline": "Too early to tell",
            "detail": "Not enough finished ideas in every group.",
        }
    return {
        **base,
        "state": "reviewable",
        "headline": "Enough days to review",
        "detail": (
            f"Top-5 ideas averaged {top['average_pct']:+.1f}% and the rest {rest_avg:+.1f}%, before costs. "
            "A gap this size can still be chance; this page is not a pass or fail."
        ),
    }


# ----------------------------------------------------------------- reading --


def _load_ideas(db: Session) -> list[Idea]:
    """Every ranked idea of every live nightly run still in force (superseded runs are left out so a day is
    never counted twice)."""
    rows = db.execute(
        select(BrainDecision, BrainRun.as_of)
        .join(BrainRun, BrainRun.id == BrainDecision.run_id)
        .where(
            BrainDecision.kind == "idea",
            BrainDecision.confidence.is_not(None),
            BrainRun.kind == "nightly",
            BrainRun.live.is_(True),
            BrainRun.status == "done",
        )
    ).all()
    by_run: dict[str, list[tuple[BrainDecision, date]]] = {}
    for decision, as_of in rows:
        by_run.setdefault(decision.run_id, []).append((decision, as_of.astimezone(IST).date()))
    ideas: list[Idea] = []
    for members in by_run.values():
        ranks = rank_ideas([(d.id, float(d.confidence)) for d, _ in members])
        for d, day in members:
            if d.outcome == "noscore":  # can never be graded: not followed
                continue
            ideas.append(
                Idea(
                    decision_id=d.id,
                    symbol=d.symbol,
                    day=day,
                    rank=ranks[d.id],
                    score=float(d.confidence),
                    word=d.word,
                    outcome=d.outcome if d.outcome in ("target", "stop", "timeout") else None,
                    ret=d.outcome_return,
                    days=d.outcome_days,
                    resolved_on=d.resolved_on,
                )
            )
    return ideas


def _bars(db: Session, symbols: set[str], since: date) -> dict[str, list[tuple[date, float]]]:
    out: dict[str, list[tuple[date, float]]] = {s: [] for s in symbols}
    if not symbols:
        return out
    floor = datetime.combine(since, datetime.min.time(), tzinfo=IST)
    rows = db.execute(
        select(Instrument.tradingsymbol, Candle.ts, Candle.close)
        .join(Candle, Candle.instrument_id == Instrument.id)
        .where(
            Instrument.tradingsymbol.in_(symbols),
            Instrument.exchange == "NSE",
            Candle.interval == "day",
            Candle.ts >= floor,
        )
        .order_by(Candle.ts)
    ).all()
    for symbol, ts, close in rows:
        out[symbol].append((ts.astimezone(IST).date(), float(close)))
    return out


def _paper_buys(db: Session, symbols: set[str]) -> dict[str, list[date]]:
    """Days a paper position was opened per symbol (any strategy, any book)."""
    out: dict[str, list[date]] = {s: [] for s in symbols}
    if not symbols:
        return out
    rows = db.execute(
        select(Instrument.tradingsymbol, Position.entry_at)
        .join(Position, Position.instrument_id == Instrument.id)
        .where(Instrument.tradingsymbol.in_(symbols), Position.mode == "paper")
    ).all()
    for symbol, at in rows:
        out[symbol].append(at.astimezone(IST).date())
    return out


def build_view(db: Session, now: datetime) -> dict:
    last_closed = last_closed_trading_day(now)
    records = build_records(_load_ideas(db))
    running = [r for r in records if r.outcome is None]
    finished = [r for r in records if r.outcome is not None]

    symbols = {r.symbol for r in records}
    since = min((r.day for r in running), default=last_closed)
    bars = _bars(db, {r.symbol for r in running}, since)
    buys = _paper_buys(db, symbols)

    def bought(r: Idea) -> bool:
        return any(
            d >= r.day and (r.resolved_on is None or d <= r.resolved_on) for d in buys.get(r.symbol, [])
        )

    running_rows = []
    for r in sorted(running, key=lambda x: (x.rank, x.symbol)):
        series = bars.get(r.symbol, [])
        before = [c for d, c in series if d <= r.day]
        entry = before[-1] if before else None
        prog = (
            running_progress(entry, series, r.day, last_closed)
            if entry
            else {"day": 0, "today_pct": None, "since_pct": None, "position": None, "price_not_updated": True}
        )
        running_rows.append(
            {
                "symbol": r.symbol,
                "rank": r.rank,
                "group": group_of(r.rank),
                "score": round(r.score * 100),
                "word": r.word,
                "ranked_on": r.day,
                "paper_bought": bought(r),
                **prog,
            }
        )

    finished_rows = [
        {
            "symbol": r.symbol,
            "rank": r.rank,
            "group": group_of(r.rank),
            "ranked_on": r.day,
            "ended_on": r.resolved_on,
            "outcome": r.outcome,
            "result_pct": round((r.ret or 0) * 100, 2),
            "days": r.days,
            "paper_bought": bought(r),
        }
        for r in sorted(finished, key=lambda x: x.resolved_on or x.day, reverse=True)[:FINISHED_SHOWN]
    ]

    groups = group_table(finished)
    days_done = len({r.day for r in finished})
    return {
        "as_of": last_closed,
        "label": LABEL,
        "verdict": verdict(finished, days_done, groups),
        "totals": {
            "running": len(running),
            "finished": len(finished),
            "target": sum(1 for r in finished if r.outcome == "target"),
            "stop": sum(1 for r in finished if r.outcome == "stop"),
        },
        "groups": groups,
        "running": running_rows,
        "finished": finished_rows,
        "how": [
            "Rank recorded: a stock enters from the brain's nightly ranking.",
            "Track daily: we follow its price for up to 15 trading days.",
            "Target, stop or day 15: the first outcome is recorded (+8%, -4% or day 15).",
            "Count outcome: it is added to the results of its original rank group.",
        ],
    }
