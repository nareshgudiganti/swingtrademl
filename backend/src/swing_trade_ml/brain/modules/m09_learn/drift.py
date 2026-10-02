"""M09 learning loop, task 3: feature drift — a population stability index
(PSI) comparing the features the active model learnt on with the features
the brain sees now.

Pure: `psi`, `feature_drift`, `drift_lines`, `collapse_one_per_day` take
arrays/frames the caller already built; no side effects, no database.
`drift_report` is the DB service that builds those frames from the active
model's training window (reference) and `feature_snapshots` (recent).
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.brain.modules.m02_perception.snapshot import feature_set_version
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
# Fewer distinct recent bar dates than this isn't "recent history" — the real
# check DB once held `feature_snapshots` for a single bar date across 60
# stocks, which made the stability index compare one sample against itself.
MIN_RECENT_DAYS = 15
# A market-wide feature has only one value a day (every stock sees the same
# number), so it needs far more days before `psi` has the 50 values it wants.
MARKET_WIDE_RECENT_DAYS = 60

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

# These three repeat the same value for every stock on a given day (the
# market's situation, not the stock's). Comparing them row-by-row like the
# others would make `psi` think it has 60x the independent evidence it
# actually does, so they are collapsed to one row a day before comparison.
MARKET_WIDE: frozenset[str] = frozenset(
    {"vix_percentile_rank", "breadth_pct_above_sma50", "nifty_trend_regime"}
)
STOCK_FEATURES: tuple[str, ...] = tuple(f for f in KEY_FEATURES if f not in MARKET_WIDE)


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

# The owner has no finance/ML background, so a drift line never names a raw
# feature column — it reads in plain English instead.
_PLAIN_FEATURE_NAMES = {
    "rsi_14": "short-term momentum (RSI)",
    "sma_50_ratio": "distance from the 50-day average",
    "sma_200_ratio": "distance from the 200-day average",
    "high_52w_dist": "distance from the 1-year high",
    "relative_strength_20d": "strength against NIFTY over 20 days",
    "vix_percentile_rank": "market fear level (India VIX)",
    "breadth_pct_above_sma50": "share of stocks in an up-trend",
    "nifty_trend_regime": "NIFTY's trend",
}


def _plain_feature_name(feature: str) -> str:
    """The plain name, capitalised for the start of a sentence."""
    name = _PLAIN_FEATURE_NAMES.get(feature, feature)
    return name[0].upper() + name[1:]


def drift_lines(drift: list[dict]) -> list[str]:
    """Plain lines for every feature that has drifted at least moderately;
    a stable feature says nothing (it would just be noise)."""
    return [
        f"{_plain_feature_name(d['feature'])} has shifted {_WORDING[d['level']]} from what the model "
        f"learnt on (stability index {d['psi']:.2f})."
        for d in drift
        if d["level"] in _WORDING
    ]


def collapse_one_per_day(frame: pd.DataFrame, day_col: str) -> pd.DataFrame:
    """One row per distinct value of `day_col`. For a market-wide feature
    every row on the same day carries the same value, so keeping every row
    would overcount how much evidence there really is; the particular row
    kept for a day does not matter since the market-wide columns agree."""
    if frame.empty or day_col not in frame.columns:
        return frame.iloc[0:0]
    return frame.drop_duplicates(subset=[day_col]).reset_index(drop=True)


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
    reproducible. Carries a `day` column (the IST day of each bar) so
    `collapse_one_per_day` can group the market-wide features by day; every
    other feature simply ignores the extra column.

    Unlike `build_dataset`, this does not skip symbols with under 260 bars of
    history: `psi` already drops NaN values on each side, and the training-
    window filter below already keeps only the rows that matter, so a
    short-history symbol just contributes fewer rows here rather than
    needing its own gate."""
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
        in_window = featured[(day >= start) & (day <= end)].copy()
        if not in_window.empty:
            in_window["day"] = day[in_window.index]
            parts.append(in_window)

    if not parts:
        return pd.DataFrame()
    reference = pd.concat(parts, ignore_index=True)
    if len(reference) > MAX_REFERENCE_ROWS:
        reference = reference.sample(n=MAX_REFERENCE_ROWS, random_state=REFERENCE_SEED)
    return reference


def _recent_dates(db: Session, limit: int) -> list:
    """The most recent `limit` distinct `feature_snapshots` bar dates,
    newest first."""
    return list(
        db.execute(
            select(FeatureSnapshot.bar_date).distinct().order_by(FeatureSnapshot.bar_date.desc()).limit(limit)
        ).scalars()
    )


def recent_bar_date_count(db: Session, limit: int = MIN_RECENT_DAYS) -> int:
    """How many distinct recent bar dates `feature_snapshots` holds, capped
    at `limit` — just enough for the learning report to say why `drift_report`
    came back empty when there simply is not enough history yet."""
    return len(_recent_dates(db, limit))


def _recent_frame(db: Session, dates: list) -> pd.DataFrame:
    """One row per `feature_snapshots` row on these bar dates, one column per
    feature plus `bar_date` (so `collapse_one_per_day` can group the
    market-wide features) — only the current feature-set version, so a
    snapshot from a retired feature list is never compared against today's
    model. `features` is stored as either a JSON mapping or a list of
    (name, value) pairs (M02 stores a tuple, which JSON round-trips as a list
    of pairs) — `dict(...)` accepts either form."""
    if not dates:
        return pd.DataFrame()
    rows = db.execute(
        select(FeatureSnapshot.bar_date, FeatureSnapshot.features).where(
            FeatureSnapshot.bar_date.in_(dates),
            FeatureSnapshot.feature_set_version == feature_set_version(),
        )
    ).all()
    return pd.DataFrame([{**dict(features), "bar_date": bar_date} for bar_date, features in rows])


def drift_report(db: Session, model_name: str = "swing_classifier", recent_days: int = 20) -> list[dict]:
    """How far the features the brain sees now have drifted from what
    `model_name`'s active version learnt on. [] when there is no active
    model, or fewer than `MIN_RECENT_DAYS` distinct recent bar dates — one
    bar day's snapshots are one sample, not recent history, and `psi` on them
    is noise rather than a signal."""
    model = get_active_model(db, model_name)
    if model is None:
        return []
    dates = _recent_dates(db, recent_days)
    if len(dates) < MIN_RECENT_DAYS:
        return []
    recent = _recent_frame(db, dates)
    if recent.empty:
        return []
    reference = _reference_frame(db, model)

    drift = feature_drift(reference, recent, STOCK_FEATURES)

    # The market-wide features get their own, longer window and are
    # collapsed to one row a day on both sides before comparison; until that
    # longer window actually holds 50+ days, `psi` naturally skips them (too
    # few values), rather than this function needing a separate gate.
    market_dates = _recent_dates(db, MARKET_WIDE_RECENT_DAYS)
    recent_market = collapse_one_per_day(_recent_frame(db, market_dates), "bar_date")
    reference_market = collapse_one_per_day(reference, "day")
    drift += feature_drift(reference_market, recent_market, tuple(MARKET_WIDE))

    drift.sort(key=lambda d: d["psi"], reverse=True)
    return drift
