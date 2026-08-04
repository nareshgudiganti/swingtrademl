"""ML model registry and stored predictions.

The registry exists so a model is never an anonymous file on disk. Six months
from now, "why did the bot buy INFY on 12 March" has to be answerable — that
needs the exact model version, its feature list, and the probability it emitted,
all recorded at the time.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from swing_trade_ml.core.enums import ModelStatus
from swing_trade_ml.db.base import Base, TimestampMixin


class MLModel(Base, TimestampMixin):
    """One trained model version.

    Exactly one row per (name) may have status ACTIVE — that is the model the
    live signal path loads. Promotion is a status flip, so rolling back a bad
    model is one UPDATE rather than a redeploy.
    """

    __tablename__ = "ml_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    version: Mapped[str] = mapped_column(String(32))
    # lightgbm | random_forest | logistic_regression | gradient_boosting
    algorithm: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default=ModelStatus.TRAINING, index=True)

    # Path to the joblib bundle. Local dir now, S3/GCS URI after cloud migration.
    artifact_path: Mapped[str | None] = mapped_column(String(512))

    # Reproducibility: the exact inputs that produced this artifact
    feature_names: Mapped[list[str]] = mapped_column(JSON, default=list)
    hyperparameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    training_symbols: Mapped[list[str]] = mapped_column(JSON, default=list)
    train_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    train_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    n_samples: Mapped[int | None] = mapped_column(Integer)

    # Label definition — a model trained on a different horizon is a different
    # model, and comparing their metrics without this recorded is meaningless
    prediction_horizon_days: Mapped[int] = mapped_column(Integer, default=5)
    target_return_pct: Mapped[float] = mapped_column(Float, default=0.02)

    # Held-out metrics. Precision matters most here: a false BUY costs money,
    # a missed BUY only costs opportunity.
    accuracy: Mapped[float | None] = mapped_column(Float)
    precision: Mapped[float | None] = mapped_column(Float)
    recall: Mapped[float | None] = mapped_column(Float)
    f1_score: Mapped[float | None] = mapped_column(Float)
    roc_auc: Mapped[float | None] = mapped_column(Float)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    feature_importance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    notes: Mapped[str | None] = mapped_column(Text)
    trained_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    predictions: Mapped[list[Prediction]] = relationship(back_populates="model")

    __table_args__ = (UniqueConstraint("name", "version", name="uq_ml_models_name_version"),)

    @property
    def is_active(self) -> bool:
        return self.status == ModelStatus.ACTIVE

    def __repr__(self) -> str:
        return f"<MLModel {self.name}:{self.version} {self.status} auc={self.roc_auc}>"


class Prediction(Base):
    """One model output for one instrument at one point in time.

    `actual_return` and `was_correct` start null and are backfilled by a job
    once the horizon has elapsed. That turns this table into the live
    scoreboard: real out-of-sample accuracy, measured on the predictions the
    bot actually made rather than on a held-out split.
    """

    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("ml_models.id", ondelete="CASCADE"), index=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id", ondelete="CASCADE"), index=True)

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    predicted_class: Mapped[int] = mapped_column(Integer)  # 1 = expected up-move
    probability: Mapped[float] = mapped_column(Float)
    price_at_prediction: Mapped[float] = mapped_column(Float)

    features: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # Backfilled after the prediction horizon passes
    actual_return: Mapped[float | None] = mapped_column(Float)
    was_correct: Mapped[bool | None] = mapped_column(Boolean, index=True)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    model: Mapped[MLModel] = relationship(back_populates="predictions")
    instrument: Mapped[Any] = relationship("Instrument")

    __table_args__ = (
        UniqueConstraint("model_id", "instrument_id", "ts", name="uq_predictions_model_inst_ts"),
        Index("ix_predictions_pending_eval", "evaluated_at", "ts"),
    )

    def __repr__(self) -> str:
        return f"<Prediction inst={self.instrument_id} p={self.probability:.3f} @{self.ts}>"
