# ruff: noqa: E501
"""Model cards for the five-day and selection-lab training paths, written beside the file (#328 slice 2b).

`brain/five_day_train.py` and `brain/selection_lab.py` are protocol-frozen (fd-protocol-v1, sl-protocol), and so
are their callers, so none of them is edited. These wrappers call the untouched trainers, then write a card as
a sidecar `<artifact>.card.json`. The artifact bytes and the `ml_models` row are never changed.

The trainers keep their train/test frames to themselves, so the card is rebuilt from the saved row and file:
anything only the frames could tell (test window dates, training-matrix hash) is recorded as null, never guessed.
Nothing calls these wrappers yet; pointing the protected callers at them is a separate, owner-approved change.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.ml import model_card as mc
from swing_trade_ml.ml.registry import artifact_sha256, load_artifact

log = get_logger(__name__)

CARD_SUFFIX = ".card.json"


def sidecar_path(artifact_path: str | Path) -> Path:
    p = Path(artifact_path)
    return p.with_name(p.name + CARD_SUFFIX)


def card_from_record(model: Any, *, invoked_by: str | None, train_args: dict[str, Any]) -> dict[str, Any]:
    """The card for a trained row and its file. Unknown values are None."""
    metrics = model.metrics or {}
    names = list(model.feature_names or [])
    symbols = sorted(model.training_symbols) if model.training_symbols else None
    path = Path(model.artifact_path) if model.artifact_path else None
    file_ok = path is not None and path.is_file()
    estimator = load_artifact(str(path)).get("estimator") if file_ok else None
    fp = mc.feature_fingerprint(names)
    return {
        "card_version": mc.CARD_VERSION,
        "source": "rebuilt_from_saved_row_and_file_after_training",
        "model": {"name": model.name, "version": model.version},
        "feature_names": names,
        "feature_fingerprint": fp,
        "input_formula_version": f"features-{fp['fingerprint_sha256'][:12]}",
        "feature_code_sha256": mc.feature_code_sha256(),
        "git": mc.git_state(),
        "training": {
            "entry_point": "swing_trade_ml.brain.card_trainers",
            "invoked_by": invoked_by,
            "requested_algorithm": model.algorithm,
            "estimator_class": mc.estimator_class(estimator),
            "args": train_args,
            "seed": settings.ML_RANDOM_SEED,
        },
        "libraries": mc.library_versions(),
        "data_window": {
            "train_start": mc.iso_or_none(model.train_start),
            "train_end": mc.iso_or_none(model.train_end),
            "test_start": None,
            "test_end": None,
        },
        "universe": {
            "symbols": symbols,
            "symbols_sha256": None if symbols is None else mc.sha256_text("\n".join(symbols)),
        },
        "rows": {
            "dataset": model.n_samples,
            "train": metrics.get("train_rows"),
            "test": metrics.get("test_rows"),
        },
        "training_matrix_sha256": None,
        "label": {
            "horizon_days": model.prediction_horizon_days,
            "target_return": model.target_return_pct,
            "stop_return": model.stop_return_pct,
            "kind": model.label_kind,
            "description": metrics.get("label"),
        },
        "asof_cutoff": metrics.get("asof_cutoff"),
        "artifact_sha256": artifact_sha256(path) if file_ok else None,
    }


def write_card(model: Any, *, invoked_by: str | None, train_args: dict[str, Any]) -> dict[str, Any] | None:
    """Write the sidecar next to the artifact (never replacing one) and return the card.

    No card is written, and None is returned, when the row has no artifact file on disk."""
    if not model.artifact_path or not Path(model.artifact_path).is_file():
        log.warning("model_card.skipped_no_artifact", model=getattr(model, "name", None),
                    version=getattr(model, "version", None))
        return None
    card = card_from_record(model, invoked_by=invoked_by, train_args=train_args)
    target = sidecar_path(model.artifact_path)
    tmp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(card, indent=1, sort_keys=True), encoding="utf-8")
        os.link(tmp, target)  # fails if a card is already there
    finally:
        tmp.unlink(missing_ok=True)
    return card


def _write_card_quietly(model: Any, *, invoked_by: str | None, train_args: dict[str, Any]) -> None:
    """A card is a record about a finished model: if writing it fails, say so and keep the trained model."""
    try:
        write_card(model, invoked_by=invoked_by, train_args=train_args)
    except Exception as exc:  # noqa: BLE001 - never fail a finished training run over its card
        log.warning(
            "model_card.write_failed", model=getattr(model, "name", None),
            version=getattr(model, "version", None), error=type(exc).__name__,
        )


def train_endpoint_model_with_card(
    db, *, name: str, cutoff: date, horizon_days: int, target_return: float,
    test_size: float | None = None, invoked_by: str | None = None,
):
    """`five_day_train.train_endpoint_model`, unchanged, then a sidecar card."""
    from swing_trade_ml.brain.five_day_train import train_endpoint_model

    model = train_endpoint_model(
        db, name=name, cutoff=cutoff, horizon_days=horizon_days,
        target_return=target_return, test_size=test_size,
    )
    _write_card_quietly(
        model, invoked_by=invoked_by,
        train_args={
            "name": name, "cutoff": cutoff.isoformat(), "horizon_days": horizon_days,
            "target_return": target_return, "test_size": test_size,
        },
    )
    return model


def train_lab_model_with_card(db, *, invoked_by: str | None = None, **kwargs: Any):
    """`selection_lab.train_lab_model`, unchanged, then a sidecar card."""
    from swing_trade_ml.brain import selection_lab as sl

    model = sl.train_lab_model(db, **kwargs)
    cutoff = kwargs.get("cutoff")
    _write_card_quietly(
        model, invoked_by=invoked_by,
        train_args={
            "name": kwargs.get("name"),
            "cutoff": cutoff.isoformat() if cutoff is not None else None,
            "symbols_count": len(kwargs.get("symbols") or []),
            "candidates_count": len(kwargs.get("candidates") or []),
            "drop_unresolved": kwargs.get("drop_unresolved", False),
        },
    )
    return model
