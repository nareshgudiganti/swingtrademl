# backend/src/swing_trade_ml/brain/five_day_train.py
"""fd-protocol-v1 fold models: the endpoint question, trained next to v1 and not inside it.

The active 5-day prod models (ids 2, 16, 17) were trained on the old endpoint label: is the close
`horizon` trading days later at least `target` above today's close? `ml/` now builds only the
barrier label, and the v1 path stays untouched (CLAUDE.md principle 8), so this evidence-only
wrapper rebuilds the endpoint answer from the same dataset: `forward_return >= target`, the rule
`ml/predict.py` uses to grade endpoint predictions (and the pre-`dd1f4c4` `build_label`).

Everything else is imported from v1 as it is: `ml.dataset.build_training_dataset` (features, rows,
cutoff), `ml.dataset.chronological_split` (embargo), `ml.train.fit_and_score` and
`ml.train._feature_importance`, `ml.registry.next_version` / `save_artifact`. The model is
registered TRAINED (never activated) as label_kind "endpoint" with no stop.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd
from sqlalchemy.orm import Session

from swing_trade_ml.core.logging import get_logger

log = get_logger(__name__)

ALGORITHM = "lightgbm"  # train_model's default, what the fold models of wf-protocol-v1 use


def endpoint_target(dataset: pd.DataFrame, target_return: float) -> pd.DataFrame:
    """The endpoint answer in place of the barrier one: close `horizon` bars later >= +target."""
    return dataset.assign(target=(dataset["forward_return"] >= target_return).astype(int))


def train_endpoint_model(
    db: Session,
    *,
    name: str,
    cutoff: date,
    horizon_days: int,
    target_return: float,
    test_size: float | None = None,
):
    from swing_trade_ml.core.config import Settings
    from swing_trade_ml.core.enums import ModelStatus
    from swing_trade_ml.db.models.ml import MLModel
    from swing_trade_ml.ml.dataset import build_training_dataset, chronological_split
    from swing_trade_ml.ml.features import FEATURE_COLUMNS
    from swing_trade_ml.ml.registry import next_version, save_artifact
    from swing_trade_ml.ml.train import _feature_importance, fit_and_score

    # The code default (0.2), so a local .env cannot change the split.
    test_size = Settings.model_fields["ML_TRAIN_TEST_SPLIT"].default if test_size is None else test_size
    # The barrier stop only shapes the column this wrapper replaces; rows, features and cutoff
    # (label_end_ts = the bar `horizon_days` later) are the same for both labels.
    dataset = build_training_dataset(
        db, horizon_days=horizon_days, target_return=target_return, stop_return=0.04, cutoff=cutoff
    )
    if dataset.empty:
        raise ValueError("No training data for the endpoint fold model.")
    dataset = endpoint_target(dataset, target_return)
    train_df, test_df = chronological_split(dataset, test_size, embargo_days=horizon_days)
    if test_df.empty or train_df.empty or train_df["target"].nunique() < 2:
        raise ValueError("Not enough history for the endpoint fold model.")
    estimator, scaler, metrics = fit_and_score(train_df, test_df, ALGORITHM, None, False)
    metrics["embargo_days"] = horizon_days
    metrics["asof_cutoff"] = cutoff.isoformat()
    metrics["label"] = f"endpoint: forward_return >= {target_return} at {horizon_days} bars (fd-protocol-v1)"

    version = next_version(db, name)
    path = save_artifact(
        name,
        version,
        {
            "estimator": estimator,
            "scaler": scaler,
            "feature_names": FEATURE_COLUMNS,
            "algorithm": ALGORITHM,
            "horizon_days": horizon_days,
            "target_return": target_return,
            "stop_return": None,
            "label_kind": "endpoint",
            "calibrated": False,
        },
    )
    record = MLModel(
        name=name,
        version=version,
        algorithm=ALGORITHM,
        status=ModelStatus.TRAINED,
        artifact_path=path,
        feature_names=FEATURE_COLUMNS,
        hyperparameters={},
        training_symbols=sorted(dataset["symbol"].unique().tolist()),
        train_start=pd.Timestamp(train_df["ts"].min()).to_pydatetime(),
        train_end=pd.Timestamp(train_df["ts"].max()).to_pydatetime(),
        n_samples=len(dataset),
        prediction_horizon_days=horizon_days,
        target_return_pct=target_return,
        stop_return_pct=None,
        label_kind="endpoint",
        accuracy=metrics["accuracy"],
        precision=metrics["precision"],
        recall=metrics["recall"],
        f1_score=metrics["f1"],
        roc_auc=metrics["roc_auc"],
        metrics=metrics,
        feature_importance=_feature_importance(estimator),
        trained_at=datetime.now(UTC),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    log.info("five_day_train.done", name=name, version=version, roc_auc=round(metrics["roc_auc"], 4))
    return record
