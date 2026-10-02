"""Pure outcome scoring for one decision's trade idea (M09): did it reach the
target, hit the stop, or time out — the same locked rule as
`ml.features.build_label` and `m05_memory.cases`: entry at the decision day's
close, horizon 15 trading bars, a bar touching both barriers counts as the
stop. No side effects, no database."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd


@dataclass(frozen=True, slots=True)
class Outcome:
    outcome: str  # target | stop | timeout
    ret: float  # +0.08, -0.04, or the bar-15 close / entry - 1
    days: int  # bars until the hit, or the horizon
    max_up: float  # highest high / entry - 1 over the bars considered
    max_down: float  # lowest low / entry - 1 over the bars considered
    resolved_on: date  # the bar day the outcome became known


def score(
    entry: float,
    bars_after: pd.DataFrame,
    horizon: int = 15,
    target: float = 0.08,
    stop: float = 0.04,
) -> Outcome | None:
    """`bars_after`: columns day, high, low, close — bars strictly after the
    decision day, ascending. Walks bars 1..horizon, stop checked first (a
    same-bar touch of both barriers is a stop). `max_up`/`max_down` are the
    highest high / lowest low over the bars actually walked (up to and
    including the hit, or the whole horizon on a timeout). Fewer than
    `horizon` bars with no hit yet -> None (the outcome is not known)."""
    n = min(len(bars_after), horizon)
    max_up = float("-inf")
    max_down = float("inf")
    for i in range(n):
        row = bars_after.iloc[i]
        high, low, day = float(row["high"]), float(row["low"]), row["day"]
        max_up = max(max_up, high / entry - 1)
        max_down = min(max_down, low / entry - 1)
        if low <= entry * (1 - stop):  # checked first: a same-bar touch of both is a stop
            return Outcome("stop", -stop, i + 1, max_up, max_down, day)
        if high >= entry * (1 + target):
            return Outcome("target", target, i + 1, max_up, max_down, day)
    if n < horizon:
        return None
    last = bars_after.iloc[horizon - 1]
    return Outcome("timeout", float(last["close"]) / entry - 1, horizon, max_up, max_down, last["day"])
