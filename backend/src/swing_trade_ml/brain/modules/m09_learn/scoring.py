"""Score every unscored idea decision of a live nightly run whose outcome is
now known, and write it onto `brain_decisions` (M09). Replays, why-runs and
intraday runs are never scored — only a live nightly run is real enough
evidence for the learning loop to grade."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.brain.modules.m09_learn.outcomes import score
from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
from swing_trade_ml.db.models.market import Candle, Instrument

# Daily candles are stamped IST midnight (stored as 18:30 UTC the day before),
# so a bar's trading day must always be read in IST.
IST = ZoneInfo("Asia/Kolkata")


def _decision_day(as_of: datetime) -> date:
    return as_of.astimezone(IST).date()


def _bars(db: Session, symbol: str) -> pd.DataFrame:
    """Every daily bar for this symbol, ascending, with its IST trading day."""
    rows = db.execute(
        select(Candle.ts, Candle.high, Candle.low, Candle.close)
        .join(Instrument, Instrument.id == Candle.instrument_id)
        .where(Instrument.tradingsymbol == symbol, Candle.interval == "day")
        .order_by(Candle.ts.asc())
    ).all()
    return pd.DataFrame(
        [
            {"day": ts.astimezone(IST).date(), "high": float(high), "low": float(low), "close": float(close)}
            for ts, high, low, close in rows
        ],
        columns=["day", "high", "low", "close"],
    )


def score_pending(db: Session, upto: date) -> int:
    """Score every unscored idea decision of a live nightly run whose outcome
    is known by `upto` (IST trading day). decision day = `brain_runs.as_of` in
    Asia/Kolkata as a date; entry = the stock's last daily close on or before
    that day; bars_after = daily bars with IST day > decision day and <= upto.
    Writes the six outcome columns. Returns how many were scored."""
    pending = db.execute(
        select(BrainDecision, BrainRun.as_of)
        .join(BrainRun, BrainRun.id == BrainDecision.run_id)
        .where(
            BrainDecision.kind == "idea",
            BrainDecision.outcome.is_(None),
            BrainRun.kind == "nightly",
            BrainRun.live.is_(True),
        )
    ).all()

    bars_by_symbol: dict[str, pd.DataFrame] = {}
    scored = 0
    for decision, as_of in pending:
        bars = bars_by_symbol.setdefault(decision.symbol, _bars(db, decision.symbol))
        if bars.empty:
            continue
        decision_day = _decision_day(as_of)
        before = bars[bars["day"] <= decision_day]
        if before.empty:
            continue
        entry = float(before.iloc[-1]["close"])
        after = bars[(bars["day"] > decision_day) & (bars["day"] <= upto)].reset_index(drop=True)
        outcome = score(entry, after)
        if outcome is None:
            continue
        decision.outcome = outcome.outcome
        decision.outcome_return = outcome.ret
        decision.outcome_days = outcome.days
        decision.max_up = outcome.max_up
        decision.max_down = outcome.max_down
        decision.resolved_on = outcome.resolved_on
        scored += 1
    db.flush()
    return scored


def score_pending_from_reader(db: Session, reader) -> int:
    """The after-run hook's entry point (`service._sync_episodes`): score
    everything resolvable as of this reader's own IST trading day."""
    return score_pending(db, reader.as_of.astimezone(IST).date())
