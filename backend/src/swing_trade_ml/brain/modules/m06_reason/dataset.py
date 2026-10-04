"""Build M06's training rows from history: for every stock and day in the
window the base models never saw, what the barrier model and the swing model
said, some market and stock context, and what really happened next (+8%
before -4% within 15 trading days).

Uses exactly the model pipeline's own code (`build_features`, `build_label`,
the saved model bundles), so the rows match what the models see live.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.brain.modules.m06_reason.trainer import unseen_rows
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.ml import MLModel
from swing_trade_ml.ml.dataset import load_candles
from swing_trade_ml.ml.features import build_features, build_label
from swing_trade_ml.ml.market_context import (
    load_index_candles,
    load_market_breadth,
    load_sector_candles,
    load_vix_candles,
)
from swing_trade_ml.ml.registry import load_artifact
from swing_trade_ml.ml.sector_map import get_sector_index

log = get_logger(__name__)
IST = ZoneInfo("Asia/Kolkata")
CONTEXT_COLUMNS = (
    "nifty_trend_regime",
    "breadth_pct_above_sma50",
    "vix_percentile_rank",
    "relative_strength_20d",
    "high_52w_dist",
    "sector_trend_regime",
)


def _batch_scores(bundle: dict, frame: pd.DataFrame) -> pd.Series:
    names = bundle["feature_names"]
    usable = frame[names].notna().all(axis=1)
    out = pd.Series(np.nan, index=frame.index)
    if usable.any():
        x = bundle["scaler"].transform(frame.loc[usable, names].to_numpy(dtype=np.float64))
        out.loc[usable] = bundle["estimator"].predict_proba(x)[:, 1]
    return out


def score_bundle(bundle: dict, features: dict[str, float]) -> float | None:
    """One stock's score from a saved model bundle and a feature mapping (a
    snapshot's features). None when any feature the model needs is missing."""
    names = bundle["feature_names"]
    values = [features.get(n) for n in names]
    if any(v is None or (isinstance(v, float) and np.isnan(v)) for v in values):
        return None
    x = bundle["scaler"].transform(np.asarray([values], dtype=np.float64))
    return float(bundle["estimator"].predict_proba(x)[0, 1])


def unseen_start(barrier: MLModel, swing: MLModel) -> pd.Timestamp:
    ends = [m.train_end for m in (barrier, swing) if m.train_end is not None]
    if not ends:
        raise ValueError("The base models have no recorded training end, so no window can be called unseen.")
    end = max(ends)
    end = end.astimezone(IST) if isinstance(end, datetime) and end.tzinfo else end
    return pd.Timestamp(end.date() if isinstance(end, datetime) else end)


def build_dataset(db: Session, barrier: MLModel, swing: MLModel, symbols: list[str]) -> pd.DataFrame:
    barrier_bundle, swing_bundle = load_artifact(barrier.artifact_path), load_artifact(swing.artifact_path)
    index_df, vix_df, breadth_df = load_index_candles(db), load_vix_candles(db), load_market_breadth(db)
    parts = []
    for symbol in symbols:
        inst = db.execute(
            select(Instrument).where(Instrument.tradingsymbol == symbol).order_by(Instrument.id).limit(1)
        ).scalar_one_or_none()
        if inst is None:
            continue
        candles = load_candles(db, inst.id, "day")
        if len(candles) < 260:
            log.info("brain.m06.dataset.short_history", symbol=symbol, rows=len(candles))
            continue
        featured = build_features(
            candles, index_df, load_sector_candles(db, get_sector_index(symbol)), vix_df, breadth_df
        )
        labelled = build_label(featured)
        frame = pd.DataFrame(
            {
                "day": pd.to_datetime(labelled["ts"], utc=True)
                .dt.tz_convert(IST)
                .dt.tz_localize(None)
                .dt.normalize(),
                "symbol": symbol,
                "p_barrier": _batch_scores(barrier_bundle, labelled),
                "p_swing": _batch_scores(swing_bundle, labelled),
                "target": labelled["target"].astype(int),
            }
        )
        for col in CONTEXT_COLUMNS:
            frame[col] = labelled[col].to_numpy()
        parts.append(frame.dropna(subset=["p_barrier", "p_swing"]))

    if not parts:
        return pd.DataFrame(columns=["day", "symbol", "p_barrier", "p_swing", "target", *CONTEXT_COLUMNS])
    data = pd.concat(parts, ignore_index=True).sort_values(["day", "symbol"]).reset_index(drop=True)
    return unseen_rows(data, unseen_start(barrier, swing))
