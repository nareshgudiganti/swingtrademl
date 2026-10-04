"""Free / Pro plans: what the caller's plan allows, and the owner's
Plans Manager (edit plans, assign users). See core/plans.py."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from swing_trade_ml.api.deps import DbSession, PlanAccessDep, Principal, get_principal, require_owner
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.plans import BASE_MODEL, CAP_TIERS, FEATURES, LIMITS, PLAN_KEYS
from swing_trade_ml.db.models.session import User
from swing_trade_ml.services import plans as plan_service

router = APIRouter(tags=["plans"])
admin = APIRouter(prefix="/admin", tags=["plans"], dependencies=[Depends(require_owner)])


class PlanUpdate(BaseModel):
    features: dict[str, bool]
    limits: dict[str, Any]


class UserPlanUpdate(BaseModel):
    plan: str


class SwitchUpdate(BaseModel):
    enabled: bool


@router.get("/me/plan", response_model=dict)
def my_plan(
    access: PlanAccessDep, principal: Annotated[Principal, Depends(get_principal)], db: DbSession
) -> dict[str, Any]:
    """What the signed-in person may see. The frontend builds its menu from
    this; the API enforces the same rules on every call regardless.

    `unrestricted` means the whole app: the owner, or anyone while plans
    are switched off. `can_manage_plans` is the real owner only, preview or
    not, so the owner can always reach the Plans Manager to get back out.
    """
    common = {
        "can_manage_plans": principal.is_owner,
        "plans_enabled": plan_service.plans_enabled(db),
        "brain_enabled": settings.BRAIN_ENABLED,
    }
    if access.unrestricted:
        return {
            **common,
            "plan": "owner" if principal.is_owner else "all",
            "unrestricted": True,
            "previewing": False,
            "features": list(FEATURES),
            "limits": {},
        }
    return {
        **common,
        "plan": access.plan,
        "unrestricted": False,
        "previewing": access.previewing,
        "features": sorted(access.features),
        "limits": access.limits,
    }


@admin.get("/switch", response_model=dict)
def get_switch(db: DbSession) -> dict[str, bool]:
    return {"enabled": plan_service.plans_enabled(db)}


@admin.put("/switch", response_model=dict)
def set_switch(body: SwitchUpdate, db: DbSession) -> dict[str, bool]:
    """Turn plans on or off for everyone. Off is the app exactly as it was
    before plans: every signed-in account sees everything."""
    return {"enabled": plan_service.set_plans_enabled(db, body.enabled)}


@admin.get("/features", response_model=dict)
def catalogue() -> dict[str, Any]:
    return {
        "features": [{"key": k, **v} for k, v in FEATURES.items()],
        "limits": [{"key": k, **v} for k, v in LIMITS.items()],
        "cap_tiers": list(CAP_TIERS),
        "base_model": BASE_MODEL,
    }


@admin.get("/plans", response_model=list[dict])
def list_plans(db: DbSession) -> list[dict[str, Any]]:
    return plan_service.list_plans(db)


@admin.put("/plans/{key}", response_model=dict)
def update_plan(key: str, body: PlanUpdate, db: DbSession) -> dict[str, Any]:
    if key not in PLAN_KEYS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No plan called {key!r}")
    try:
        return plan_service.save_plan(db, key, body.features, body.limits)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


def _user_out(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "auth_provider": user.auth_provider,
        "is_active": user.is_active,
        "is_owner": user.is_superuser,
        "plan": user.plan,
        "last_login_at": user.last_login_at,
    }


@admin.get("/users", response_model=list[dict])
def list_users(db: DbSession) -> list[dict[str, Any]]:
    users = db.execute(select(User).order_by(User.created_at)).scalars().all()
    return [_user_out(u) for u in users]


@admin.put("/users/{user_id}/plan", response_model=dict)
def set_user_plan(user_id: int, body: UserPlanUpdate, db: DbSession) -> dict[str, Any]:
    if body.plan not in PLAN_KEYS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Plan must be one of {', '.join(PLAN_KEYS)}"
        )
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    user.plan = body.plan
    db.commit()
    return _user_out(user)
