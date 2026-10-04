"""Past cases: for every stock-day, its situation key and what happened next.

Outcome — the locked rule, with exactly `ml.features.build_label`'s
conventions: entry at the day's close; +8% target against -4% stop within
15 trading bars; a bar touching both counts as the stop; the last 15 days
have no case (their outcome is not known yet). Each case also records the
day its outcome became known (`outcome_day`: the hit, or day 15), the day
its whole 15-day path was known (`path_day`), its exit return (+8%, -4% or
the day-15 close) and the 15 daily closes relative to entry (`path`).

Key — four plain parts, each from data available on that day:
  market  M04's market label for the day
  stock   the stock's trend as M03 reads it: up (close > 50-day > 200-day
          average), down (the reverse) or sideways; none before 200 days
  trend   its last 20 days: falling hard (<= -8%), falling, flat (within 2%),
          rising, rising fast (>= +8%)
  vol     its 14-day average true range as a share of price: low (< 1.5%),
          normal (< 3%), high
Pure.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from swing_trade_ml.ml.features import atr

HORIZON = 15
TARGET = 0.08
STOP = 0.04


def barrier_outcomes(bars: pd.DataFrame) -> pd.DataFrame:
    close = bars["close"].to_numpy(float)
    high = bars["high"].to_numpy(float)
    low = bars["low"].to_numpy(float)
    days = list(bars["day"])
    n = len(bars) - HORIZON
    if n <= 0:
        return pd.DataFrame(
            columns=["day", "outcome", "exit_return", "days", "outcome_day", "path_day", "path"]
        )

    rows = []
    for i in range(n):
        entry = close[i]
        outcome, k_hit, exit_return = "timeout", HORIZON, close[i + HORIZON] / entry - 1
        for k in range(1, HORIZON + 1):
            stop = low[i + k] <= entry * (1 - STOP)
            target = high[i + k] >= entry * (1 + TARGET)
            if stop:  # a same-bar touch of both is a stop
                outcome, k_hit, exit_return = "stop", k, -STOP
                break
            if target:
                outcome, k_hit, exit_return = "target", k, TARGET
                break
        rows.append(
            {
                "day": days[i],
                "outcome": outcome,
                "exit_return": float(exit_return),
                "days": k_hit,
                "outcome_day": days[i + k_hit],
                "path_day": days[i + HORIZON],
                "path": [float(close[i + k] / entry - 1) for k in range(1, HORIZON + 1)],
            }
        )
    return pd.DataFrame(rows)


def _trend_bucket(r: float) -> str | None:
    if np.isnan(r):
        return None
    if r <= -0.08:
        return "falling hard"
    if r <= -0.02:
        return "falling"
    if r < 0.02:
        return "flat"
    if r < 0.08:
        return "rising"
    return "rising fast"


def _vol_bucket(v: float) -> str | None:
    if np.isnan(v):
        return None
    return "low" if v < 0.015 else "normal" if v < 0.03 else "high"


def state_keys(bars: pd.DataFrame, market_labels: pd.Series) -> pd.DataFrame:
    close = bars["close"].astype(float).reset_index(drop=True)
    sma50, sma200 = close.rolling(50).mean(), close.rolling(200).mean()
    stock = np.where(
        sma200.isna(),
        None,
        np.where(
            (close > sma50) & (sma50 > sma200),
            "up",
            np.where((close < sma50) & (sma50 < sma200), "down", "sideways"),
        ),
    )
    ret20 = close.pct_change(20)
    vol = (
        atr(
            bars["high"].astype(float).reset_index(drop=True),
            bars["low"].astype(float).reset_index(drop=True),
            close,
            14,
        )
        / close
    )
    return pd.DataFrame(
        {
            "day": list(bars["day"]),
            "market": [market_labels.get(d) for d in bars["day"]],
            "stock": stock,
            "trend": [_trend_bucket(r) for r in ret20],
            "vol": [_vol_bucket(v) for v in vol],
        }
    )


def build_cases(symbol: str, bars: pd.DataFrame, market_labels: pd.Series) -> pd.DataFrame:
    keys = state_keys(bars, market_labels)
    cases = keys.merge(barrier_outcomes(bars), on="day", how="inner")
    cases = cases.dropna(subset=["stock", "trend", "vol", "market"])
    cases = cases[cases["market"] != "unlabelled"]
    cases.insert(0, "symbol", symbol)
    return cases.reset_index(drop=True)
