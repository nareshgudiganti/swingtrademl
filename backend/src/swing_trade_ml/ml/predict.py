"""Inference and prediction scoring.

The loaded artifact is cached per (model_id, artifact_path): deserialising a
few hundred trees on every instrument in the watchlist would dominate the scan.
Keying on the path as well means a re-trained artifact under the same id still
invalidates the entry.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.ml import MLModel, Prediction
from swing_trade_ml.ml.dataset import load_candles
from swing_trade_ml.ml.features import build_features
from swing_trade_ml.ml.market_context import load_index_candles
from swing_trade_ml.ml.registry import get_active_model, load_artifact

log = get_logger(__name__)

_artifact_cache: dict[tuple[int, str], dict[str, Any]] = {}


def _get_bundle(model: MLModel) -> dict[str, Any]:
    key = (model.id, model.artifact_path or "")
    if key not in _artifact_cache:
        if not model.artifact_path:
            raise ValueError(f"Model {model.name}:{model.version} has no artifact")
        _artifact_cache[key] = load_artifact(model.artifact_path)
        log.info("model.artifact.loaded", name=model.name, version=model.version)
    return _artifact_cache[key]


def clear_cache() -> None:
    _artifact_cache.clear()


@dataclass(slots=True)
class PredictionResult:
    instrument_id: int
    symbol: str
    probability: float
    predicted_class: int
    price: float
    ts: datetime
    features: dict[str, float]


def predict_instrument(
    db: Session, instrument: Instrument, model: MLModel, interval: str = "day"
) -> PredictionResult | None:
    """Score the most recent bar. Returns None when features are not ready.

    Requesting 400 bars covers the 252-period 52-week high with headroom, so
    the newest row has every indicator populated.
    """
    df = load_candles(db, instrument.id, interval, limit=400)
    if len(df) < 220:
        log.debug("predict.insufficient_history", symbol=instrument.tradingsymbol, rows=len(df))
        return None

    bundle = _get_bundle(model)
    feature_names: list[str] = bundle["feature_names"]

    index_df = load_index_candles(db, interval)
    featured = build_features(df, index_df)
    row = featured.iloc[[-1]]
    x = row[feature_names]
    if x.isna().to_numpy().any():
        # Indicators still warming up. Imputing here would feed the model a
        # vector unlike anything it trained on, so skip the instrument instead.
        log.debug("predict.nan_features", symbol=instrument.tradingsymbol)
        return None

    x_scaled = bundle["scaler"].transform(x.to_numpy(dtype=np.float64))
    estimator = bundle["estimator"]

    if hasattr(estimator, "predict_proba"):
        probability = float(estimator.predict_proba(x_scaled)[0, 1])
    else:
        probability = float(estimator.predict(x_scaled)[0])

    ts = pd.Timestamp(row["ts"].iloc[0]).to_pydatetime()
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)

    return PredictionResult(
        instrument_id=instrument.id,
        symbol=instrument.tradingsymbol,
        probability=probability,
        predicted_class=int(probability >= 0.5),
        price=float(row["close"].iloc[0]),
        ts=ts,
        features={k: float(v) for k, v in x.iloc[0].items()},
    )


def predict_watchlist(
    db: Session, model_name: str | None = None, interval: str = "day", persist: bool = True
) -> list[PredictionResult]:
    """Score every watchlisted instrument with the active model."""
    model = get_active_model(db, model_name)
    if model is None:
        log.warning("predict.no_active_model")
        return []

    instruments = list(
        db.execute(
            select(Instrument).where(
                Instrument.is_watchlisted.is_(True), Instrument.is_active.is_(True)
            )
        )
        .scalars()
        .all()
    )

    results: list[PredictionResult] = []
    for inst in instruments:
        try:
            result = predict_instrument(db, inst, model, interval)
        except Exception as exc:  # noqa: BLE001 — one bad symbol must not abort the scan
            log.error("predict.failed", symbol=inst.tradingsymbol, error=str(exc))
            continue
        if result is None:
            continue
        results.append(result)

        if persist:
            _upsert_prediction(db, model, result)

    if persist:
        db.commit()

    log.info("predict.batch_done", model=model.name, scored=len(results), total=len(instruments))
    return sorted(results, key=lambda r: r.probability, reverse=True)


def _upsert_prediction(db: Session, model: MLModel, result: PredictionResult) -> None:
    """Idempotent per (model, instrument, bar) so re-running a scan the same day
    updates rather than duplicating."""
    existing = db.execute(
        select(Prediction).where(
            Prediction.model_id == model.id,
            Prediction.instrument_id == result.instrument_id,
            Prediction.ts == result.ts,
        )
    ).scalar_one_or_none()

    if existing:
        existing.probability = result.probability
        existing.predicted_class = result.predicted_class
        existing.price_at_prediction = result.price
        existing.features = result.features
        return

    db.add(
        Prediction(
            model_id=model.id,
            instrument_id=result.instrument_id,
            ts=result.ts,
            predicted_class=result.predicted_class,
            probability=result.probability,
            price_at_prediction=result.price,
            features=result.features,
        )
    )


def evaluate_pending_predictions(db: Session, interval: str = "day") -> int:
    """Score past predictions whose horizon has now elapsed.

    This is the honest measure of the model: out-of-sample accuracy on calls it
    actually made, not on a held-out split from training time. It is what the
    six-month paper phase exists to accumulate.
    """
    now = datetime.now(UTC)
    evaluated = 0

    pending = list(
        db.execute(
            select(Prediction).where(Prediction.evaluated_at.is_(None)).order_by(Prediction.ts)
        )
        .scalars()
        .all()
    )

    for pred in pending:
        model = db.get(MLModel, pred.model_id)
        if model is None:
            continue

        horizon_end = pred.ts + timedelta(days=model.prediction_horizon_days)
        # Calendar days overshoot trading days; a small buffer avoids evaluating
        # before the market has actually produced the bars.
        if now < horizon_end + timedelta(days=2):
            continue

        future = db.execute(
            select(Candle.close)
            .where(
                Candle.instrument_id == pred.instrument_id,
                Candle.interval == interval,
                Candle.ts > pred.ts,
                Candle.ts <= horizon_end + timedelta(days=4),
            )
            .order_by(Candle.ts.desc())
            .limit(1)
        ).scalar_one_or_none()

        if future is None:
            continue

        actual_return = float(future) / pred.price_at_prediction - 1
        pred.actual_return = actual_return
        pred.was_correct = (actual_return >= model.target_return_pct) == bool(pred.predicted_class)
        pred.evaluated_at = now
        evaluated += 1

    if evaluated:
        db.commit()
        log.info("predict.evaluated", count=evaluated)
    return evaluated
