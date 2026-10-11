# backend/src/swing_trade_ml/brain/replay_scoring.py
"""Strict, pure scoring of one idea against what the stock really did (replay-score).

The locked rule in `m09_learn.outcomes` enters at the decision day's close and
assumes exactly +8% / -4%. This stricter rule is closer to what a real order would
get: it enters at the next day's open, fills a gap at the open (not at the level),
pays slippage and charges (`services/costs.py`) and sells half at +5%. After the
half-out the stop is NOT moved up: that is the cautious reading of a plain stop.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from swing_trade_ml.brain.modules.m09_learn.outcomes import Outcome, score
from swing_trade_ml.services.costs import apply_slippage, compute_charges

HORIZON_BARS = 15
TARGET = 0.08
STOP = 0.04
HALF_OUT = 0.05
POSITION_INR = 40_000.0  # about the smallest position the risk rules allow


@dataclass(frozen=True, slots=True)
class StrictOutcome:
    status: str  # target | stop | timeout | open
    net_return: float | None  # fraction of the money put in, after costs; None while open
    days: int | None  # bars held, counting the entry day as 1
    half_out: bool  # half was sold at +5%
    gap: bool  # an exit filled at the open, past the level
    exit_day: date | None


def _sell(price: float, qty: float) -> float:
    """Cash received for selling `qty` shares at `price`, after slippage and charges."""
    gross = apply_slippage(price, "SELL") * qty
    brokerage, taxes = compute_charges(gross, "SELL")
    return gross - brokerage - taxes


def _done(status, cash_in, cash_out, days, half_done, gap, day) -> StrictOutcome:
    return StrictOutcome(status, cash_out / cash_in - 1.0, days, half_done, gap, day)


def strict_score(bars: pd.DataFrame) -> StrictOutcome:
    """`bars`: columns day, open, high, low, close; the first row is the entry day
    (the day after the decision), ascending."""
    if bars.empty:
        return StrictOutcome("open", None, None, False, False, None)
    fill = apply_slippage(float(bars.iloc[0]["open"]), "BUY")
    qty = POSITION_INR / fill
    brokerage, taxes = compute_charges(fill * qty, "BUY")
    cash_in = fill * qty + brokerage + taxes
    stop, half, target = fill * (1 - STOP), fill * (1 + HALF_OUT), fill * (1 + TARGET)

    held, cash_out, half_done, gap = qty, 0.0, False, False
    n = min(len(bars), HORIZON_BARS)
    for i in range(n):
        row = bars.iloc[i]
        o, h, lo, day = float(row["open"]), float(row["high"]), float(row["low"]), row["day"]
        if lo <= stop:  # checked first: a bar touching the stop and anything else is the stop
            gap = gap or o <= stop
            cash_out += _sell(o if o <= stop else stop, held)
            return _done("stop", cash_in, cash_out, i + 1, half_done, gap, day)
        if not half_done and h >= half:
            cash_out += _sell(o if o >= half else half, qty / 2)
            held, half_done = qty / 2, True
        if h >= target:
            gap = gap or o >= target
            cash_out += _sell(o if o >= target else target, held)
            return _done("target", cash_in, cash_out, i + 1, half_done, gap, day)
    if n < HORIZON_BARS:
        return StrictOutcome("open", None, None, half_done, gap, None)
    last = bars.iloc[HORIZON_BARS - 1]
    cash_out += _sell(float(last["close"]), held)
    return _done("timeout", cash_in, cash_out, HORIZON_BARS, half_done, gap, last["day"])


def after_day(df: pd.DataFrame, day: date) -> pd.DataFrame:
    """Bars strictly after the decision day."""
    return df[df["day"] > day].reset_index(drop=True)


def locked_score(df: pd.DataFrame, day: date) -> Outcome | None:
    """The existing M09 rule: entry at the decision day's close. None if there is no such bar."""
    before = df[df["day"] <= day]
    if before.empty:
        return None
    entry = float(before.iloc[-1]["close"])
    return score(entry, after_day(df, day)[["day", "high", "low", "close"]])


def strict_for(df: pd.DataFrame, day: date) -> StrictOutcome:
    return strict_score(after_day(df, day))
