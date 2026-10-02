"""Where an open trade stands today, against similar past trades.

The band is the 25th-75th percentile of similar trades' returns on each day
after entry (M05's memory). Today's status:

* stop hit      the close is at or below the stop — the exit rules sell; the
                card states it and offers no choice (constitution C7)
* past horizon  more than 15 trading days in: the plan's window is over; the
                time stop (30 calendar days) still applies
* on track      at or above the band's low edge
* breakdown     more than one average day's range (ATR) below the low edge
* drift         below the band, but not that far, and above the stop

(The module adds "no data" when no price has arrived since an older entry.)

Pure.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from swing_trade_ml.brain.contracts import TrackPoint
from swing_trade_ml.services.limits import format_inr

HORIZON = 15
FIRST_TARGET = 0.05
MIN_CASES = 30


def track(
    symbol: str,
    entry_price: float,
    closes_since: list[tuple[date, float]],
    stop: float | None,
    band: tuple[tuple[int, float, float, float], ...],
    atr_pct: float | None,
) -> TrackPoint:
    day_n = len(closes_since)
    close = closes_since[-1][1] if closes_since else entry_price
    ret = close / entry_price - 1 if entry_price > 0 else 0.0
    common = {"symbol": symbol, "day_n": day_n, "ret": ret, "stop": stop, "band": band}

    if stop is not None and close <= stop:
        return TrackPoint(
            status="stop hit",
            reason=f"Stop hit at {format_inr(stop)}: the exit rules sell this position.",
            **common,
        )
    if day_n == 0:
        return TrackPoint(status="on track", reason="Bought today; tracking starts tomorrow.", **common)
    if day_n > HORIZON:
        return TrackPoint(
            status="past horizon",
            reason=(
                f"Day {day_n}: past the usual {HORIZON} trading days at {ret:+.1%}. The time stop "
                "(30 calendar days) still applies."
            ),
            **common,
        )
    if not band or day_n > len(band):
        return TrackPoint(
            status="on track",
            reason=(
                f"Day {day_n} of up to {HORIZON}: {ret:+.1%}; no record of similar trades to compare with."
            ),
            **common,
        )
    _, low, mid, high = band[day_n - 1]
    where = f"Day {day_n} of up to {HORIZON}: {ret:+.1%}"
    usual = f"the usual range of similar trades ({low:+.1%} to {high:+.1%})"
    if ret >= low:
        status, reason = "on track", f"{where}, inside {usual}."
    elif atr_pct is not None and ret < low - atr_pct:
        status, reason = "breakdown", f"{where}, well below {usual}."
    else:
        status, reason = "drift", f"{where}, below {usual} but above the stop."
    return TrackPoint(status=status, reason=reason, band_low=low, band_mid=mid, band_high=high, **common)


def after_first_target(similar: pd.DataFrame) -> str | None:
    """Of similar trades whose close reached +5%, how many went on to +8% —
    the evidence for booking half at +5% and trailing the rest."""
    if similar.empty:
        return None
    reached = similar[similar["path"].map(lambda p: max(p) >= FIRST_TARGET)]
    if len(reached) < MIN_CASES:
        return None
    share = float((reached["outcome"] == "target").mean())
    return f"Of {len(reached)} similar trades that reached +5%, {share:.0%} went on to reach +8%."
