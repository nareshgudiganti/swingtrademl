"""Classic swing setups, from a stock's daily bars (exact rules, each tested).

* pullback in up-trend  the 20-day average is above the 50-day one and the
                        50-day one is higher than 10 days ago; today's low
                        touched the 20-day average (within 1%) and the close
                        held (no more than 2% below it)
* breakout              the close is above the highest high of the previous
                        20 days, on at least 1.5x their average volume
* base                  the last 10 days' whole range is under 1.5x the
                        14-day average true range (a tight, quiet stretch)
* breakdown             the close is below the lowest low of the previous 20
                        days on at least 1.5x their average volume — the
                        only label that argues against buying

Pure: bars must already end at the run's date. Fewer than MIN_BARS → none.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from swing_trade_ml.ml.features import atr

MIN_BARS = 60
LOOKBACK = 20
VOLUME_MULTIPLE = 1.5
BASE_DAYS = 10
BASE_ATR_MULTIPLE = 1.5


@dataclass(frozen=True, slots=True)
class Setup:
    label: str
    line: str  # plain card line
    confirming: bool  # True supports buying; False argues against it


def _heavy_volume(bars: pd.DataFrame) -> float | None:
    """Today's volume as a multiple of the previous 20 days' average, or None
    when that average is zero (a suspended or empty stock)."""
    avg = float(bars["volume"].iloc[-1 - LOOKBACK : -1].mean())
    return None if avg <= 0 else float(bars["volume"].iloc[-1]) / avg


def find_setups(bars: pd.DataFrame) -> list[Setup]:
    if len(bars) < MIN_BARS:
        return []
    close, high, low = bars["close"], bars["high"], bars["low"]
    last = float(close.iloc[-1])
    prior = bars.iloc[-1 - LOOKBACK : -1]
    volume_x = _heavy_volume(bars)
    heavy = volume_x is not None and volume_x >= VOLUME_MULTIPLE
    found: list[Setup] = []

    sma20, sma50 = close.rolling(20).mean(), close.rolling(50).mean()
    up_trend = sma20.iloc[-1] > sma50.iloc[-1] and sma50.iloc[-1] > sma50.iloc[-11]
    if up_trend and low.iloc[-1] <= sma20.iloc[-1] * 1.01 and last >= sma20.iloc[-1] * 0.98:
        found.append(
            Setup("pullback in up-trend", "Setup: pullback to the 20-day average in an up-trend.", True)
        )

    if heavy and last > float(prior["high"].max()):
        found.append(
            Setup(
                "breakout",
                f"Setup: breakout above the 20-day high on {volume_x:.1f}x the usual volume.",
                True,
            )
        )

    recent = bars.iloc[-BASE_DAYS:]
    span = float(recent["high"].max() - recent["low"].min())
    atr14 = float(atr(high, low, close, 14).iloc[-1])
    if atr14 > 0 and span < BASE_ATR_MULTIPLE * atr14:
        found.append(
            Setup("base", "Setup: tight base — the price has held in a narrow range for 10 days.", True)
        )

    if heavy and last < float(prior["low"].min()):
        found.append(
            Setup(
                "breakdown",
                f"Breakdown: closed below the 20-day low on {volume_x:.1f}x the usual volume.",
                False,
            )
        )
    return found
