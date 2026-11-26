# ruff: noqa: E501
"""Model cards for the five-day and selection-lab training paths, written beside the file (#328 slice 2b).

`brain/five_day_train.py` and `brain/selection_lab.py` are protocol-frozen (fd-protocol-v1, sl-protocol), and so
are their callers, so none of them is edited. These wrappers call the untouched trainers, then write a card as
a sidecar `<artifact>.card.json`. The artifact bytes and the `ml_models` row are never changed.

The trainers keep their train/test frames to themselves, so the card is rebuilt from the saved row and file:
anything only the frames could tell (test window dates, training-matrix hash) is recorded as null, never guessed.
`shadow_lanes/lane_freeze.py` (not protocol-frozen) trains its lab candidates through the lab wrapper. The
protected callers (the five-day and selection-lab protocol runners) stay as they are: pointing them here needs the owner and
a new protocol tag. For models trained without a card (older ones, or a run that stopped after saving the
file), `backfill_missing_cards` finds them and writes one; `python -m swing_trade_ml.brain.card_trainers
backfill --dry-run` lists them.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from collections.abc import Iterable
from datetime import UTC, date, datetime
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


def card_from_record(
    model: Any,
    *,
    invoked_by: str | None,
    train_args: dict[str, Any],
    source: str = "rebuilt_from_saved_row_and_file_after_training",
) -> dict[str, Any]:
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
        "source": source,
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


def write_card(
    model: Any,
    *,
    invoked_by: str | None,
    train_args: dict[str, Any],
    source: str | None = None,
) -> dict[str, Any] | None:
    """Write the sidecar next to the artifact (never replacing one) and return the card.

    No card is written, and None is returned, when the row has no artifact file on disk."""
    if not model.artifact_path or not Path(model.artifact_path).is_file():
        log.warning(
            "model_card.skipped_no_artifact",
            model=getattr(model, "name", None),
            version=getattr(model, "version", None),
        )
        return None
    extra = {"source": source} if source else {}
    card = card_from_record(model, invoked_by=invoked_by, train_args=train_args, **extra)
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
            "model_card.write_failed",
            model=getattr(model, "name", None),
            version=getattr(model, "version", None),
            error=type(exc).__name__,
        )


# ---------------------------------------------------------------- re-runs, crashes and repair

BACKFILL_SOURCE = "backfilled_from_saved_row_and_file"
#: what `write_card` leaves behind if the process is killed between writing its temp file and removing it
_STALE_TMP = re.compile(r"^\..+" + re.escape(CARD_SUFFIX) + r"\.[0-9a-f]{32}\.tmp$")


def card_state(artifact_path: str | Path | None) -> str:
    """'no_artifact', 'missing' (file but no card), 'ok' (card names this file's sha256) or 'mismatch'
    (card unreadable, or it names different bytes). Reads only."""
    if not artifact_path or not Path(artifact_path).is_file():
        return "no_artifact"
    side = sidecar_path(artifact_path)
    if not side.exists():
        return "missing"
    try:
        recorded = json.loads(side.read_text(encoding="utf-8")).get("artifact_sha256")
    except (OSError, ValueError, AttributeError):
        return "mismatch"
    return "ok" if recorded and recorded == artifact_sha256(artifact_path) else "mismatch"


def ensure_card(
    model: Any,
    *,
    invoked_by: str | None,
    train_args: dict[str, Any],
    source: str | None = None,
) -> str:
    """Safe to call any number of times: writes the card only when there is none. Returns 'written',
    'present', 'mismatch' (an existing card is left untouched) or 'no_artifact'."""
    state = card_state(model.artifact_path)
    if state != "missing":
        return "present" if state == "ok" else state
    try:
        write_card(model, invoked_by=invoked_by, train_args=train_args, source=source)
    except FileExistsError:  # another writer got there first; judge what it wrote
        state = card_state(model.artifact_path)
        return "present" if state == "ok" else state
    return "written"


def stale_temp_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.is_file() and _STALE_TMP.match(p.name))


def backfill_missing_cards(
    models: Iterable[Any],
    *,
    dry_run: bool = False,
    repair: bool = False,
    invoked_by: str = "backfill",
) -> dict[str, Any]:
    """Find models whose file has no card (e.g. the run stopped after saving the file) and write one.

    Model files are only read. Rows that already carry their card in `metrics["card"]` (ml/train.py) are
    skipped. A card that does not match its file is reported; with `repair=True` it is renamed to
    `<card>.bad-<UTC time>` (kept, never deleted) and a fresh card is written. Leftover temp files from a
    killed writer are listed and, unless `dry_run`, removed. Re-running finds nothing more to do."""
    report: dict[str, Any] = {
        "dry_run": dry_run,
        "written": [],
        "missing": [],
        "present": [],
        "card_in_row": [],
        "no_artifact": [],
        "mismatch": [],
        "repaired": [],
        "stale_temp_files": [],
        "failed": [],
    }
    folders: set[Path] = set()
    for model in models:
        label = f"{model.name} {model.version}"
        if model.artifact_path:
            folders.add(Path(model.artifact_path).parent)
        if isinstance(model.metrics, dict) and model.metrics.get("card"):
            report["card_in_row"].append(label)
            continue
        state = card_state(model.artifact_path)
        if state == "no_artifact":
            report["no_artifact"].append(label)
        elif state == "ok":
            report["present"].append(label)
        elif state == "mismatch" and not (repair and not dry_run):
            report["mismatch"].append(label)
        elif dry_run:
            report["missing"].append(label)
        else:
            try:
                if state == "mismatch":
                    side = sidecar_path(model.artifact_path)
                    side.rename(side.with_name(f"{side.name}.bad-{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}"))
                write_card(
                    model, invoked_by=invoked_by, train_args={"backfill": True}, source=BACKFILL_SOURCE
                )
                report["repaired" if state == "mismatch" else "written"].append(label)
            except Exception as exc:  # noqa: BLE001 - report it and carry on with the other models
                log.warning("model_card.backfill_failed", model=label, error=type(exc).__name__)
                report["failed"].append(label)
    for folder in sorted(folders):
        for tmp in stale_temp_files(folder):
            report["stale_temp_files"].append(tmp.name)
            if not dry_run:
                tmp.unlink(missing_ok=True)
    return report


def backfill_from_db(db, **kwargs: Any) -> dict[str, Any]:
    """`backfill_missing_cards` over every registered model. Reads the database, never writes it."""
    from sqlalchemy import select

    from swing_trade_ml.db.models.ml import MLModel

    rows = db.execute(select(MLModel).order_by(MLModel.name, MLModel.version)).scalars().all()
    return backfill_missing_cards(rows, **kwargs)


def train_endpoint_model_with_card(
    db,
    *,
    name: str,
    cutoff: date,
    horizon_days: int,
    target_return: float,
    test_size: float | None = None,
    invoked_by: str | None = None,
):
    """`five_day_train.train_endpoint_model`, unchanged, then a sidecar card."""
    from swing_trade_ml.brain.five_day_train import train_endpoint_model

    model = train_endpoint_model(
        db,
        name=name,
        cutoff=cutoff,
        horizon_days=horizon_days,
        target_return=target_return,
        test_size=test_size,
    )
    _write_card_quietly(
        model,
        invoked_by=invoked_by,
        train_args={
            "name": name,
            "cutoff": cutoff.isoformat(),
            "horizon_days": horizon_days,
            "target_return": target_return,
            "test_size": test_size,
        },
    )
    return model


def train_lab_model_with_card(db, *, invoked_by: str | None = None, **kwargs: Any):
    """`selection_lab.train_lab_model`, unchanged, then a sidecar card."""
    from swing_trade_ml.brain import selection_lab as sl

    model = sl.train_lab_model(db, **kwargs)
    cutoff = kwargs.get("cutoff")
    _write_card_quietly(
        model,
        invoked_by=invoked_by,
        train_args={
            "name": kwargs.get("name"),
            "cutoff": cutoff.isoformat() if cutoff is not None else None,
            "symbols_count": len(kwargs.get("symbols") or []),
            "candidates_count": len(kwargs.get("candidates") or []),
            "drop_unresolved": kwargs.get("drop_unresolved", False),
        },
    )
    return model


def main(argv: list[str] | None = None) -> int:
    """python -m swing_trade_ml.brain.card_trainers backfill [--dry-run] [--repair]"""
    parser = argparse.ArgumentParser(
        description="Find and write missing model cards (model files are only read)"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backfill")
    b.add_argument("--dry-run", action="store_true", help="list what is missing; write nothing")
    b.add_argument("--repair", action="store_true", help="also replace cards that do not match their file")
    args = parser.parse_args(argv)
    from swing_trade_ml.db.session import session_scope

    with session_scope() as db:
        report = backfill_from_db(db, dry_run=args.dry_run, repair=args.repair)
    for key in ("written", "repaired", "missing", "mismatch", "no_artifact", "failed", "stale_temp_files"):
        print(f"{key}: {len(report[key])}" + (f"  {', '.join(report[key])}" if report[key] else ""))
    print(f"present: {len(report['present'])}  card_in_row: {len(report['card_in_row'])}")
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
