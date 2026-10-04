"""Turn a stock's bars into the brain's Snapshot.

The features are exactly the model's own (`ml.features.FEATURE_COLUMNS`,
computed by `latest_feature_row`), so whatever the brain stores is what the
model saw. Three plain facts ride along, computed from the same bars: the
close, the 14-day average true range, and the 20-day average traded value.

Pure: the caller passes bars and market-context frames that already end at
the run's date, which is what keeps a replay free of look-ahead.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import pandas as pd

from swing_trade_ml.brain.contracts import Snapshot
from swing_trade_ml.ml.features import FEATURE_COLUMNS, atr, latest_feature_row

IST = ZoneInfo("Asia/Kolkata")
ADV_DAYS = 20


@dataclass(frozen=True, slots=True)
class ContextFrames:
    index: pd.DataFrame
    sector: pd.DataFrame
    vix: pd.DataFrame
    breadth: pd.DataFrame


def feature_set_version() -> str:
    """Changes whenever the model's feature list changes, so a stored snapshot
    can always be matched to the model that could read it."""
    return hashlib.sha1(",".join(FEATURE_COLUMNS).encode()).hexdigest()[:12]


def snapshot_from(symbol: str, bars: pd.DataFrame, frames: ContextFrames, version: str) -> Snapshot | None:
    """None when there is too little history for the indicators to warm up."""
    if bars.empty:
        return None
    row = latest_feature_row(bars, frames.index, frames.sector, frames.vix, frames.breadth)
    if row is None:
        return None
    last = bars.iloc[-1]
    tail = bars.tail(ADV_DAYS)
    atr_14 = atr(bars["high"], bars["low"], bars["close"], 14).iloc[-1]
    return Snapshot(
        symbol=symbol,
        as_of=pd.Timestamp(last["ts"]).tz_convert(IST).date().isoformat(),
        close=float(last["close"]),
        atr_14=None if pd.isna(atr_14) else float(atr_14),
        adv_inr_20=float((tail["close"] * tail["volume"]).mean()),
        features=tuple((name, float(row[name].iloc[0])) for name in FEATURE_COLUMNS),
        feature_set_version=version,
    )
