# ruff: noqa: E501, N818 (long explanatory lines; VersionConflict / InvalidChange read better without an Error suffix)
"""Model registry, phase 1: a read view over models the app already has, plus the owner's research notes.

Reads `ml_models` and `strategies`; the only write is `update_slot`, which touches `model_research_slots`
and the audit log. It imports nothing from the brain, from model training or from model activation, and
nothing in the brain, strategies, ml or workers imports it.

Honesty rules, each covered by a test:
- A model sits in a slot only when its name is on the verified list below AND its horizon is 5, 10 or 15.
  Everything else is Unassigned. A name is never guessed into a cap group.
- Registry status (the `ml_models` row) and strategy usage (which active strategies load it) are two separate
  facts. An ACTIVE row does not imply a strategy uses it.
- Only stored provenance is shown. A value that is not stored is "Unknown", never invented, and the model
  file is never read or hashed here.
- A metric nobody measured is None ("Not measured"), never 0.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from swing_trade_ml.core.plans import BASE_MODEL
from swing_trade_ml.db.base import utcnow
from swing_trade_ml.db.models.ml import MLModel
from swing_trade_ml.db.models.registry import ModelResearchSlot
from swing_trade_ml.db.models.session import User
from swing_trade_ml.db.models.trading import Strategy
from swing_trade_ml.ml.real_question import resolve_model_name
from swing_trade_ml.services import audit

HORIZONS = (15, 10, 5)
TIERS = ("large", "midcap", "smallcap")

#: The only model names mapped to a cap group. Exact matches; no suffix guessing.
VERIFIED_NAMES: dict[str, str] = {
    "swing_classifier": "large",
    "swing_classifier_midcap": "midcap",
    "swing_classifier_smallcap": "smallcap",
}

#: Descriptive labels. None of them means validated, and none of them starts or enables anything.
RESEARCH_STATUSES = ("not_started", "researching", "paused", "dropped")
MAX_NOTE = 2000
MAX_PRIORITY = 9

NOT_MEASURED = "Not measured"


class VersionConflict(Exception):
    """The slot changed since the caller read it."""

    def __init__(self, current: dict[str, Any]):
        super().__init__("slot changed")
        self.current = current


class InvalidChange(ValueError):
    pass


def slot_key(horizon: int, tier: str) -> str:
    return f"{horizon}d-{tier}"


def all_slot_keys() -> list[str]:
    return [slot_key(h, t) for h in HORIZONS for t in TIERS]


def slot_for(name: str | None, horizon: int | None) -> str | None:
    """The slot a model belongs to, or None (Unassigned). Strict: exact verified name and a known horizon."""
    if name not in VERIFIED_NAMES or horizon not in HORIZONS:
        return None
    return slot_key(horizon, VERIFIED_NAMES[name])


def _fingerprint(values: list[Any]) -> str | None:
    if not values:
        return None
    return hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()


def calibration_status(metrics: Any) -> str:
    """Calibrated only when the training run recorded it. A model with no recorded metrics is Unknown."""
    if not isinstance(metrics, dict) or not metrics:
        return "Unknown"
    return "Calibrated" if metrics.get("calibration") else "No calibration recorded"


def provenance(m: MLModel) -> dict[str, Any]:
    metrics = m.metrics if isinstance(m.metrics, dict) else {}
    features = list(m.feature_names or [])
    symbols = sorted(m.training_symbols or [])
    stored_file_fp = metrics.get("artifact_sha256")
    return {
        "model_id": m.id,
        "name": m.name,
        "version": m.version,
        "algorithm": m.algorithm,
        "horizon_days": m.prediction_horizon_days,
        "target_return_pct": m.target_return_pct,
        "stop_return_pct": m.stop_return_pct,
        "label_kind": m.label_kind,
        "n_inputs": len(features) or None,
        # Computed from the stored lists (small, cheap, deterministic); not from the model file.
        "inputs_fingerprint": _fingerprint(features),
        "n_training_symbols": len(symbols) or None,
        "training_universe_fingerprint": _fingerprint(symbols),
        "n_samples": m.n_samples,
        "train_start": m.train_start.isoformat() if m.train_start else None,
        "train_end": m.train_end.isoformat() if m.train_end else None,
        "trained_at": m.trained_at.isoformat() if m.trained_at else None,
        "calibration": calibration_status(m.metrics),
        # Only a fingerprint stored at training time counts. The file is never read here.
        "model_file_fingerprint": stored_file_fp if isinstance(stored_file_fp, str) else "Unknown",
    }


def evidence(m: MLModel) -> dict[str, Any]:
    """Historical evidence only; each field says what it is. Forward evidence is read by the page elsewhere."""
    metrics = m.metrics if isinstance(m.metrics, dict) else {}
    return {
        "historical": {
            "held_out_auc": {
                "label": "Held-out AUC (one historical split; not top-5 performance)",
                "value": m.roc_auc,
            },
            "precision_at_threshold": {
                "label": "Precision at threshold (historical split)",
                "value": metrics.get("precision_at_threshold"),
            },
            "top5_ranking": {"label": "Top-5 ranking performance", "value": None, "note": NOT_MEASURED},
            "net_return_after_costs": {
                "label": "Net return after costs",
                "value": None,
                "note": NOT_MEASURED,
            },
            "drawdown": {"label": "Drawdown", "value": None, "note": NOT_MEASURED},
        },
        "forward": {
            "label": "Forward evidence",
            "value": None,
            "note": "Read from the 5-day test report, not here",
        },
    }


def active_strategy_usage(db: Session) -> dict[str, list[dict[str, Any]]] | None:
    """model name -> active ml_swing strategies that load it. None when strategies cannot be read.

    A strategy loads the ACTIVE version of the name it resolves to (the same resolution the strategy itself
    uses), so this is a statement about names; the caller attaches it only to the ACTIVE version.
    """
    try:
        rows = db.execute(
            select(Strategy).where(Strategy.is_active.is_(True), Strategy.strategy_type == "ml_swing")
        ).scalars()
        usage: dict[str, list[dict[str, Any]]] = {}
        for s in rows:
            name = resolve_model_name((s.params or {}).get("model_name") or BASE_MODEL)
            usage.setdefault(name or BASE_MODEL, []).append(
                {"strategy": s.name, "mode": s.mode, "execution_mode": s.execution_mode}
            )
        return usage
    except SQLAlchemyError:
        return None


def model_view(m: MLModel, usage: dict[str, list[dict[str, Any]]] | None) -> dict[str, Any]:
    if usage is None:
        used_by: list[dict[str, Any]] | None = None  # Unknown
    elif m.status == "ACTIVE":
        used_by = usage.get(m.name, [])
    else:
        used_by = []  # only the ACTIVE version of a name is ever loaded
    return {
        "slot": slot_for(m.name, m.prediction_horizon_days),
        "provenance": provenance(m),
        # Two separate facts, never merged into one label.
        "registry_status": m.status,
        "active_strategies": used_by,
        "active_strategies_note": (
            "Unknown (strategies could not be read)"
            if used_by is None
            else "Strategies that name this model and are switched on. A model with status ACTIVE may have none."
        ),
        "evidence": evidence(m),
    }


def _row_out(r: ModelResearchSlot) -> dict[str, Any]:
    return {
        "slot_key": r.slot_key,
        "horizon_days": r.horizon_days,
        "cap_tier": r.cap_tier,
        "research_status": r.research_status,
        "priority": r.priority,
        "note": r.note,
        "version": r.version,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        "updated_by": r.updated_by,
    }


def _order(r: ModelResearchSlot) -> tuple:
    """Deterministic: priority 1..9 first (ties broken by horizon then size), unranked last in the same order."""
    return (
        r.priority is None,
        r.priority if r.priority is not None else 0,
        -r.horizon_days,
        TIERS.index(r.cap_tier) if r.cap_tier in TIERS else len(TIERS),
        r.slot_key,
    )


def list_slots(db: Session) -> dict[str, Any]:
    slots = sorted(db.execute(select(ModelResearchSlot)).scalars().all(), key=_order)
    usage = active_strategy_usage(db)
    models = (
        db.execute(select(MLModel).order_by(MLModel.created_at.desc(), MLModel.id.desc())).scalars().all()
    )
    by_slot: dict[str, list[dict[str, Any]]] = {}
    unassigned: list[dict[str, Any]] = []
    for m in models:
        v = model_view(m, usage)
        (by_slot.setdefault(v["slot"], []) if v["slot"] else unassigned).append(v)
    return {
        "ordering": "priority 1 first, unranked last; equal priorities by longer horizon, then large, mid, small",
        "slots": [
            {**_row_out(r), "rank": i + 1, "models": by_slot.get(r.slot_key, [])} for i, r in enumerate(slots)
        ],
        "unassigned": unassigned,
        "statuses": list(RESEARCH_STATUSES),
        "status_note": "Research status is a descriptive label. It does not mean validated and starts nothing.",
    }


def get_model(db: Session, model_id: int) -> dict[str, Any] | None:
    m = db.get(MLModel, model_id)
    return None if m is None else model_view(m, active_strategy_usage(db))


@dataclass(frozen=True)
class Change:
    priority_set: bool = False
    priority: int | None = None
    status: str | None = None
    note_set: bool = False
    note: str | None = None


def update_slot(
    db: Session,
    key: str,
    expected_version: int,
    change: Change,
    actor: User | None,
    actor_label: str | None = None,
) -> dict[str, Any]:
    """Change a slot's priority, status or note. Compare-and-set on `version`: a stale caller gets VersionConflict."""
    if not (change.priority_set or change.status is not None or change.note_set):
        raise InvalidChange("nothing to change")
    values: dict[str, Any] = {}
    if change.priority_set:
        if change.priority is not None and not (1 <= change.priority <= MAX_PRIORITY):
            raise InvalidChange(f"priority must be 1 to {MAX_PRIORITY}, or empty")
        values["priority"] = change.priority
    if change.status is not None:
        if change.status not in RESEARCH_STATUSES:
            raise InvalidChange("unknown research status")
        values["research_status"] = change.status
    if change.note_set:
        if change.note is not None and len(change.note) > MAX_NOTE:
            raise InvalidChange(f"note is limited to {MAX_NOTE} characters")
        values["note"] = (change.note or "").strip() or None
    current = db.get(ModelResearchSlot, key)
    if current is None:
        raise LookupError(key)
    before = _row_out(current)
    label = actor_label or (actor.username if actor is not None else "api-key")
    now: datetime = utcnow()
    result = db.execute(
        update(ModelResearchSlot)
        .where(ModelResearchSlot.slot_key == key, ModelResearchSlot.version == expected_version)
        .values(**values, version=ModelResearchSlot.version + 1, updated_at=now, updated_by=label[:128])
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.expire_all()
        fresh = db.get(ModelResearchSlot, key)
        raise VersionConflict(_row_out(fresh) if fresh is not None else before)
    db.expire_all()
    fresh = db.get(ModelResearchSlot, key)
    after = _row_out(fresh)
    audit.record(
        db,
        "model_slot.update",
        actor=actor,
        actor_label=label,
        target_type="model_slot",
        target_id=key,
        before={k: before[k] for k in values_to_fields(values)},
        after={k: after[k] for k in values_to_fields(values)},
    )
    return after


def values_to_fields(values: dict[str, Any]) -> list[str]:
    return list(values.keys())
