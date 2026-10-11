"""Models and scores that are safe to use for a past day (brain replays).

A model trained with a cutoff only learned from rows whose outcome was known by that day,
and may only score days strictly after it.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.ml import MLModel
from swing_trade_ml.ml.dataset import load_candles
from swing_trade_ml.ml.features import build_features
from swing_trade_ml.ml.market_context import (
    load_index_candles,
    load_market_breadth,
    load_sector_candles,
    load_vix_candles,
)
from swing_trade_ml.ml.predict import _get_bundle
from swing_trade_ml.ml.sector_map import get_sector_index
from swing_trade_ml.ml.train import train_model

_IST = ZoneInfo("Asia/Kolkata")
MIN_BARS = 220  # the live path needs the same warm-up
_cache: dict[tuple[int, int], dict[date, float]] = {}


def asof_cutoff(model: Any) -> date | None:
    """The cutoff a model was trained with, or None for an ordinary (live) model."""
    raw = (getattr(model, "metrics", None) or {}).get("asof_cutoff")
    return date.fromisoformat(raw) if raw else None


def train_asof_model(db: Session, cutoff: date, symbols: list[str] | None = None, **kwargs) -> MLModel:
    """Train `swing_classifier_asof_<YYYYMMDD>` on data known by `cutoff`. Never activated."""
    kwargs.pop("auto_activate", None)
    return train_model(
        db,
        name=f"swing_classifier_asof_{cutoff:%Y%m%d}",
        symbols=symbols,
        cutoff=cutoff,
        auto_activate=False,
        **kwargs,
    )


def clear_cache() -> None:
    _cache.clear()


def score_series(db: Session, instrument: Instrument, model: MLModel, after: date) -> dict[date, float]:
    """Probability for every IST day strictly after `after` where the stock has at least
    MIN_BARS of history and a complete feature row. Features are built once from the full
    history; this equals cutting the data at each day only because the features are causal
    (tests/test_asof_scoring.py proves it)."""
    key = (model.id, instrument.id)
    if key not in _cache:
        _cache[key] = _score_all(db, instrument, model)
    return {d: p for d, p in _cache[key].items() if d > after}


def _score_all(db: Session, instrument: Instrument, model: MLModel) -> dict[date, float]:
    raw = load_candles(db, instrument.id, "day")
    if len(raw) < MIN_BARS:
        return {}
    bundle = _get_bundle(model)
    names: list[str] = bundle["feature_names"]
    featured = build_features(
        raw,
        load_index_candles(db, "day"),
        load_sector_candles(db, get_sector_index(instrument.tradingsymbol), "day"),
        load_vix_candles(db, "day"),
        load_market_breadth(db, "day"),
    )
    featured = featured.iloc[MIN_BARS - 1 :]
    x = featured[names]
    ok = ~x.isna().any(axis=1)
    if not ok.any():
        return {}
    scaled = bundle["scaler"].transform(x[ok].to_numpy(dtype=np.float64))
    est = bundle["estimator"]
    probs = est.predict_proba(scaled)[:, 1] if hasattr(est, "predict_proba") else est.predict(scaled)
    days = [pd.Timestamp(t).tz_convert(_IST).date() for t in featured.loc[ok, "ts"]]
    return {d: float(p) for d, p in zip(days, probs, strict=True)}
