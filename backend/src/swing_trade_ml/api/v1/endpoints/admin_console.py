"""Admin console API: two-step sign-in (MFA) for the admin, and the admin-only users screen.

- Admin = a signed-in user with the owner role. The shared API key is NOT an admin here (no person
  behind it, so no second step). Anyone else is refused with a 403 and never sees the admin screen.
- /admin/mfa/*: status, setup, enable, verify (trade a code for a 15-minute step-up token).
- /admin/console/*: needs that token in `X-Admin-Mfa`. Users list, Free/Pro switch, manual grants
  (with reason and optional end date), audit trail, release switches (read-only).
Every change is written to the audit log by the same code the older owner screens use.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from swing_trade_ml.api.deps import DbSession, Principal, get_principal
from swing_trade_ml.api.v1.endpoints import billing as billing_ep
from swing_trade_ml.api.v1.endpoints import plans as plans_ep
from swing_trade_ml.core.release_switches import switch_states
from swing_trade_ml.db.models.audit import AuditLog
from swing_trade_ml.db.models.billing import PlanGrant, Subscription
from swing_trade_ml.db.models.session import User
from swing_trade_ml.services import admin_mfa as mfa
from swing_trade_ml.services import audit
from swing_trade_ml.services.billing import entitlement


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")


def _admin_only() -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, "Only the admin can do this.")


async def require_admin_user(principal: Annotated[Principal, Depends(get_principal)]) -> User:
    """A signed-in owner-role person. Everyone else (members, testers, the API key) gets a 403."""
    user = principal.user
    if principal.via_api_key or user is None or user.role != "owner" or not user.is_active:
        raise _admin_only()
    return user


AdminUser = Annotated[User, Depends(require_admin_user)]


async def require_admin_mfa(
    user: AdminUser,
    db: DbSession,
    x_admin_mfa: Annotated[str | None, Header(alias="X-Admin-Mfa")] = None,
) -> User:
    if not mfa.is_enrolled(db, user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            {"code": "mfa_setup_required", "message": "Set up two-step sign-in first."},
        )
    if not mfa.step_up_valid(x_admin_mfa, user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, {"code": "mfa_required", "message": "Enter your two-step code."}
        )
    return user


MfaAdmin = Annotated[User, Depends(require_admin_mfa)]

mfa_router = APIRouter(prefix="/admin/mfa", tags=["admin-mfa"])
console = APIRouter(prefix="/admin/console", tags=["admin-console"])


class CodeBody(BaseModel):
    code: str | None = Field(default=None, max_length=12)
    recovery_code: str | None = Field(default=None, max_length=24)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


# ---------------------------------------------------------------- MFA


@mfa_router.get("")
def mfa_status(user: AdminUser, db: DbSession) -> dict[str, Any]:
    enrolled = mfa.is_enrolled(db, user)
    return {
        "enrolled": enrolled,
        "recovery_codes_left": mfa.remaining_recovery_codes(db, user) if enrolled else 0,
    }


@mfa_router.post("/setup")
def mfa_setup(
    user: AdminUser,
    db: DbSession,
    request: Request,
    x_admin_mfa: Annotated[str | None, Header(alias="X-Admin-Mfa")] = None,
) -> dict[str, str]:
    """Create a secret to scan into an authenticator app. Replacing an active setup needs a step-up token."""
    if mfa.is_enrolled(db, user) and not mfa.step_up_valid(x_admin_mfa, user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, {"code": "mfa_required", "message": "Enter your two-step code."}
        )
    secret, uri = mfa.start_setup(db, user)
    audit.record(db, "admin.mfa_setup", actor=user, target_type="user", target_id=user.id, request=request)
    db.commit()
    return {"secret": secret, "otpauth_uri": uri}


@mfa_router.post("/enable")
def mfa_enable(body: CodeBody, user: AdminUser, db: DbSession, request: Request) -> dict[str, Any]:
    try:
        codes = mfa.enable(db, user, body.code or "")
    except mfa.MfaError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    audit.record(db, "admin.mfa_enabled", actor=user, target_type="user", target_id=user.id, request=request)
    token, exp = mfa.issue_step_up(user)
    db.commit()
    return {"recovery_codes": codes, "step_up_token": token, "expires_at": _iso(exp)}


@mfa_router.post("/verify")
def mfa_verify(body: CodeBody, user: AdminUser, db: DbSession, request: Request) -> dict[str, Any]:
    try:
        mfa.verify(db, user, code=body.code, recovery_code=body.recovery_code)
    except mfa.MfaError as exc:
        audit.record(
            db, "admin.mfa_failed", actor=user, target_type="user", target_id=user.id, request=request
        )
        db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    audit.record(
        db,
        "admin.mfa_recovery_used" if body.recovery_code else "admin.mfa_verified",
        actor=user,
        target_type="user",
        target_id=user.id,
        request=request,
    )
    token, exp = mfa.issue_step_up(user)
    db.commit()
    return {
        "step_up_token": token,
        "expires_at": _iso(exp),
        "recovery_codes_left": mfa.remaining_recovery_codes(db, user),
    }


# ---------------------------------------------------------------- users


def _user_row(db: DbSession, u: User, now: datetime) -> dict[str, Any]:
    subs = db.execute(select(Subscription).where(Subscription.user_id == u.id)).scalars().all()
    grants = db.execute(select(PlanGrant).where(PlanGrant.user_id == u.id)).scalars().all()
    live_grant = next((g for g in grants if entitlement.grant_in_force(g, now)), None)
    latest_sub = max(subs, key=lambda s: s.id, default=None)
    return {
        "id": u.id,
        "username": u.username,
        "email": u.email,
        "full_name": u.full_name,
        "role": u.role,
        "is_active": u.is_active,
        "email_verified": u.email_verified_at is not None,
        "stored_plan": u.plan,
        "effective_plan": entitlement.effective_plan_for_user(db, u, now) or u.plan,
        "subscription_status": latest_sub.status if latest_sub else None,
        "subscription_ends_at": _iso(latest_sub.current_end) if latest_sub else None,
        "grant_expires_at": _iso(live_grant.expires_at) if live_grant else None,
        "has_active_grant": live_grant is not None,
        "last_login_at": _iso(u.last_login_at),
        "created_at": _iso(u.created_at),
    }


@console.get("/users")
def list_users(
    admin: MfaAdmin, db: DbSession, q: str | None = None, limit: int = 50, offset: int = 0
) -> dict[str, Any]:
    limit = max(1, min(limit, 200))
    stmt = select(User).order_by(User.id)
    if q and q.strip():
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(User.username.ilike(like), User.email.ilike(like), User.full_name.ilike(like)))
    rows = db.execute(stmt.offset(max(0, offset)).limit(limit)).scalars().all()
    now = datetime.now(UTC)
    return {"users": [_user_row(db, u, now) for u in rows], "limit": limit, "offset": max(0, offset)}


@console.put("/users/{user_id}/plan")
def set_plan(user_id: int, body: plans_ep.UserPlanUpdate, admin: MfaAdmin, db: DbSession) -> dict[str, Any]:
    target = db.get(User, user_id)
    if target is None:
        raise _not_found()
    if target.role == "owner":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "The admin account is never limited by a plan."
        )
    plans_ep.set_user_plan(user_id, body, db, Principal(user=admin))
    db.refresh(target)
    return _user_row(db, target, datetime.now(UTC))


@console.get("/users/{user_id}/grants")
def list_grants(user_id: int, admin: MfaAdmin, db: DbSession) -> list[dict[str, Any]]:
    return billing_ep.list_grants(user_id, db)


@console.post("/users/{user_id}/grants", status_code=status.HTTP_201_CREATED)
def create_grant(
    user_id: int, body: billing_ep.GrantCreate, admin: MfaAdmin, db: DbSession, request: Request
) -> dict[str, Any]:
    return billing_ep.create_grant(user_id, body, db, Principal(user=admin), request)


@console.delete("/users/{user_id}/grants/{grant_id}")
def revoke_grant(
    user_id: int, grant_id: int, admin: MfaAdmin, db: DbSession, request: Request
) -> dict[str, Any]:
    return billing_ep.revoke_grant(user_id, grant_id, db, Principal(user=admin), request)


# ---------------------------------------------------------------- audit + switches


@console.get("/audit")
def audit_trail(
    admin: MfaAdmin, db: DbSession, limit: int = 50, action: str | None = None
) -> list[dict[str, Any]]:
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(max(1, min(limit, 200)))
    if action:
        stmt = stmt.where(AuditLog.action == action)
    return [
        {
            "id": r.id,
            "ts": _iso(r.ts),
            "actor": r.actor_label,
            "action": r.action,
            "target_type": r.target_type,
            "target_id": r.target_id,
            "before": r.before,
            "after": r.after,
        }
        for r in db.execute(stmt).scalars()
    ]


@console.get("/release-switches")
def release_switches(admin: MfaAdmin) -> dict[str, Any]:
    return {"switches": switch_states()}
