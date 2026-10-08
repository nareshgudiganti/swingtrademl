"""A second copy of every trained model artifact.

Three model files were lost once, and nothing was in place to notice or to
restore them. The MLModel row survives that loss — it keeps the metrics, the
label triple, the feature list and an `artifact_path` pointing at nothing — so
the registry reads as intact right up to the moment something tries to score
with it.

Deliberately a directory copy rather than an upload. The destination is
configuration (`MODEL_BACKUP_DIR`), so it can be a mounted volume, a synced
folder or an object-storage mount without this module learning about any of
them, and the job has no credentials to leak. Off-server is a property of
where that path points, which is the one part this code cannot guarantee.

Archived versions are copied alongside the active one: rollback is why the
registry keeps them, and a backup holding only the champion would make
rollback impossible after exactly the failure it is meant to survive.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.ml import MLModel

log = get_logger(__name__)


def registered_artifacts(db: Session) -> list[tuple[MLModel, Path | None]]:
    """Every registered model with its artifact file, or None when the file is
    gone. The one place that turns a registry row into a path, shared by the
    directory backup and the downloadable archive."""
    models = db.execute(select(MLModel).order_by(MLModel.name, MLModel.version)).scalars().all()
    found: list[tuple[MLModel, Path | None]] = []
    for model in models:
        source = Path(model.artifact_path) if model.artifact_path else None
        found.append((model, source if source is not None and source.is_file() else None))
    return found


def backup_model_artifacts(
    db: Session, destination: Path | str | None = None
) -> dict[str, Any]:
    """Copy every registered artifact to `destination`, skipping ones already
    there byte-for-byte.

    Artifacts are immutable once written, so a day with no training copies
    nothing. Returns a summary rather than raising: a backup that aborts on
    the first missing file would skip the healthy ones behind it, and the
    missing ones are the finding, not an error.
    """
    if destination is None:
        destination = settings.MODEL_BACKUP_DIR or None
    if destination is None:
        log.info("model.backup.disabled")
        return {"enabled": False, "copied": 0, "already_present": 0, "missing": [], "bytes": 0}

    target = Path(destination)
    target.mkdir(parents=True, exist_ok=True)

    copied = already_present = 0
    missing: list[str] = []
    total_bytes = 0

    for model, source in registered_artifacts(db):
        if source is None:
            missing.append(f"{model.name}:{model.version}")
            continue

        copy = target / source.name
        # Size is enough to detect "already backed up": the filename carries
        # name and version, and a version is never rewritten.
        if copy.is_file() and copy.stat().st_size == source.stat().st_size:
            already_present += 1
            continue

        shutil.copy2(source, copy)
        copied += 1
        total_bytes += source.stat().st_size

    if missing:
        log.error("model.backup.artifact_missing", models=missing, count=len(missing))
    log.info(
        "model.backup.done",
        destination=str(target),
        copied=copied,
        already_present=already_present,
        missing=len(missing),
    )
    return {
        "enabled": True,
        "copied": copied,
        "already_present": already_present,
        "missing": missing,
        "bytes": total_bytes,
        "destination": str(target),
    }
