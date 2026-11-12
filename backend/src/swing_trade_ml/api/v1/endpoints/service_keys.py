"""Owner-only management of scoped service keys. The raw key is returned ONCE, on create/rotate."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from swing_trade_ml.api.admin_step_up import StepUp
from swing_trade_ml.api.deps import DbSession, Principal, actor_name, require_owner
from swing_trade_ml.services import audit, service_keys

admin = APIRouter(prefix="/admin/service-keys", tags=["service-keys"], dependencies=[Depends(require_owner)])

NEEDS_SIGNED_IN_OWNER = "Sign in as the owner to manage service keys."


def _owner_person(principal: Principal = Depends(require_owner)) -> Principal:
    """Keys are managed by a signed-in owner, not by the shared key that these keys replace."""
    if principal.user is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, NEEDS_SIGNED_IN_OWNER)
    return principal


class KeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    scope: Literal["read_status", "read_ops", "read_all"]
    expires_in_days: int | None = Field(default=None, ge=1, le=730)


class KeyRotate(BaseModel):
    overlap_hours: int = Field(default=24, ge=0, le=168)


class KeyOut(BaseModel):
    id: int
    name: str
    scope: str
    prefix: str
    created_at: datetime | None
    created_by: str
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None
    rotated_from_id: int | None
    status: str


def _out(row) -> KeyOut:
    now = datetime.now(row.created_at.tzinfo) if row.created_at else datetime.utcnow()
    if row.revoked_at is not None:
        state = "revoked"
    elif row.expires_at is not None and row.expires_at <= now:
        state = "expired"
    else:
        state = "active"
    return KeyOut(
        id=row.id,
        name=row.name,
        scope=row.scope,
        prefix=row.prefix,
        created_at=row.created_at,
        created_by=row.created_by,
        last_used_at=row.last_used_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        rotated_from_id=row.rotated_from_id,
        status=state,
    )


@admin.get("")
def list_keys(db: DbSession) -> dict:
    """Every key, never its secret. Also says whether the old shared key still works."""
    from swing_trade_ml.core.config import settings

    return {
        "keys": [_out(r) for r in service_keys.list_keys(db)],
        "scopes": {
            "read_status": "Health checks only: " + ", ".join(sorted(service_keys.READ_STATUS_PATHS)),
            "read_ops": "The daily operations digest only: GET /ops/digest.",
            "read_all": "Read-only access to most screens. Never writes, the real account, or admin.",
        },
        "legacy_api_key_enabled": settings.LEGACY_API_KEY_ENABLED,
    }


@admin.post("", status_code=status.HTTP_201_CREATED, dependencies=[StepUp])
def create(
    body: KeyCreate, db: DbSession, request: Request, principal: Principal = Depends(_owner_person)
) -> dict:
    row, raw = service_keys.create_key(
        db,
        name=body.name,
        scope=body.scope,
        created_by=actor_name(principal),
        expires_in_days=body.expires_in_days,
    )
    audit.record(
        db,
        "service_key.create",
        actor=principal.user,
        actor_label=actor_name(principal),
        target_type="service_key",
        target_id=row.id,
        after={"name": row.name, "scope": row.scope},
        request=request,
    )
    db.commit()
    return {"key": raw, "shown_once": True, "item": _out(row)}


@admin.post("/{key_id}/rotate", status_code=status.HTTP_201_CREATED, dependencies=[StepUp])
def rotate(
    key_id: int,
    body: KeyRotate,
    db: DbSession,
    request: Request,
    principal: Principal = Depends(_owner_person),
) -> dict:
    result = service_keys.rotate(
        db, key_id, created_by=actor_name(principal), overlap_hours=body.overlap_hours
    )
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No active key with that id.")
    new, raw, old = result
    audit.record(
        db,
        "service_key.rotate",
        actor=principal.user,
        actor_label=actor_name(principal),
        target_type="service_key",
        target_id=new.id,
        after={"replaces": old.id, "overlap_hours": body.overlap_hours},
        request=request,
    )
    db.commit()
    return {"key": raw, "shown_once": True, "item": _out(new), "old": _out(old)}


@admin.post("/{key_id}/revoke", dependencies=[StepUp])
def revoke(
    key_id: int, db: DbSession, request: Request, principal: Principal = Depends(_owner_person)
) -> dict:
    row = service_keys.revoke(db, key_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No key with that id.")
    audit.record(
        db,
        "service_key.revoke",
        actor=principal.user,
        actor_label=actor_name(principal),
        target_type="service_key",
        target_id=row.id,
        request=request,
    )
    db.commit()
    return {"item": _out(row)}
