"""Name what the market is doing, from NIFTY and India VIX closes by date.

In order of priority (the first that fits wins):

* crash        NIFTY fell 4% or more in a day, or India VIX jumped 30% or
               more in a day, on one of the last 3 trading days
* bear phase   NIFTY is 10% or more below its 1-year high AND under its
               200-day average
* correction   NIFTY is 5% or more below its 1-year high (not a bear phase)
* recovery     back within 5% of the high, after a fall of 10% or more in
               the last 60 trading days
* up-trend     the 50-day average is above the 200-day one and NIFTY is
               above the 50-day average
* sideways     none of the above

Fewer than 200 days of history → "unlabelled". Crash, bear phase (and an
unknown market, see novelty.py) suggest going careful. Pure.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

CRASH_DAY_FALL = -0.04
CRASH_VIX_JUMP = 0.30
CRASH_HOLD_DAYS = 3
CORRECTION = -0.05
BEAR = -0.10
RECOVERY_LOOKBACK = 60
MIN_HISTORY = 200
DEFENSIVE_LABELS = frozenset({"crash", "bear phase"})


@dataclass(frozen=True, slots=True)
class MarketLabel:
    label: str
    evidence: tuple[str, ...]
    suggest_defensive: bool
    confidence: float


def label_days(nifty: pd.Series, vix: pd.Series) -> pd.DataFrame:
    """One label per NIFTY day (index = dates), plus the numbers behind it."""
    close = nifty.astype(float)
    vix = vix.astype(float).reindex(close.index).ffill()
    ret1 = close.pct_change()
    vix_jump = vix.pct_change()
    crash_day = (ret1 <= CRASH_DAY_FALL) | (vix_jump >= CRASH_VIX_JUMP)
    crash = crash_day.astype(float).rolling(CRASH_HOLD_DAYS, min_periods=1).max().astype(bool)
    dd = close / close.rolling(252, min_periods=1).max() - 1
    sma50, sma200 = close.rolling(50).mean(), close.rolling(200).mean()
    worst_recent = dd.rolling(RECOVERY_LOOKBACK, min_periods=1).min()

    label = np.select(
        [
            sma200.isna(),
            crash,
            (dd <= BEAR) & (close < sma200),
            dd <= CORRECTION,
            (dd > CORRECTION) & (worst_recent <= BEAR),
            (sma50 > sma200) & (close > sma50),
        ],
        ["unlabelled", "crash", "bear phase", "correction", "recovery", "up-trend"],
        default="sideways",
    )
    return pd.DataFrame(
        {
            "label": label,
            "close": close,
            "ret1": ret1,
            "vix_jump": vix_jump,
            "dd": dd,
            "worst_recent": worst_recent,
            "sma50": sma50,
            "sma200": sma200,
            "crash_day": crash_day,
        },
        index=close.index,
    )


def _evidence(frame: pd.DataFrame) -> str:
    last = frame.iloc[-1]
    label = last["label"]
    if label == "crash":
        days = frame[frame["crash_day"]].tail(CRASH_HOLD_DAYS)
        day, row = days.index[-1], days.iloc[-1]
        if row["ret1"] <= CRASH_DAY_FALL:
            return f"NIFTY fell {-row['ret1']:.1%} on {day:%d %b %Y}."
        return f"India VIX jumped {row['vix_jump']:.0%} on {day:%d %b %Y} (fear spiking)."
    if label == "bear phase":
        return f"NIFTY is {-last['dd']:.0%} below its 1-year high and under its 200-day average."
    if label == "correction":
        return f"NIFTY is {-last['dd']:.0%} below its 1-year high."
    if label == "recovery":
        return (
            f"NIFTY is back within {-CORRECTION:.0%} of its high after falling "
            f"{-last['worst_recent']:.0%} in the last {RECOVERY_LOOKBACK} trading days."
        )
    if label == "up-trend":
        return "NIFTY is above its 50-day average, which is above its 200-day average."
    if label == "sideways":
        return "No clear direction: NIFTY is near its high but not trending."
    return "Not enough NIFTY history to name the market's situation."


def market_situation(nifty: pd.Series, vix: pd.Series) -> MarketLabel:
    if len(nifty) == 0:
        return MarketLabel("unlabelled", ("No NIFTY history.",), False, 0.0)
    frame = label_days(nifty, vix)
    label = str(frame["label"].iloc[-1])
    if label == "unlabelled":
        return MarketLabel(label, (_evidence(frame),), False, 0.0)
    return MarketLabel(label, (_evidence(frame),), label in DEFENSIVE_LABELS, 0.8)
