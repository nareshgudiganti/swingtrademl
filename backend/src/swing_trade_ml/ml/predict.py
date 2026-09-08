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
from sqlalchemy.dialects.postgresql import insert as pg_insert
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
    db: Session, model_name: str | None = "swing_classifier", interval: str = "day", persist: bool = True
) -> list[PredictionResult]:
    """Score every watchlisted instrument with the active model.

    Defaults to "swing_classifier" rather than None, because the watchlist IS
    the large-cap universe by definition — falling through to "whichever
    model was most recently activated across every strategy" silently let a
    mid-cap or small-cap promotion shadow this for over a week (see Aug 12
    incident). Pass model_name=None explicitly if that global-latest lookup
    is ever genuinely wanted.
    """
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
    updates rather than duplicating.

    A real database-level upsert, not a Python check-then-insert — the
    latter raced two concurrent callers (e.g. the scheduled scan and a
    manual "Refresh now" click landing close together): both would see "no
    existing row" before either committed, both would try to INSERT, and
    whichever committed second crashed the whole batch on the unique
    constraint instead of just updating. ON CONFLICT is atomic at the
    database level, so this can't happen regardless of what else is
    writing predictions at the same time.
    """
    stmt = pg_insert(Prediction).values(
        model_id=model.id,
        instrument_id=result.instrument_id,
        ts=result.ts,
        predicted_class=result.predicted_class,
        probability=result.probability,
        price_at_prediction=result.price,
        features=result.features,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Prediction.model_id, Prediction.instrument_id, Prediction.ts],
        set_={
            "predicted_class": stmt.excluded.predicted_class,
            "probability": stmt.excluded.probability,
            "price_at_prediction": stmt.excluded.price_at_prediction,
            "features": stmt.excluded.features,
        },
    )
    db.execute(stmt)


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

        actual_return = forward_return_at_horizon(
            db, pred.instrument_id, pred.ts, pred.price_at_prediction,
            model.prediction_horizon_days, interval, now,
        )
        if actual_return is None:
            continue

        pred.actual_return = actual_return
        pred.was_correct = (actual_return >= model.target_return_pct) == bool(pred.predicted_class)
        pred.evaluated_at = now
        evaluated += 1

    if evaluated:
        db.commit()
        log.info("predict.evaluated", count=evaluated)
    return evaluated


def forward_return_at_horizon(
    db: Session,
    instrument_id: int,
    ts: datetime,
    price_at_ts: float,
    horizon_days: int,
    interval: str = "day",
    now: datetime | None = None,
) -> float | None:
    """Actual return from ts to ts+horizon_days, or None if that much time
    (plus a trading-day buffer) hasn't elapsed yet, or no candle exists near
    the horizon end. Calendar days overshoot trading days, so the nearest bar
    within a 4-day window past the horizon is used rather than an exact date
    match. Shared by evaluate_pending_predictions (which locks a prediction's
    outcome in at the model's own trained horizon, once) and
    accuracy_at_horizon (which asks "what if" at an arbitrary horizon,
    read-only, as many times as asked).
    """
    now = now or datetime.now(UTC)
    horizon_end = ts + timedelta(days=horizon_days)
    if now < horizon_end + timedelta(days=2):
        return None

    future = db.execute(
        select(Candle.close)
        .where(
            Candle.instrument_id == instrument_id,
            Candle.interval == interval,
            Candle.ts > ts,
            Candle.ts <= horizon_end + timedelta(days=4),
        )
        .order_by(Candle.ts.desc())
        .limit(1)
    ).scalar_one_or_none()
    if future is None:
        return None
    return float(future) / price_at_ts - 1


@dataclass(slots=True)
class HorizonAccuracy:
    horizon_days: int
    target_return: float
    total_predictions: int
    evaluable: int
    correct: int
    accuracy: float
    avg_actual_return: float


def accuracy_at_horizon(
    db: Session,
    horizon_days: int,
    target_return: float | None = None,
    model_id: int | None = None,
    interval: str = "day",
) -> HorizonAccuracy:
    """Re-score every prediction a model has made against an arbitrary
    horizon, entirely read-only — nothing is written to the predictions
    table. This answers "would this model have looked accurate if we'd
    judged it on X days instead of the horizon it was trained for", using
    the same forward-return lookup evaluate_pending_predictions uses to lock
    in the real (permanent) outcome at the model's own horizon.
    """
    model = db.get(MLModel, model_id) if model_id else get_active_model(db)
    if model is None:
        raise ValueError("No model to evaluate")
    target_return = model.target_return_pct if target_return is None else target_return

    predictions = list(
        db.execute(select(Prediction).where(Prediction.model_id == model.id)).scalars().all()
    )
    now = datetime.now(UTC)

    evaluable = 0
    correct = 0
    returns: list[float] = []
    for pred in predictions:
        actual_return = forward_return_at_horizon(
            db, pred.instrument_id, pred.ts, pred.price_at_prediction, horizon_days, interval, now
        )
        if actual_return is None:
            continue
        evaluable += 1
        returns.append(actual_return)
        if (actual_return >= target_return) == bool(pred.predicted_class):
            correct += 1

    return HorizonAccuracy(
        horizon_days=horizon_days,
        target_return=target_return,
        total_predictions=len(predictions),
        evaluable=evaluable,
        correct=correct,
        accuracy=(correct / evaluable) if evaluable else 0.0,
        avg_actual_return=(sum(returns) / len(returns)) if returns else 0.0,
    )
