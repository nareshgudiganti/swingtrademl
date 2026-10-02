"""M09 learning loop, task 3: feature drift — a population stability index
(PSI) comparing the features the active model learnt on with the features
the brain sees now.

Pure: `psi`, `feature_drift`, `drift_lines` take arrays/frames the caller
already built; no side effects, no database. `drift_report` is the DB
service that builds those frames from the active model's training window
(reference) and `feature_snapshots` (recent).
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.db.models.brain import FeatureSnapshot
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.ml.dataset import load_candles
from swing_trade_ml.ml.features import build_features
from swing_trade_ml.ml.market_context import (
    load_index_candles,
    load_market_breadth,
    load_sector_candles,
    load_vix_candles,
)
from swing_trade_ml.ml.registry import get_active_model
from swing_trade_ml.ml.sector_map import get_sector_index

IST = ZoneInfo("Asia/Kolkata")
MIN_ROWS = 50
MAX_REFERENCE_ROWS = 20_000
REFERENCE_SEED = 42

KEY_FEATURES = (
    "rsi_14",
    "sma_50_ratio",
    "sma_200_ratio",
    "high_52w_dist",
    "relative_strength_20d",
    "vix_percentile_rank",
    "breadth_pct_above_sma50",
    "nifty_trend_regime",
)


def psi(reference: np.ndarray, recent: np.ndarray, bins: int = 10) -> float | None:
    """Population stability index between two samples of the same feature.

    Bin edges are the reference's own quantiles (deduplicated, so a feature
    with many repeated values still gets usable bins); the outer edges are
    opened to -inf/+inf so a recent value that has drifted outside the
    reference's whole range still lands in the nearest bin instead of being
    dropped. A small `eps` is added to every share before the log so an
    empty bin on either side never divides by zero. None when either side
    has fewer than 50 non-NaN values — too little to say anything."""
    ref = pd.Series(reference).dropna().to_numpy(dtype=np.float64)
    rec = pd.Series(recent).dropna().to_numpy(dtype=np.float64)
    if len(ref) < MIN_ROWS or len(rec) < MIN_ROWS:
        return None

    edges = np.unique(np.quantile(ref, np.linspace(0, 1, bins + 1)))
    if len(edges) < 2:
        return 0.0  # the reference has no spread at all; nothing to compare
    edges = edges.copy()
    edges[0], edges[-1] = -np.inf, np.inf

    ref_counts, _ = np.histogram(ref, bins=edges)
    rec_counts, _ = np.histogram(rec, bins=edges)
    eps = 1e-4
    ref_share = ref_counts / len(ref) + eps
    rec_share = rec_counts / len(rec) + eps
    return float(np.sum((rec_share - ref_share) * np.log(rec_share / ref_share)))


def _level(value: float) -> str:
    if value < 0.1:
        return "stable"
    if value < 0.25:
        return "moderate"
    return "major"


def feature_drift(
    reference: pd.DataFrame, recent: pd.DataFrame, features: tuple[str, ...] = KEY_FEATURES
) -> list[dict]:
    """PSI per feature the model relies on, most-drifted first. A feature
    missing from either side (or with too few values to score) is skipped
    rather than reported as a false "stable"."""
    out = []
    for feature in features:
        if feature not in reference.columns or feature not in recent.columns:
            continue
        value = psi(reference[feature].to_numpy(), recent[feature].to_numpy())
        if value is None:
            continue
        out.append({"feature": feature, "psi": value, "level": _level(value)})
    out.sort(key=lambda d: d["psi"], reverse=True)
    return out


_WORDING = {"moderate": "a little", "major": "a lot"}


def drift_lines(drift: list[dict]) -> list[str]:
    """Plain lines for every feature that has drifted at least moderately;
    a stable feature says nothing (it would just be noise)."""
    return [
        f"{d['feature']} has shifted {_WORDING[d['level']]} from what the model learnt on "
        f"(stability index {d['psi']:.2f})."
        for d in drift
        if d["level"] in _WORDING
    ]


def _watchlist(db: Session) -> list[str]:
    return list(
        db.execute(
            select(Instrument.tradingsymbol)
            .where(Instrument.is_watchlisted.is_(True), Instrument.is_active.is_(True))
            .order_by(Instrument.tradingsymbol)
        ).scalars()
    )


def _reference_frame(db: Session, model) -> pd.DataFrame:
    """`build_features(...)` rows for every watch-listed instrument, kept to
    the bars whose IST trading day falls inside the active model's own
    training window — exactly as `m06_reason.dataset.build_dataset` loads
    context, so the comparison is apples to apples. Capped at
    `MAX_REFERENCE_ROWS`, sampled with a fixed seed so the report is
    reproducible."""
    if model.train_start is None or model.train_end is None:
        return pd.DataFrame()
    start = model.train_start.astimezone(IST).date()
    end = model.train_end.astimezone(IST).date()

    index_df, vix_df, breadth_df = load_index_candles(db), load_vix_candles(db), load_market_breadth(db)
    parts = []
    for symbol in _watchlist(db):
        inst = db.execute(
            select(Instrument).where(Instrument.tradingsymbol == symbol).order_by(Instrument.id).limit(1)
        ).scalar_one_or_none()
        if inst is None:
            continue
        candles = load_candles(db, inst.id, "day")
        if candles.empty:
            continue
        featured = build_features(
            candles, index_df, load_sector_candles(db, get_sector_index(symbol)), vix_df, breadth_df
        )
        day = pd.to_datetime(featured["ts"], utc=True).dt.tz_convert(IST).dt.date
        in_window = featured[(day >= start) & (day <= end)]
        if not in_window.empty:
            parts.append(in_window)

    if not parts:
        return pd.DataFrame()
    reference = pd.concat(parts, ignore_index=True)
    if len(reference) > MAX_REFERENCE_ROWS:
        reference = reference.sample(n=MAX_REFERENCE_ROWS, random_state=REFERENCE_SEED)
    return reference


def _recent_frame(db: Session, recent_days: int) -> pd.DataFrame:
    """One row per `feature_snapshots` row from the last `recent_days`
    distinct bar dates, one column per feature. `features` is stored as
    either a JSON mapping or a list of (name, value) pairs (M02 stores a
    tuple, which JSON round-trips as a list of pairs) — `dict(...)` accepts
    either form."""
    dates = (
        db.execute(
            select(FeatureSnapshot.bar_date)
            .distinct()
            .order_by(FeatureSnapshot.bar_date.desc())
            .limit(recent_days)
        )
        .scalars()
        .all()
    )
    if not dates:
        return pd.DataFrame()
    rows = (
        db.execute(select(FeatureSnapshot.features).where(FeatureSnapshot.bar_date.in_(dates)))
        .scalars()
        .all()
    )
    return pd.DataFrame([dict(row) for row in rows])


def drift_report(db: Session, model_name: str = "swing_classifier", recent_days: int = 20) -> list[dict]:
    """How far the features the brain sees now have drifted from what
    `model_name`'s active version learnt on. [] when there is no active
    model, or no recent snapshots to compare against."""
    model = get_active_model(db, model_name)
    if model is None:
        return []
    recent = _recent_frame(db, recent_days)
    if recent.empty:
        return []
    reference = _reference_frame(db, model)
    return feature_drift(reference, recent)
