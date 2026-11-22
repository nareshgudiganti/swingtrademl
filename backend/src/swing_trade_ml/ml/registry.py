"""Model artifact persistence and lifecycle.

An artifact bundle is a single joblib file holding the fitted estimator, the
scaler, and the feature list. Keeping them together makes a version
self-contained: loading it cannot pick up a mismatched scaler or a feature
ordering that has since changed in the source.
"""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import ModelStatus
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.ml import MLModel

log = get_logger(__name__)


def artifact_path(name: str, version: str) -> Path:
    return settings.model_dir / f"{name}_{version}.joblib"


class ArtifactMismatchError(ValueError):
    """The model file is missing, or is not the file its ml_models row describes."""


class ArtifactPublishError(OSError):
    """The model folder cannot publish a finished file in one step without replacing an existing one."""


def name_lock_key(name: str) -> int:
    """A stable 63-bit Postgres advisory-lock key for one model name."""
    return int.from_bytes(hashlib.sha256(f"ml_models:{name}".encode()).digest()[:8], "big") >> 1


def _lock_name(db: Session, name: str) -> None:
    """Serialise version allocation and activation per model name until the transaction ends.

    Held by the caller's transaction, so a second trainer of the same name waits until the first has
    committed its row, then sees that version as taken. Other databases (none in use) skip the lock."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": name_lock_key(name)})


def save_artifact(name: str, version: str, bundle: dict[str, Any]) -> str:
    """Write the bundle to `{name}_{version}.joblib`, never replacing an existing file.

    The file is written under a temporary name first and then published in one step, so a reader never
    sees half a file and a second writer of the same version gets FileExistsError instead of overwriting.
    The bundle records its own name and version so a file can be checked against its row later."""
    path = artifact_path(name, version)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        joblib.dump({**bundle, "model_name": name, "model_version": version}, tmp)
        try:
            os.link(tmp, path)  # atomic, and fails if the target exists
        except FileExistsError:
            raise
        except OSError as exc:
            # No one-step no-replace publish on this filesystem. Copying into the final name would make an
            # empty or half-written model visible under it (and a kill mid-copy would leave it there), so stop
            # before the final name exists. The model folder must be on a filesystem with hard links.
            raise ArtifactPublishError(
                f"cannot publish {path.name}: the model folder {path.parent} does not support hard links "
                f"({type(exc).__name__}); nothing was written under the final name"
            ) from exc
    finally:
        tmp.unlink(missing_ok=True)
    log.info("model.artifact.saved", path=str(path))
    return str(path)


def artifact_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def load_artifact(path: str) -> dict[str, Any]:
    return joblib.load(path)


def load_model_artifact(model: MLModel) -> dict[str, Any]:
    """Load a model's file only if it is the file its row describes; otherwise raise ArtifactMismatchError.

    Checks: a path is recorded and the file exists; its sha256 equals metrics["artifact_sha256"] when one
    was recorded (models trained before 2026-11-18 have none and skip only this check); the name and version
    the file records, when present, match the row; and its input list equals the row's feature_names."""
    who = f"{model.name} {model.version}"
    if not model.artifact_path:
        raise ArtifactMismatchError(f"{who}: no model file is recorded")
    path = Path(model.artifact_path)
    try:
        is_file = path.is_file()
        expected = (model.metrics or {}).get("artifact_sha256")
        hash_differs = is_file and isinstance(expected, str) and artifact_sha256(path) != expected
    except OSError as exc:  # permission denied, disk error: a refusal, never a crash; no path in the message
        raise ArtifactMismatchError(
            f"{who}: model file could not be read ({path.name}, {type(exc).__name__})"
        ) from exc
    if not is_file:
        raise ArtifactMismatchError(f"{who}: model file is missing ({path.name})")
    if hash_differs:
        raise ArtifactMismatchError(f"{who}: model file hash does not match the recorded hash")
    try:
        bundle = load_artifact(str(path))
    except Exception as exc:  # truncated or not a model file; older files have no hash to catch it earlier
        raise ArtifactMismatchError(f"{who}: model file could not be read ({type(exc).__name__})") from exc
    if not isinstance(bundle, dict):
        raise ArtifactMismatchError(f"{who}: model file could not be read (not a model bundle)")
    named = (bundle.get("model_name"), bundle.get("model_version"))
    if named != (None, None) and named != (model.name, model.version):
        raise ArtifactMismatchError(f"{who}: model file belongs to {named[0]} {named[1]}")
    if list(bundle.get("feature_names") or []) != list(model.feature_names or []):
        raise ArtifactMismatchError(f"{who}: model file inputs differ from the recorded inputs")
    return bundle


_VERSION_RE = re.compile(r"^v(\d+)$")


def next_version(db: Session, name: str) -> str:
    """Monotonic `vN` per model name — never reuses a number, even after deletions, so a version string
    always identifies one training run.

    Takes the per-name lock for the rest of the caller's transaction: commit the new row in the same
    transaction. One past the highest number in use (never below the row count, so odd version strings
    cannot lower it), skipping any number whose file is already on disk (left by a run that crashed
    before saving its row)."""
    _lock_name(db, name)
    versions = db.execute(select(MLModel.version).where(MLModel.name == name)).scalars().all()
    numbers = [int(m.group(1)) for v in versions if (m := _VERSION_RE.match(v or ""))]
    n = max([*numbers, len(versions)]) + 1
    while artifact_path(name, f"v{n}").exists():
        n += 1
    return f"v{n}"


def get_active_model(db: Session, name: str | None = None) -> MLModel | None:
    stmt = select(MLModel).where(MLModel.status == ModelStatus.ACTIVE)
    if name:
        stmt = stmt.where(MLModel.name == name)
    return db.execute(stmt.order_by(MLModel.activated_at.desc()).limit(1)).scalar_one_or_none()


def activate_model(db: Session, model_id: int) -> MLModel:
    """Promote one version and archive whatever it replaces.

    Demoting the incumbent in the same transaction guarantees there is never a
    window with two ACTIVE models of the same name — the inference path picks
    one arbitrarily, and "which model made this call" must stay answerable.
    The per-name lock stops two concurrent activations both winning, and the
    file is checked against its row first (ArtifactMismatchError, a ValueError).
    """
    model = db.get(MLModel, model_id)
    if model is None:
        raise ValueError(f"Model {model_id} not found")
    _lock_name(db, model.name)
    db.refresh(model)  # re-read under the lock: another activation may have just changed it
    if model.status not in (ModelStatus.TRAINED, ModelStatus.ARCHIVED):
        raise ValueError(f"Cannot activate a model with status {model.status}")
    # Never promote a file that is missing or is not the one this row describes; the incumbent stays.
    load_model_artifact(model)

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
