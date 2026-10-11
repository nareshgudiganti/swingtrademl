# backend/src/swing_trade_ml/brain/replay_score.py
"""Replay the brain over past days and score every idea against what happened next.

Read-only for live evidence: it never writes `brain_decisions.outcome*` and nothing it
produces counts toward the M18 30-idea gate. Replays are non-live runs; this module
only reads their decisions and the candles.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.brain import service
from swing_trade_ml.brain.replay_report import (
    LIMITATIONS,
    ScoredIdea,
    all_eligible_stats,
    random_baseline,
    track_stats,
)
from swing_trade_ml.brain.replay_scoring import locked_score, strict_for
from swing_trade_ml.brain.replay_week import run_replay_week
from swing_trade_ml.core.market_session import last_closed_trading_day
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.trading import Signal, Strategy
from swing_trade_ml.ml.asof import asof_cutoff
from swing_trade_ml.strategies.brain import blocked_by_risk

IST = ZoneInfo("Asia/Kolkata")
_BAR_COLUMNS = ["day", "open", "high", "low", "close"]


class ReplayWindowError(ValueError):
    """The requested replay would score days the model had already learned from."""


def _check_window(asof_model, start: date, allow_in_sample: bool) -> dict:
    """Refuse a window that starts on or before the model's cutoff, unless told otherwise."""
    cutoff = asof_cutoff(asof_model)
    in_sample = False
    if cutoff is None:
        if not allow_in_sample:
            raise ReplayWindowError(
                f"{asof_model.name} has no cutoff date, so it has seen recent days. "
                "Train one with `brain asof-train --cutoff D`, or pass --allow-in-sample."
            )
        in_sample = True
    elif start <= cutoff:
        if not allow_in_sample:
            raise ReplayWindowError(
                f"The window starts {start.isoformat()} but {asof_model.name} was trained on data "
                f"up to {cutoff.isoformat()}. Start after {cutoff.isoformat()}, or pass --allow-in-sample."
            )
        in_sample = True
    return {
        "name": asof_model.name,
        "version": asof_model.version,
        "cutoff": cutoff.isoformat() if cutoff else None,
        "in_sample": in_sample,
    }


def collect_ideas(db: Session, run_id: str, day: date) -> tuple[list[dict], list[str]]:
    """(ideas, every symbol the brain judged that day). An idea is a TRADE that stayed
    TRADE (track B) or a TRADE the risk check lowered to WATCH (blocked). The owner's
    overrule, if any, wins over the brain's own word."""
    rows: list[dict] = []
    symbols: list[str] = []
    for d in service.decisions_for(db, run_id):
        if d.kind != "idea":
            continue
        symbols.append(d.symbol)
        final = d.overruled_word or d.word
        track_b = final == "TRADE"
        blocked = (not track_b) and blocked_by_risk(d) and d.stop is not None and d.target is not None
        if not (track_b or blocked):
            continue
        rows.append(
            {
                "symbol": d.symbol,
                "word": final,
                "track_b": track_b,
                "blocked": blocked,
                "score": round(d.confidence * 100) if d.confidence is not None else None,
                "reasons": tuple(d.reasons or ()),
            }
        )
    return rows, symbols


def load_bars(db: Session, symbols: Sequence[str], upto: date) -> dict[str, pd.DataFrame]:
    """Daily bars per symbol, ascending, with IST trading days, up to and including `upto`."""
    if not symbols:
        return {}
    ceiling = datetime.combine(upto + timedelta(days=1), time(0, 0), tzinfo=IST)
    rows = db.execute(
        select(Instrument.tradingsymbol, Candle.ts, Candle.open, Candle.high, Candle.low, Candle.close)
        .join(Instrument, Instrument.id == Candle.instrument_id)
        .where(Instrument.tradingsymbol.in_(list(symbols)), Candle.interval == "day", Candle.ts < ceiling)
        .order_by(Instrument.tradingsymbol, Candle.ts.asc())
    ).all()
    grouped: dict[str, list[dict]] = defaultdict(list)
    for symbol, ts, o, h, lo, c in rows:
        grouped[symbol].append(
            {
                "day": ts.astimezone(IST).date(),
                "open": float(o),
                "high": float(h),
                "low": float(lo),
                "close": float(c),
            }
        )
    return {s: pd.DataFrame(r, columns=_BAR_COLUMNS) for s, r in grouped.items()}


def v1_buys(db: Session, start: date, end: date) -> dict[date, list[str]]:
    """Version 1's `ml_swing` BUY signals per IST day (paper), for the same-days comparison."""
    lo = datetime.combine(start, time(0, 0), tzinfo=IST)
    hi = datetime.combine(end + timedelta(days=1), time(0, 0), tzinfo=IST)
    rows = db.execute(
        select(Signal.generated_at, Instrument.tradingsymbol)
        .join(Strategy, Strategy.id == Signal.strategy_id)
        .join(Instrument, Instrument.id == Signal.instrument_id)
        .where(
            Strategy.strategy_type == "ml_swing",
            Signal.signal_type == "BUY",
            Signal.mode == "paper",
            Signal.generated_at >= lo,
            Signal.generated_at < hi,
        )
        .order_by(Signal.generated_at)
    ).all()
    out: dict[date, list[str]] = defaultdict(list)
    for when, symbol in rows:
        day = when.astimezone(IST).date()
        if symbol not in out[day]:
            out[day].append(symbol)
    return dict(out)


def _idea_row(i: ScoredIdea) -> dict:
    s = i.strict
    return {
        "day": i.day.isoformat(),
        "symbol": i.symbol,
        "word": i.word,
        "track": "B" if i.track_b else "A only (blocked by the risk check)",
        "score": i.score,
        "why": list(i.reasons[:3]),
        "strict_status": "no_price_data" if s is None else s.status,
        "strict_net_return": None if s is None else s.net_return,
        "strict_days": None if s is None else s.days,
        "locked_status": None if i.locked is None else i.locked.outcome,
        "locked_return": None if i.locked is None else i.locked.ret,
    }


def run_replay_score(
    db: Session,
    *,
    start: date,
    end: date,
    book: str = "paper",
    symbols: list[str] | None = None,
    upto: date | None = None,
    replay: Callable = run_replay_week,
    draws: int = 200,
    seed: int = 7,
    asof_model=None,
    allow_in_sample: bool = False,
) -> dict:
    model_info = None if asof_model is None else _check_window(asof_model, start, allow_in_sample)
    extra = {} if asof_model is None else {"asof_model": asof_model}
    failed: list[str] = []
    try:
        results = list(replay(db, start=start, end=end, book=book, symbols=symbols, **extra))
    except Exception as exc:  # noqa: BLE001 - a failed replay is reported, never hidden
        results = []
        failed.append(f"{start.isoformat()}..{end.isoformat()} ({type(exc).__name__}: {exc})")

    upto = upto or last_closed_trading_day(datetime.now(UTC))
    per_day: dict[date, list[dict]] = {}
    pool: dict[date, list[str]] = {}
    scored_days = 0
    for r in results:
        rows, judged = collect_ideas(db, r.run_id, r.day)
        per_day[r.day] = rows
        pool[r.day] = judged
        if any(d.confidence is not None for d in service.decisions_for(db, r.run_id)):
            scored_days += 1

    wanted = sorted({s for syms in pool.values() for s in syms})
    bars = load_bars(db, wanted, upto)

    outcomes: dict[tuple[str, date], object] = {}
    for day, judged in pool.items():
        for sym in judged:
            df = bars.get(sym)
            outcomes[(sym, day)] = None if df is None or df.empty else strict_for(df, day)

    scored: list[ScoredIdea] = []
    for day, rows in per_day.items():
        for row in rows:
            df = bars.get(row["symbol"])
            locked = None if df is None or df.empty else locked_score(df, day)
            scored.append(
                ScoredIdea(
                    day=day,
                    symbol=row["symbol"],
                    word=row["word"],
                    track_b=row["track_b"],
                    blocked=row["blocked"],
                    score=row["score"],
                    reasons=row["reasons"],
                    locked=locked,
                    strict=outcomes[(row["symbol"], day)],
                )
            )

    picks_per_day = {d: len(rows) for d, rows in per_day.items() if rows}
    v1 = v1_buys(db, start, end)
    v1_bars = load_bars(db, sorted({s for syms in v1.values() for s in syms}), upto)
    v1_outcomes = {
        (s, d): (None if v1_bars.get(s) is None or v1_bars[s].empty else strict_for(v1_bars[s], d))
        for d, syms in v1.items()
        for s in syms
    }

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "window": {
            "from": start.isoformat(),
            "to": end.isoformat(),
            "days_replayed": len(results),
            "failed_days": failed,
            "scored_up_to": upto.isoformat(),
        },
        "model": None
        if model_info is None
        else {**model_info, "days_scored": scored_days, "days_without_score": len(results) - scored_days},
        "track_a": track_stats(scored),
        "track_b": track_stats([i for i in scored if i.track_b]),
        "baselines": {
            "all_eligible": all_eligible_stats(pool, outcomes),
            "random": random_baseline(pool, picks_per_day, outcomes, draws=draws, seed=seed),
            "v1": all_eligible_stats(v1, v1_outcomes),
        },
        "ideas": [_idea_row(i) for i in scored],
        "limitations": list(LIMITATIONS),
    }
