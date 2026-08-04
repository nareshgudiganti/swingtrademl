"""Model training.

Produces a binary classifier: will this instrument gain `target_return_pct`
within `prediction_horizon_days`? Probability output is what the strategy
thresholds on, so calibration matters more than raw accuracy.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.preprocessing import StandardScaler
from sqlalchemy.orm import Session

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import ModelStatus
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.ml import MLModel
from swing_trade_ml.ml.dataset import build_training_dataset, chronological_split
from swing_trade_ml.ml.features import FEATURE_COLUMNS
from swing_trade_ml.ml.registry import next_version, save_artifact

log = get_logger(__name__)


def _build_estimator(algorithm: str, hyperparameters: dict[str, Any] | None = None):
    """Instantiate the estimator.

    `class_weight="balanced"` throughout: only ~20-30% of bars precede a 2% move
    in five days, and an unweighted fit on that imbalance converges to
    predicting "no" every time — 75% accurate and completely useless.
    """
    hp = hyperparameters or {}
    seed = settings.ML_RANDOM_SEED

    if algorithm == "lightgbm":
        try:
            from lightgbm import LGBMClassifier
        except ImportError:
            log.warning("train.lightgbm_missing.fallback_to_gbdt")
            return _build_estimator("gradient_boosting", hp)
        return LGBMClassifier(
            n_estimators=hp.get("n_estimators", 400),
            learning_rate=hp.get("learning_rate", 0.05),
            max_depth=hp.get("max_depth", 6),
            num_leaves=hp.get("num_leaves", 31),
            subsample=hp.get("subsample", 0.8),
            colsample_bytree=hp.get("colsample_bytree", 0.8),
            # Financial features are noisy; a high leaf minimum stops the trees
            # carving out splits that fit a handful of coincidental bars.
            min_child_samples=hp.get("min_child_samples", 50),
            reg_alpha=hp.get("reg_alpha", 0.1),
            reg_lambda=hp.get("reg_lambda", 0.1),
            class_weight="balanced",
            random_state=seed,
            n_jobs=-1,
            verbose=-1,
        )

    if algorithm == "random_forest":
        return RandomForestClassifier(
            n_estimators=hp.get("n_estimators", 400),
            max_depth=hp.get("max_depth", 12),
            min_samples_leaf=hp.get("min_samples_leaf", 30),
            max_features=hp.get("max_features", "sqrt"),
            class_weight="balanced",
            random_state=seed,
            n_jobs=-1,
        )

    if algorithm == "gradient_boosting":
        return GradientBoostingClassifier(
            n_estimators=hp.get("n_estimators", 300),
            learning_rate=hp.get("learning_rate", 0.05),
            max_depth=hp.get("max_depth", 4),
            subsample=hp.get("subsample", 0.8),
            random_state=seed,
        )

    if algorithm == "logistic_regression":
        return LogisticRegression(
            C=hp.get("C", 1.0),
            max_iter=hp.get("max_iter", 2000),
            class_weight="balanced",
            random_state=seed,
        )

    raise ValueError(f"Unknown algorithm: {algorithm}")


def train_model(
    db: Session,
    name: str = "swing_classifier",
    algorithm: str = "lightgbm",
    symbols: list[str] | None = None,
    interval: str = "day",
    horizon_days: int | None = None,
    target_return: float | None = None,
    test_size: float | None = None,
    hyperparameters: dict[str, Any] | None = None,
    auto_activate: bool = False,
) -> MLModel:
    """Train, evaluate on a held-out future window, and register the result.

    The returned model is TRAINED, not ACTIVE, unless `auto_activate` is set.
    Promotion stays a deliberate act — during the paper phase a new model
    should be inspected before it starts generating signals.
    """
    horizon_days = horizon_days or settings.ML_PREDICTION_HORIZON_DAYS
    target_return = target_return if target_return is not None else settings.ML_TARGET_RETURN_PCT
    test_size = test_size if test_size is not None else settings.ML_TRAIN_TEST_SPLIT

    log.info("train.start", name=name, algorithm=algorithm, horizon=horizon_days)

    dataset = build_training_dataset(
        db, symbols=symbols, interval=interval,
        horizon_days=horizon_days, target_return=target_return,
    )
    if dataset.empty:
        raise ValueError(
            "No training data. Ingest historical candles first: "
            "POST /api/v1/market-data/backfill"
        )
    if len(dataset) < 1000:
        log.warning("train.small_dataset", rows=len(dataset))

    train_df, test_df = chronological_split(dataset, test_size)
    if test_df.empty:
        raise ValueError("Test split is empty — need more historical data")

    x_train = train_df[FEATURE_COLUMNS].to_numpy(dtype=np.float64)
    y_train = train_df["target"].to_numpy(dtype=np.int64)
    x_test = test_df[FEATURE_COLUMNS].to_numpy(dtype=np.float64)
    y_test = test_df["target"].to_numpy(dtype=np.int64)

    # Fitted on train only. Fitting the scaler on the full dataset would leak
    # the test period's mean and variance backwards into training.
    scaler = StandardScaler().fit(x_train)
    x_train_s, x_test_s = scaler.transform(x_train), scaler.transform(x_test)

    estimator = _build_estimator(algorithm, hyperparameters)
    estimator.fit(x_train_s, y_train)

    y_pred = estimator.predict(x_test_s)
    y_proba = (
        estimator.predict_proba(x_test_s)[:, 1]
        if hasattr(estimator, "predict_proba")
        else y_pred.astype(float)
    )

    metrics = {
        "accuracy": float(accuracy_score(y_test, y_pred)),
        # zero_division=0: an over-conservative model can predict no positives
        # at all, and that should score 0 rather than raise.
        "precision": float(precision_score(y_test, y_pred, zero_division=0)),
        "recall": float(recall_score(y_test, y_pred, zero_division=0)),
        "f1": float(f1_score(y_test, y_pred, zero_division=0)),
        "roc_auc": float(roc_auc_score(y_test, y_proba)) if len(set(y_test)) > 1 else 0.5,
        "train_rows": len(train_df),
        "test_rows": len(test_df),
        "train_positive_rate": float(y_train.mean()),
        "test_positive_rate": float(y_test.mean()),
        "confusion_matrix": confusion_matrix(y_test, y_pred).tolist(),
        "report": classification_report(y_test, y_pred, zero_division=0, output_dict=True),
    }

    # What the strategy actually experiences: among bars the model is confident
    # about, how often was it right? Headline precision at the 0.5 cut-off does
    # not describe the trades this system would take.
    threshold = settings.ML_MIN_CONFIDENCE
    confident = y_proba >= threshold
    metrics["confident_signal_count"] = int(confident.sum())
    metrics["precision_at_threshold"] = (
        float(y_test[confident].mean()) if confident.any() else 0.0
    )
    metrics["threshold"] = threshold

    importance = _feature_importance(estimator)

    version = next_version(db, name)
    path = save_artifact(
        name, version,
        {
            "estimator": estimator,
            "scaler": scaler,
            "feature_names": FEATURE_COLUMNS,
            "algorithm": algorithm,
            "horizon_days": horizon_days,
            "target_return": target_return,
        },
    )

    record = MLModel(
        name=name,
        version=version,
        algorithm=algorithm,
        status=ModelStatus.TRAINED,
        artifact_path=path,
        feature_names=FEATURE_COLUMNS,
        hyperparameters=hyperparameters or {},
        training_symbols=sorted(dataset["symbol"].unique().tolist()),
        train_start=pd.Timestamp(train_df["ts"].min()).to_pydatetime(),
        train_end=pd.Timestamp(train_df["ts"].max()).to_pydatetime(),
        n_samples=len(dataset),
        prediction_horizon_days=horizon_days,
        target_return_pct=target_return,
        accuracy=metrics["accuracy"],
        precision=metrics["precision"],
        recall=metrics["recall"],
        f1_score=metrics["f1"],
        roc_auc=metrics["roc_auc"],
        metrics=metrics,
        feature_importance=importance,
        trained_at=datetime.now(UTC),
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    log.info(
        "train.done",
        name=name, version=version,
        accuracy=round(metrics["accuracy"], 4),
        roc_auc=round(metrics["roc_auc"], 4),
        precision_at_threshold=round(metrics["precision_at_threshold"], 4),
    )

    if auto_activate:
        from swing_trade_ml.ml.registry import activate_model

        record = activate_model(db, record.id)

    return record


def _feature_importance(estimator) -> dict[str, float]:
    if hasattr(estimator, "feature_importances_"):
        values = estimator.feature_importances_
    elif hasattr(estimator, "coef_"):
        values = np.abs(estimator.coef_[0])
    else:
        return {}

    total = float(np.sum(values)) or 1.0
    pairs = sorted(
        ((name, float(v) / total) for name, v in zip(FEATURE_COLUMNS, values, strict=False)),
        key=lambda kv: kv[1],
        reverse=True,
    )
    return dict(pairs)
