"""Model artifact persistence and lifecycle.

An artifact bundle is a single joblib file holding the fitted estimator, the
scaler, and the feature list. Keeping them together makes a version
self-contained: loading it cannot pick up a mismatched scaler or a feature
ordering that has since changed in the source.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import ModelStatus
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.ml import MLModel

log = get_logger(__name__)


def artifact_path(name: str, version: str) -> Path:
    return settings.model_dir / f"{name}_{version}.joblib"


def save_artifact(name: str, version: str, bundle: dict[str, Any]) -> str:
    path = artifact_path(name, version)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, path)
    log.info("model.artifact.saved", path=str(path))
    return str(path)


def load_artifact(path: str) -> dict[str, Any]:
    return joblib.load(path)


def next_version(db: Session, name: str) -> str:
    """Monotonic `vN` per model name — never reuses a number, even after
    deletions, so a version string always identifies one training run."""
    count = len(list(db.execute(select(MLModel).where(MLModel.name == name)).scalars().all()))
    return f"v{count + 1}"


def get_active_model(db: Session, name: str | None = None) -> MLModel | None:
    """The active model for one name.

    `name` is required whenever more than one model is active - and three
    normally are, one per cap tier, each serving its own strategy. This used
    to order by activated_at and take the newest, so a 22-millisecond
    difference in activation time decided which model answered a nameless
    lookup. `real_trading` passes model_name=None, which meant real Zerodha
    holdings were scored by the small-cap model whatever the stock was.

    Callers that genuinely want every tier use active_models() instead.
    Raising is deliberate: returning one arbitrary row is the behaviour being
    removed, and a silent wrong model is far worse than a loud stop.
    """
    stmt = select(MLModel).where(MLModel.status == ModelStatus.ACTIVE)
    if name:
        return db.execute(
            stmt.where(MLModel.name == name).order_by(MLModel.activated_at.desc()).limit(1)
        ).scalar_one_or_none()

    rows = list(db.execute(stmt.order_by(MLModel.name)).scalars().all())
    if len(rows) > 1:
        raise ValueError(
            f"{len(rows)} models are active ({', '.join(r.name for r in rows)}); "
            "the caller names a model or uses active_models()"
        )
    return rows[0] if rows else None


def active_models(db: Session) -> list[MLModel]:
    """Every active model, ordered by name.

    Ordered by name rather than by activation time so the list a status
    screen shows is stable between calls - the ordering that caused the bug
    above must not survive anywhere a human reads it.
    """
    return list(
        db.execute(
            select(MLModel).where(MLModel.status == ModelStatus.ACTIVE).order_by(MLModel.name)
        )
        .scalars()
        .all()
    )


def activate_model(db: Session, model_id: int) -> MLModel:
    """Promote one version and archive whatever it replaces.

    Demoting the incumbent in the same transaction guarantees there is never a
    window with two ACTIVE models of the same name — the inference path picks
    one arbitrarily, and "which model made this call" must stay answerable.
    """
    model = db.get(MLModel, model_id)
    if model is None:
        raise ValueError(f"Model {model_id} not found")
    if model.status not in (ModelStatus.TRAINED, ModelStatus.ARCHIVED):
        raise ValueError(f"Cannot activate a model with status {model.status}")

    db.query(MLModel).filter(
        MLModel.name == model.name,
        MLModel.status == ModelStatus.ACTIVE,
        MLModel.id != model_id,
    ).update({"status": ModelStatus.ARCHIVED})

    model.status = ModelStatus.ACTIVE
    model.activated_at = datetime.now(UTC)
    db.commit()
    db.refresh(model)
    log.info("model.activated", name=model.name, version=model.version)
    return model
