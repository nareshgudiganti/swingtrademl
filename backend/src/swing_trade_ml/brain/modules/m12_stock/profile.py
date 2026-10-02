"""How a stock usually behaves, in one plain line, from its last year of bars:
its typical daily move, how often it opens with a jump, and how often (and
how fast) it reached +8% within the 15-trading-day horizon.

Pure: bars must already end at the run's date. Fewer than MIN_BARS → None.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

MIN_BARS = 60
YEAR = 250
GAP = 0.02
TARGET = 0.08
HORIZON = 15


def profile_line(bars: pd.DataFrame) -> str | None:
    if len(bars) < MIN_BARS:
        return None
    b = bars.tail(YEAR).reset_index(drop=True)
    close, high = b["close"].to_numpy(float), b["high"].to_numpy(float)
    daily_range = float(np.median((b["high"] - b["low"]) / b["close"]))
    prev = np.r_[np.nan, close[:-1]]
    gaps = np.abs(b["open"].to_numpy(float) / prev - 1)[1:]
    gap_share = float(np.mean(gaps > GAP)) if gaps.size else 0.0

    days_to_hit: list[int] = []
    tested = 0
    for i in range(len(b) - HORIZON):
        tested += 1
        ahead = high[i + 1 : i + 1 + HORIZON] >= close[i] * (1 + TARGET)
        if ahead.any():
            days_to_hit.append(int(np.argmax(ahead)) + 1)

    line = (
        f"Usually moves about {daily_range:.1%} in a day; opens with a jump of more than "
        f"{GAP:.0%} on {gap_share:.0%} of days"
    )
    if tested:
        rate = len(days_to_hit) / tested
        line += (
            f"; reached +{TARGET:.0%} within {HORIZON} trading days {rate:.0%} of the time in the last year"
        )
        if days_to_hit:
            line += f" (typically in {int(np.median(days_to_hit))} days)"
    return line + "."
