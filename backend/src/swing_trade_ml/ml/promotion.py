"""Model promotion safeguard (#328): the only way a model becomes the active one.

`promote(db, model_id, approval)` and `rollback(db, to_model_id, approval)` wrap `registry.activate_model`.
Each one, in this order:

1. refuses while the `ALLOW_MODEL_PROMOTION` switch is off (the default);
2. refuses without a complete owner approval: who approved, when (within the last 7 days), why, at least
   one evidence reference (an evaluation report and its commit, a protocol verdict), and the sha256 of the
   exact model file the owner approved;
3. refuses unless the evidence checks out against the file on disk:
   - promote: the model card in `metrics["card"]` names a file hash, that hash matches the row's
     `metrics["artifact_sha256"]`, the approved hash and the file's real hash;
   - rollback: the target is the model the last recorded promotion of that name replaced, the model that
     promotion made active is still the active one, and the file's real hash still equals the hash recorded
     when it was replaced (older models without a card can be rolled back to this way);
4. activates through `registry.activate_model`, which archives the incumbent and checks the file against
   its row once more, and writes one `audit_log` row (`model.promote` / `model.rollback`) in the same
   transaction: approver, evidence, the file hash, and the model it replaced (with that file's hash) so a
   later rollback can restore it.

Nothing here trains, deletes or edits a model file. Any refusal raises `PromotionError` (a ValueError)
before anything is written. A guard test (tests/test_model_activation_guard.py) fails if any other code
makes a model active.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.core.enums import ModelStatus
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.core.release_switches import promotion_refusal
from swing_trade_ml.db.models.audit import AuditLog
from swing_trade_ml.db.models.ml import MLModel
from swing_trade_ml.ml import registry

log = get_logger(__name__)

PROMOTE_ACTION = "model.promote"
ROLLBACK_ACTION = "model.rollback"
TARGET_TYPE = "ml_model"
APPROVAL_MAX_AGE = timedelta(days=7)
CLOCK_SKEW = timedelta(minutes=5)
MIN_REASON_CHARS = 10
MAX_TEXT_CHARS = 500
APPROVAL_REQUIRED = "A recorded owner approval is required to make a model active."
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class PromotionError(ValueError):
    """The model was not made active; the message says why in plain English."""


@dataclass(frozen=True)
class Approval:
    """The owner's recorded decision to put one exact model file into use."""

    approver: str
    reason: str
    evidence: tuple[str, ...]
    artifact_sha256: str
    approved_at: datetime
    protocol_verdict: str | None = None
    approver_user_id: int | None = None


def check_approval(approval: Approval | None, now: datetime | None = None) -> Approval:
    if not isinstance(approval, Approval):
        raise PromotionError(APPROVAL_REQUIRED)
    now = now or datetime.now(UTC)
    if not (approval.approver or "").strip():
        raise PromotionError("The approval must name the approver.")
    if len((approval.reason or "").strip()) < MIN_REASON_CHARS:
        raise PromotionError(f"The approval needs a reason of at least {MIN_REASON_CHARS} characters.")
    evidence = approval.evidence or ()
    if not evidence or any(not isinstance(e, str) or not e.strip() for e in evidence):
        raise PromotionError("The approval needs at least one evidence reference (report, commit).")
    if any(len(e) > MAX_TEXT_CHARS for e in evidence) or len(approval.reason) > MAX_TEXT_CHARS:
        raise PromotionError(f"Approval text is limited to {MAX_TEXT_CHARS} characters per field.")
    if not isinstance(approval.artifact_sha256, str) or not _SHA256.match(approval.artifact_sha256):
        raise PromotionError("The approval must give the approved file's sha256 (64 hex characters).")
    at = approval.approved_at
    if not isinstance(at, datetime) or at.tzinfo is None:
        raise PromotionError("The approval time must include a time zone.")
    if at > now + CLOCK_SKEW:
        raise PromotionError("The approval time is in the future.")
    if now - at > APPROVAL_MAX_AGE:
        raise PromotionError(f"The approval is older than {APPROVAL_MAX_AGE.days} days; record a new one.")
    return approval


def _disk_sha(model: MLModel) -> str | None:
    """The real sha256 of the model's file, or None when it is missing or unreadable."""
    if not model.artifact_path:
        return None
    try:
        return registry.artifact_sha256(Path(model.artifact_path))
    except OSError:
        return None


def _check_file(model: MLModel, expected: str, approved: str) -> None:
    who = f"{model.name} {model.version}"
    if approved != expected:
        raise PromotionError(f"{who}: the approved file hash is not this model's file hash.")
    path = Path(model.artifact_path) if model.artifact_path else None
    try:
        actual = registry.artifact_sha256(path) if path is not None else None
    except FileNotFoundError:
        actual = None
    except OSError as exc:  # never put the server path in the message
        raise PromotionError(f"{who}: the file on disk could not be read ({type(exc).__name__}).") from exc
    if actual is None:
        raise PromotionError(f"{who}: the file on disk is missing.")
    if actual != expected:
        raise PromotionError(f"{who}: the file on disk is not the file that was approved.")


def check_card_evidence(model: MLModel, approval: Approval) -> str:
    """The model card names the exact file on disk that the owner approved. Returns that hash."""
    who = f"{model.name} {model.version}"
    metrics = model.metrics or {}
    card = metrics.get("card")
    card_sha = card.get("artifact_sha256") if isinstance(card, dict) else None
    if not isinstance(card_sha, str) or not _SHA256.match(card_sha):
        raise PromotionError(f"{who}: no model card with a file hash; it cannot be promoted.")
    if metrics.get("artifact_sha256") != card_sha:
        raise PromotionError(f"{who}: the model card and the recorded file hash disagree.")
    _check_file(model, card_sha, approval.artifact_sha256)
    return card_sha


def _get(db: Session, model_id: int) -> MLModel:
    model = db.get(MLModel, model_id)
    if model is None:
        raise PromotionError(f"Model {model_id} not found.")
    return model


def _approval_record(approval: Approval, invoked_by: str) -> dict[str, Any]:
    return {
        "approver": approval.approver.strip(),
        "approved_at": approval.approved_at.astimezone(UTC).isoformat(),
        "reason": approval.reason.strip(),
        "evidence": [e.strip() for e in approval.evidence],
        "protocol_verdict": approval.protocol_verdict,
        "invoked_by": invoked_by,
    }


def _activate(
    db: Session, model: MLModel, approval: Approval, sha: str, action: str, invoked_by: str, extra: dict
) -> MLModel:
    from swing_trade_ml.db.models.session import User
    from swing_trade_ml.services import audit

    def record(active: MLModel, replaced: list[MLModel]) -> None:
        prev = replaced[0] if replaced else None
        audit.record(
            db,
            action,
            actor=db.get(User, approval.approver_user_id) if approval.approver_user_id else None,
            actor_label=approval.approver.strip(),
            target_type=TARGET_TYPE,
            target_id=active.id,
            before={
                "active_model_id": prev.id if prev else None,
                "active_version": prev.version if prev else None,
                "active_artifact_sha256": _disk_sha(prev) if prev else None,
                "also_archived": [m.id for m in replaced[1:]],
            },
            after={
                "model_id": active.id,
                "name": active.name,
                "version": active.version,
                "artifact_sha256": sha,
                **_approval_record(approval, invoked_by),
                **extra,
            },
        )

    activated = registry.activate_model(db, model.id, before_commit=record)
    log.info(action, name=activated.name, version=activated.version, approver=approval.approver)
    return activated


def promote(
    db: Session, model_id: int, approval: Approval, *, invoked_by: str, now: datetime | None = None
) -> MLModel:
    """Make `model_id` the active model of its name, with the owner's approval and checked evidence."""
    if refusal := promotion_refusal():
        raise PromotionError(refusal)
    check_approval(approval, now)
    model = _get(db, model_id)
    sha = check_card_evidence(model, approval)
    return _activate(db, model, approval, sha, PROMOTE_ACTION, invoked_by, {})


def last_change(db: Session, name: str) -> AuditLog | None:
    """The most recent recorded promotion or rollback of a model name."""
    rows = db.execute(
        select(AuditLog)
        .where(AuditLog.target_type == TARGET_TYPE, AuditLog.action.in_((PROMOTE_ACTION, ROLLBACK_ACTION)))
        .order_by(AuditLog.id.desc())
    ).scalars()
    return next((r for r in rows if (r.after or {}).get("name") == name), None)


def rollback(
    db: Session, to_model_id: int, approval: Approval, *, invoked_by: str, now: datetime | None = None
) -> MLModel:
    """Undo the last recorded promotion of a name: restore the model it replaced, through the same gate."""
    if refusal := promotion_refusal():
        raise PromotionError(refusal)
    check_approval(approval, now)
    target = _get(db, to_model_id)
    who = f"{target.name} {target.version}"
    change = last_change(db, target.name)
    if change is None:
        raise PromotionError(f"{who}: there is no recorded promotion of {target.name} to roll back.")
    before, after = change.before or {}, change.after or {}
    if before.get("active_model_id") != target.id:
        raise PromotionError(f"{who}: only the model the last promotion replaced can be restored.")
    current = registry.get_active_model(db, target.name)
    if current is None or current.id != after.get("model_id"):
        raise PromotionError(
            f"{who}: the active {target.name} model changed outside the promotion record; check it by hand."
        )
    recorded = before.get("active_artifact_sha256")
    if not isinstance(recorded, str) or not _SHA256.match(recorded):
        raise PromotionError(f"{who}: no file hash was recorded when it was replaced; cannot restore it.")
    if target.status != ModelStatus.ARCHIVED:
        raise PromotionError(f"{who}: only an archived model can be restored (now {target.status}).")
    _check_file(target, recorded, approval.artifact_sha256)
    undo = {"undoes_audit_id": change.id}
    return _activate(db, target, approval, recorded, ROLLBACK_ACTION, invoked_by, undo)
