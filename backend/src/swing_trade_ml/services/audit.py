"""Write one audit_log row. The caller commits: an action and its audit row
succeed or fail together."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from swing_trade_ml.db.models.audit import AuditLog
from swing_trade_ml.db.models.session import User

_SECRET_KEYS = frozenset(
    {
        "password",
        "new_password",
        "current_password",
        "hashed_password",
        "token",
        "access_token",
        "code",
        "secret",
    }
)


def _clean(values: dict[str, Any] | None) -> dict[str, Any] | None:
    if values is None:
        return None
    return {k: ("[redacted]" if k in _SECRET_KEYS else v) for k, v in values.items()}


def record(
    db: Session,
    action: str,
    *,
    actor: User | None = None,
    actor_label: str | None = None,
    target_type: str | None = None,
    target_id: object | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    request: Request | None = None,
) -> AuditLog:
    label = actor_label or (actor.username if actor is not None else "system")
    row = AuditLog(
        actor_user_id=actor.id if actor is not None else None,
        actor_label=label[:128],
        action=action[:48],
        target_type=target_type,
        target_id=None if target_id is None else str(target_id)[:64],
        before=_clean(before),
        after=_clean(after),
        ip=(request.client.host if request is not None and request.client else None),
        user_agent=((request.headers.get("user-agent") or "")[:256] if request is not None else None),
    )
    db.add(row)
    db.flush()
    return row
