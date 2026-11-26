"""Model promotion safeguard (#328): the only way to change which model serves.

Two steps, both recorded in `audit_log` (no new table):

1. **Record an approval** (`record_approval`): only a signed-in owner named in `REAL_ACCOUNT_USERS` can
   record one, never the shared API key or a typed-in name. The approval names what it is for (`kind` plus
   `target`), the sha256 of the exact model file approved, a reason, a protocol verdict that must be PASS, and
   evidence: at least one repo file with its sha256 (re-checked on disk), plus any PR numbers as plain
   references (a PR number cannot be checked offline and never counts as evidence alone). The row is an
   `approval_recorded` audit row; its id is the approval id and its server timestamp starts the 7-day clock.

2. **Use it once**, within 7 days, through one of:
   - `promote(db, model_id, approval_id)`: kind `promote`. The model card in `metrics["card"]` must name the
     approved file hash, and the file's sha256 is recomputed on disk now and must match it. The card is
     written by the trainer, so the independent check is that recomputation, not the card itself.
   - `rollback(db, to_model_id, approval_id)`: kind `rollback`. Restores only the model the last recorded
     promotion of that name replaced, only while that promotion's model is still active, and only if the
     file still has the hash recorded when it was replaced.
   - `approve_m06_on(db, approval_id)`: kind `brain_module_on`, target `M06`. The newest saved combiner (the
     file M06 serves) must have the approved hash. The caller then switches the module on.
   - `approve_strategy_model(db, approval_id, strategy_id, model_name)`: kind `strategy_model`. A strategy's
     model selector may change only to the approved name, whose active model file must have the approved hash.

Every use needs `ALLOW_MODEL_PROMOTION` on, takes the per-name lock before checking (promote / rollback),
re-checks the approver is still a designated owner and the evidence files are unchanged, and writes its own
audit row carrying the approval id, so an approval is never used twice. Refusals raise `PromotionError`
(a ValueError) before anything is written. A guard test (tests/test_model_activation_guard.py) fails if any
other code makes a model active.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.core.config import REPO_ROOT, settings
from swing_trade_ml.core.enums import ModelStatus
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.core.release_switches import promotion_refusal
from swing_trade_ml.db.models.audit import AuditLog
from swing_trade_ml.db.models.ml import MLModel
from swing_trade_ml.ml import registry

log = get_logger(__name__)

APPROVAL_ACTION = "model.approval_recorded"
PROMOTE_ACTION = "model.promote"
ROLLBACK_ACTION = "model.rollback"
M06_ON_ACTION = "brain.m06_on"
STRATEGY_MODEL_ACTION = "strategy.model_change"
USE_ACTIONS = (PROMOTE_ACTION, ROLLBACK_ACTION, M06_ON_ACTION, STRATEGY_MODEL_ACTION)
TARGET_TYPE = "ml_model"
#: kind -> audit target_type of the thing the approval is for
KINDS = {
    "promote": "ml_model",
    "rollback": "ml_model",
    "brain_module_on": "brain_module",
    "strategy_model": "strategy",
}
APPROVAL_MAX_AGE = timedelta(days=7)
MIN_REASON_CHARS = 10
MAX_TEXT_CHARS = 500
MAX_EVIDENCE = 20
PASS = "PASS"
APPROVAL_REQUIRED = "A recorded owner approval (approval id) is required."
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class PromotionError(ValueError):
    """Nothing was changed; the message says why in plain English."""


# ------------------------------------------------------------------ who may approve


def designated_owners() -> set[str]:
    return {n.strip().lower() for n in settings.REAL_ACCOUNT_USERS.split(",") if n.strip()}


def owner_problem(user: Any) -> str | None:
    """None when `user` is an active owner login named in REAL_ACCOUNT_USERS, else why not."""
    if user is None:
        return "Only the signed-in owner can approve; the shared API key and service keys cannot."
    if getattr(user, "role", None) != "owner" or not getattr(user, "is_active", False):
        return "Only an active owner login can approve."
    if (getattr(user, "username", "") or "").lower() not in designated_owners():
        return "Only the designated owner account (REAL_ACCOUNT_USERS) can approve."
    return None


def signed_in_owner(principal: Any) -> Any:
    """The designated owner's User from an API principal; the API key or a service key never qualifies."""
    user = getattr(principal, "user", None)
    if getattr(principal, "via_api_key", False) or getattr(principal, "service_scope", None):
        user = None
    if problem := owner_problem(user):
        raise PromotionError(problem)
    return user


# ------------------------------------------------------------------ evidence


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _is_repo_relative(rel: str) -> bool:
    """True only for a plain relative path with no parent step, judged the same on Windows and Linux.

    `Path.is_absolute()` depends on the machine: 'C:/x' is absolute on Windows but a plain name on Linux, and
    'a\\..\\b' has a '..' step only on Windows. Parsing as a Windows path (which also accepts '/') catches
    drive letters, UNC shares and backslash steps everywhere."""
    win = PureWindowsPath(rel)
    return bool(rel) and not win.anchor and not PurePosixPath(rel).is_absolute() and ".." not in win.parts


def check_evidence(evidence: Any) -> list[dict]:
    """Each ref is {"path": repo-relative file, "sha256": its hash} (checked on disk now) or {"pr": number}
    (recorded only). At least one file ref is required. Returns the cleaned list."""
    if not isinstance(evidence, list | tuple) or not evidence or len(evidence) > MAX_EVIDENCE:
        raise PromotionError(f"Evidence must list 1 to {MAX_EVIDENCE} references.")
    cleaned: list[dict] = []
    root = Path(REPO_ROOT).resolve()
    for ref in evidence:
        if isinstance(ref, dict) and set(ref) == {"pr"} and isinstance(ref["pr"], int) and ref["pr"] > 0:
            cleaned.append({"pr": ref["pr"]})
            continue
        if not (isinstance(ref, dict) and set(ref) == {"path", "sha256"}):
            raise PromotionError('Each evidence reference is {"path", "sha256"} or {"pr"}.')
        rel, sha = ref["path"], ref["sha256"]
        if not isinstance(rel, str) or not isinstance(sha, str) or not _SHA256.match(sha):
            raise PromotionError("An evidence file needs a repo path and its sha256 (64 hex characters).")
        candidate = (root / rel).resolve()
        if not _is_repo_relative(rel) or root not in candidate.parents:
            raise PromotionError(f"Evidence path {rel!r} must be a path inside the repository.")
        try:
            actual = _file_sha(candidate) if candidate.is_file() else None
        except OSError:
            actual = None
        if actual is None:
            raise PromotionError(f"Evidence file {rel!r} was not found.")
        if actual != sha:
            raise PromotionError(f"Evidence file {rel!r} has changed since it was cited (hash differs).")
        cleaned.append({"path": Path(rel).as_posix(), "sha256": sha})
    if not any("path" in r for r in cleaned):
        raise PromotionError("At least one evidence reference must be a repo file with its sha256.")
    return cleaned


# ------------------------------------------------------------------ step 1: record


def record_approval(
    db: Session,
    user: Any,
    *,
    kind: str,
    target: str | int,
    reason: str,
    evidence: list,
    protocol_verdict: str | None,
    artifact_sha256: str,
    model_name: str | None = None,
) -> AuditLog:
    """Record the designated owner's approval. Changes nothing else; the caller commits."""
    from swing_trade_ml.services import audit

    if problem := owner_problem(user):
        raise PromotionError(problem)
    if kind not in KINDS:
        raise PromotionError(f"Unknown approval kind {kind!r}; one of {sorted(KINDS)}.")
    reason = (reason or "").strip()
    if not MIN_REASON_CHARS <= len(reason) <= MAX_TEXT_CHARS:
        raise PromotionError(f"The reason must be {MIN_REASON_CHARS} to {MAX_TEXT_CHARS} characters.")
    if protocol_verdict != PASS:
        raise PromotionError("The protocol verdict must be PASS; FAIL, INCONCLUSIVE or none is refused.")
    if not isinstance(artifact_sha256, str) or not _SHA256.match(artifact_sha256):
        raise PromotionError("The approval must give the approved file's sha256 (64 hex characters).")
    if kind == "strategy_model" and not (model_name or "").strip():
        raise PromotionError("A strategy model approval must name the model.")
    target_text = str(target).strip().upper() if kind == "brain_module_on" else str(target).strip()
    if not target_text:
        raise PromotionError("The approval must name what it is for.")
    row = audit.record(
        db,
        APPROVAL_ACTION,
        actor=user,
        target_type=KINDS[kind],
        target_id=target_text,
        after={
            "kind": kind,
            "target": target_text,
            "artifact_sha256": artifact_sha256,
            "model_name": (model_name or "").strip() or None,
            "reason": reason,
            "evidence": check_evidence(evidence),
            "protocol_verdict": PASS,
            "approver_user_id": user.id,
            "approver_username": user.username,
            "approver_email": getattr(user, "email", None),
        },
    )
    log.info(APPROVAL_ACTION, approval_id=row.id, kind=kind, target=target_text, approver=user.username)
    return row


# ------------------------------------------------------------------ step 2: use once


def use_approval(
    db: Session, approval_id: int | None, *, kind: str, target: str | int, now: datetime | None = None
) -> AuditLog:
    """The recorded approval, if it is for this kind and target, fresh, unused and still backed by its
    evidence and a designated owner. Raises PromotionError otherwise."""
    from swing_trade_ml.db.models.session import User

    if approval_id is None:
        raise PromotionError(APPROVAL_REQUIRED)
    row = db.get(AuditLog, approval_id)
    if row is None or row.action != APPROVAL_ACTION:
        raise PromotionError(f"Approval {approval_id} not found.")
    after = row.after or {}
    expected = str(target).strip().upper() if kind == "brain_module_on" else str(target).strip()
    if after.get("kind") != kind or row.target_id != expected:
        raise PromotionError(f"Approval {approval_id} is for {after.get('kind')} {row.target_id}, not this.")
    now = now or datetime.now(UTC)
    recorded = row.ts if row.ts.tzinfo else row.ts.replace(tzinfo=UTC)
    if now - recorded > APPROVAL_MAX_AGE:
        raise PromotionError(
            f"Approval {approval_id} is older than {APPROVAL_MAX_AGE.days} days; record a new one."
        )
    used = db.execute(
        select(AuditLog.id)
        .where(AuditLog.action.in_(USE_ACTIONS), AuditLog.after["approval_id"].as_integer() == approval_id)
        .limit(1)
    ).scalar_one_or_none()
    if used is not None:
        raise PromotionError(f"Approval {approval_id} has already been used; record a new one.")
    approver = db.get(User, row.actor_user_id) if row.actor_user_id else None
    if problem := owner_problem(approver):
        raise PromotionError(f"Approval {approval_id}: {problem}")
    if after.get("protocol_verdict") != PASS:
        raise PromotionError(f"Approval {approval_id}: the protocol verdict is not PASS.")
    check_evidence(after.get("evidence"))
    return row


def _use_record(approval: AuditLog, invoked_by: str) -> dict[str, Any]:
    a = approval.after or {}
    return {
        "approval_id": approval.id,
        "approved_at": approval.ts.isoformat() if approval.ts else None,
        "approver_user_id": a.get("approver_user_id"),
        "approver_username": a.get("approver_username"),
        "approver_email": a.get("approver_email"),
        "reason": a.get("reason"),
        "evidence": a.get("evidence"),
        "protocol_verdict": a.get("protocol_verdict"),
        "invoked_by": invoked_by,
    }


def _switch_on() -> None:
    if refusal := promotion_refusal():
        raise PromotionError(refusal)


def _get(db: Session, model_id: int) -> MLModel:
    model = db.get(MLModel, model_id)
    if model is None:
        raise PromotionError(f"Model {model_id} not found.")
    return model


def _disk_sha(model: MLModel) -> str | None:
    """The real sha256 of the model's file, or None when it is missing or unreadable."""
    if not model.artifact_path:
        return None
    try:
        return registry.artifact_sha256(Path(model.artifact_path))
    except OSError:
        return None


def _check_file(model: MLModel, approved: str) -> None:
    """Recompute the file's sha256 now and compare it to the approved hash."""
    who = f"{model.name} {model.version}"
    path = Path(model.artifact_path) if model.artifact_path else None
    try:
        actual = registry.artifact_sha256(path) if path is not None else None
    except FileNotFoundError:
        actual = None
    except OSError as exc:  # never put the server path in the message
        raise PromotionError(f"{who}: the file on disk could not be read ({type(exc).__name__}).") from exc
    if actual is None:
        raise PromotionError(f"{who}: the file on disk is missing.")
    if actual != approved:
        raise PromotionError(f"{who}: the file on disk is not the file that was approved.")


def _activate(
    db: Session, model: MLModel, approval: AuditLog, action: str, invoked_by: str, extra: dict
) -> MLModel:
    from swing_trade_ml.db.models.session import User
    from swing_trade_ml.services import audit

    a = approval.after or {}

    def record(active: MLModel, replaced: list[MLModel]) -> None:
        prev = replaced[0] if replaced else None
        audit.record(
            db,
            action,
            actor=db.get(User, approval.actor_user_id) if approval.actor_user_id else None,
            actor_label=a.get("approver_username") or approval.actor_label,
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
                "artifact_sha256": a.get("artifact_sha256"),
                **_use_record(approval, invoked_by),
                **extra,
            },
        )

    activated = registry.activate_model(db, model.id, before_commit=record)
    log.info(action, name=activated.name, version=activated.version, approval_id=approval.id)
    return activated


def promote(
    db: Session, model_id: int, approval_id: int | None, *, invoked_by: str, now: datetime | None = None
) -> MLModel:
    """Make `model_id` the active model of its name, using one recorded owner approval."""
    _switch_on()
    model = _get(db, model_id)
    registry.lock_model_name(db, model.name)  # checks and activation see one state
    db.refresh(model)
    approval = use_approval(db, approval_id, kind="promote", target=model.id, now=now)
    approved = (approval.after or {}).get("artifact_sha256")
    card = (model.metrics or {}).get("card")
    card_sha = card.get("artifact_sha256") if isinstance(card, dict) else None
    who = f"{model.name} {model.version}"
    if not isinstance(card_sha, str) or not _SHA256.match(card_sha):
        raise PromotionError(f"{who}: no model card with a file hash; it cannot be promoted.")
    if card_sha != approved:
        raise PromotionError(f"{who}: the approved file hash is not the file its model card describes.")
    _check_file(model, approved)
    return _activate(db, model, approval, PROMOTE_ACTION, invoked_by, {})


def last_change(db: Session, name: str) -> AuditLog | None:
    """The most recent recorded promotion or rollback of a model name."""
    return db.execute(
        select(AuditLog)
        .where(
            AuditLog.target_type == TARGET_TYPE,
            AuditLog.action.in_((PROMOTE_ACTION, ROLLBACK_ACTION)),
            AuditLog.after["name"].as_string() == name,
        )
        .order_by(AuditLog.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def rollback(
    db: Session, to_model_id: int, approval_id: int | None, *, invoked_by: str, now: datetime | None = None
) -> MLModel:
    """Undo the last recorded promotion of a name: restore the model it replaced, through the same gate."""
    _switch_on()
    target = _get(db, to_model_id)
    registry.lock_model_name(db, target.name)  # taken before any check (no race with another activation)
    db.refresh(target)
    approval = use_approval(db, approval_id, kind="rollback", target=target.id, now=now)
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
    if (approval.after or {}).get("artifact_sha256") != recorded:
        raise PromotionError(f"{who}: the approved file hash is not the hash recorded when it was replaced.")
    _check_file(target, recorded)
    return _activate(db, target, approval, ROLLBACK_ACTION, invoked_by, {"undoes_audit_id": change.id})


# ------------------------------------------------------------------ other ways to change what serves


def newest_combiner_sha() -> str | None:
    """sha256 of the newest saved M06 combiner (the file M06 serves), or None when there is none."""
    from swing_trade_ml.brain.modules.m06_reason import artifact  # read only; the module is trial-frozen

    versions = artifact._versions()
    if not versions:
        return None
    try:
        return _file_sha(versions[-1][1])
    except OSError:
        return None


def _record_use(db: Session, approval: AuditLog, action: str, target_type: str, target_id: str, after: dict):
    from swing_trade_ml.db.models.session import User
    from swing_trade_ml.services import audit

    a = approval.after or {}
    return audit.record(
        db,
        action,
        actor=db.get(User, approval.actor_user_id) if approval.actor_user_id else None,
        actor_label=a.get("approver_username") or approval.actor_label,
        target_type=target_type,
        target_id=target_id,
        after={
            **after,
            "artifact_sha256": a.get("artifact_sha256"),
            **_use_record(approval, after["invoked_by"]),
        },
    )


def refuse_combiner_save_while_m06_on(db: Session) -> None:
    """M06 serves the newest saved combiner (frozen `artifact.load_latest`), so saving a new one while M06 is
    on would swap the approved file with no approval. Refuse it: switch M06 to shadow or off, train, record an
    approval for the new file, then switch it on. Shadow/off saves change no decision."""
    from swing_trade_ml.db.models.brain import BrainModuleSetting

    row = db.get(BrainModuleSetting, "M06")
    if row is not None and row.mode == "on":
        raise PromotionError(
            "M06 is on, so a new combiner can't be saved: it would replace the approved file unseen. "
            "Switch M06 to shadow, train, approve the new file, then switch it on."
        )


def approve_m06_on(
    db: Session, approval_id: int | None, *, invoked_by: str, now: datetime | None = None
) -> None:
    """Check and spend an approval to switch M06 on; writes the audit row. The caller switches, commits."""
    _switch_on()
    approval = use_approval(db, approval_id, kind="brain_module_on", target="M06", now=now)
    served = newest_combiner_sha()
    if served is None:
        raise PromotionError("M06 has no saved combiner to switch on.")
    if served != (approval.after or {}).get("artifact_sha256"):
        raise PromotionError("The newest saved M06 combiner is not the file that was approved.")
    _record_use(db, approval, M06_ON_ACTION, "brain_module", "M06", {"mode": "on", "invoked_by": invoked_by})


def approve_strategy_model(
    db: Session,
    approval_id: int | None,
    *,
    strategy_id: int,
    model_name: str,
    before: str | None,
    invoked_by: str,
    now: datetime | None = None,
) -> None:
    """Check and spend an approval to point a strategy at `model_name`; writes the audit row."""
    _switch_on()
    approval = use_approval(db, approval_id, kind="strategy_model", target=strategy_id, now=now)
    a = approval.after or {}
    if a.get("model_name") != model_name:
        raise PromotionError(
            f"Approval {approval.id} is for model {a.get('model_name')!r}, not {model_name!r}."
        )
    active = registry.get_active_model(db, model_name)
    if active is None:
        raise PromotionError(f"No active model is named {model_name!r}.")
    _check_file(active, a.get("artifact_sha256"))
    _record_use(
        db,
        approval,
        STRATEGY_MODEL_ACTION,
        "strategy",
        str(strategy_id),
        {
            "model_name": model_name,
            "previous_model_name": before,
            "model_id": active.id,
            "invoked_by": invoked_by,
        },
    )
