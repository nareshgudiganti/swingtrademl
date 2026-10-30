# backend/src/swing_trade_ml/brain/lanes/h05_features.py
# ruff: noqa: E501, N812 (short P / R import aliases and long report sentences, as in brain/five_day.py)
"""Input values for the h05 lane: score a stock the way each SAVED model expects, and prove the feature code.

The saved models were trained in Aug 2026. One input, `obv_slope`, changed formula on 2026-10-05 (commit
fcaef35: the denominator moved from the OBV level to the typical daily volume). Replaying today's code on each
model's own training data reproduces the saved scalers for every other input, and reproduces `obv_slope` only
with the OLD formula on full history (see h05_parity). So the lane's primary score uses the old formula; the
production path (`ml.predict.predict_instrument`) is kept as a labelled diagnostic.

Nothing here edits a frozen file: it imports the feature builder and recomputes one column.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from swing_trade_ml.brain.lanes import h05_protocol as P
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.ml.dataset import load_candles
from swing_trade_ml.ml.features import build_features, on_balance_volume
from swing_trade_ml.ml.market_context import (
    load_index_candles,
    load_market_breadth,
    load_sector_candles,
    load_vix_candles,
)
from swing_trade_ml.ml.sector_map import get_sector_index

PACKAGE = Path(__file__).resolve().parents[2]  # .../swing_trade_ml


def feature_code_sha256() -> dict[str, str]:
    """sha256 of the code that builds and serves the inputs, line endings ignored (as the freeze test does)."""
    out = {}
    for rel in P.FEATURE_CODE_SHA256:
        out[rel] = hashlib.sha256((PACKAGE / rel).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    return out


def old_obv_slope(close: pd.Series, volume: pd.Series) -> pd.Series:
    """obv_slope as the saved models were trained: a 10-day OBV change over the 20-day mean OBV LEVEL.
    That level depends on how much history is loaded, which is why training used the full stored history."""
    obv = on_balance_volume(close, volume)
    return obv.diff(10) / obv.rolling(20).mean().abs().replace(0, np.nan)


@dataclass(frozen=True)
class BasisScore:
    probability: float
    ts: datetime
    price: float


def training_basis_frame(
    db: Session, instrument: Instrument, bars_limit: int | None = None
) -> pd.DataFrame | None:
    """The stock's feature rows, built from the FULL stored history (as the training set builder read it),
    with `obv_slope` in the training formula. `bars_limit` is for tests only."""
    df = load_candles(db, instrument.id, "day", limit=bars_limit)
    if len(df) < P.MIN_BARS:
        return None
    featured = build_features(
        df,
        load_index_candles(db, "day"),
        load_sector_candles(db, get_sector_index(instrument.tradingsymbol), "day"),
        load_vix_candles(db, "day"),
        load_market_breadth(db, "day"),
    ).copy()
    if len(featured) != len(df):  # the replacement column must line up row for row
        raise ValueError("feature rows and candles differ in length")
    featured["obv_slope"] = old_obv_slope(df["close"].astype(float), df["volume"].astype(float)).to_numpy()
    return featured


def score_training_basis(db: Session, instrument: Instrument, bundle: dict[str, Any]) -> BasisScore | None:
    """Probability from the saved model on the training-basis inputs for the newest bar.

    None when any input of THIS model is missing: nothing is imputed, as in training and in production."""
    featured = training_basis_frame(db, instrument)
    if featured is None:
        return None
    row = featured.iloc[[-1]]
    x = row[list(bundle["feature_names"])]
    if x.isna().to_numpy().any():
        return None
    scaled = bundle["scaler"].transform(x.to_numpy(dtype=np.float64))
    estimator = bundle["estimator"]
    p = (
        float(estimator.predict_proba(scaled)[0, 1])
        if hasattr(estimator, "predict_proba")
        else float(estimator.predict(scaled)[0])
    )
    ts = pd.Timestamp(row["ts"].iloc[0]).to_pydatetime()
    return BasisScore(p, ts, float(row["close"].iloc[0]))
