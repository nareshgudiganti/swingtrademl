"""Pro subscription billing (Razorpay SANDBOX only, behind BILLING_ENABLED).

Every route here answers 404 while BILLING_ENABLED is false (404 = switched off for this
environment; 403 = switched on but not allowed). POST /billing/checkout additionally answers 404
unless BILLING_ACCEPT_NEW_CHECKOUTS is true; /me, /cancel and the webhook work either way.
Plan resolution reads the result through services/billing/entitlement.py and ignores both switches.

Plan-gate classification (see tests/test_billing_routes_classified.py):
- /billing/plans, /me, /checkout, /cancel, /fake/simulate: any signed-in PERSON, own data only.
  They deliberately do not sit behind require_auth (a member's writes are owner-only there).
- /billing/webhook: public by design (the provider calls it), rate-limited, signature checked first.
- /admin/users/{id}/grants: owner only (require_owner).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import select

from swing_trade_ml.api.admin_step_up import StepUp
from swing_trade_ml.api.deps import (
    DbSession,
    Principal,
    PrincipalDep,
    actor_name,
    get_principal,
    require_owner,
)
from swing_trade_ml.api.rate_limit import public_limit
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.core.plans import PLAN_KEYS, default_plan
from swing_trade_ml.db.models.billing import PlanGrant, Subscription
from swing_trade_ml.db.models.session import User
from swing_trade_ml.services import audit
from swing_trade_ml.services.billing import entitlement
from swing_trade_ml.services.billing import service as billing
from swing_trade_ml.services.billing.base import BillingConfigError, BillingError
from swing_trade_ml.services.billing.fake import SIMULATED_EVENTS

log = get_logger(__name__)

NOT_AVAILABLE = "Not found"


def billing_enabled() -> None:
    if not settings.BILLING_ENABLED:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_AVAILABLE)


def checkout_open() -> None:
    """New checkouts are a separate, narrower switch: closed = 404 for this route only."""
    if not settings.BILLING_ACCEPT_NEW_CHECKOUTS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_AVAILABLE)


router = APIRouter(prefix="/billing", tags=["billing"], dependencies=[Depends(billing_enabled)])
admin = APIRouter(
    prefix="/admin",
    tags=["billing"],
    dependencies=[Depends(billing_enabled), Depends(require_owner)],
)


def person(principal: Annotated[Principal, Depends(get_principal)]) -> User:
    """A signed-in person. The shared API key has no person behind it, so it is refused."""
    if principal.user is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sign in as a person to use billing.")
    return principal.user


Person = Annotated[User, Depends(person)]


def _provider_error(exc: BillingError) -> HTTPException:
    """A generic message only: provider details and keys never reach the client."""
    if isinstance(exc, BillingConfigError):
        log.warning("billing.misconfigured", error=str(exc))
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Billing is not set up right now.")
    log.warning("billing.provider_error", error=str(exc))
    return HTTPException(
        status.HTTP_502_BAD_GATEWAY, "The payment service did not answer. Try again shortly."
    )


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _sub_out(sub: Subscription | None) -> dict[str, Any]:
    if sub is None:
        return {"subscription": None}
    return {
        "subscription": {
            "provider": sub.provider,
            "status": sub.status,
            "paid_through": _iso(sub.current_end),
            "cancel_scheduled": bool(sub.cancel_at_cycle_end),
            "cancelled_at": _iso(sub.cancelled_at),
        }
    }


@router.get("/plans", response_model=dict)
def plans(_user: Person) -> dict[str, Any]:
    out = []
    for key in PLAN_KEYS:
        spec = default_plan(key)
        entry: dict[str, Any] = {"key": key, "name": spec["name"], "features": spec["features"]}
        if key == "pro":
            entry["price"] = {
                "amount_paise": settings.PRO_PRICE_MONTHLY_PAISE,
                "currency": "INR",
                "interval": "monthly",
            }
        out.append(entry)
    return {
        "plans": out,
        "provider": settings.BILLING_PROVIDER,
        "sandbox": not settings.ALLOW_LIVE_BILLING,
        "checkout_open": bool(settings.BILLING_ACCEPT_NEW_CHECKOUTS),
    }


@router.get("/me", response_model=dict)
def my_billing(user: Person, db: DbSession) -> dict[str, Any]:
    sub = billing.latest_subscription(db, user.id)
    grants = db.execute(select(PlanGrant).where(PlanGrant.user_id == user.id)).scalars().all()
    now = datetime.now(UTC)
    return {
        "plan": entitlement.effective_plan_for_user(db, user, now),
        "stored_plan": user.plan,
        "complimentary": any(entitlement.grant_in_force(g, now) for g in grants),
        "provider": settings.BILLING_PROVIDER,
        "sandbox": not settings.ALLOW_LIVE_BILLING,
        **_sub_out(sub),
    }


@router.post("/checkout", response_model=dict, dependencies=[Depends(checkout_open)])
def checkout(user: Person, db: DbSession) -> dict[str, Any]:
    now = datetime.now(UTC)
    existing = billing.latest_subscription(db, user.id)
    if existing is not None and entitlement.subscription_entitled(existing, now):
        raise HTTPException(status.HTTP_409_CONFLICT, "You already have an active Pro subscription.")
    try:
        info = billing.create_checkout(db, user, "pro")
    except BillingError as exc:
        raise _provider_error(exc) from None
    db.commit()
    return {
        "provider": info.provider,
        "subscription_id": info.provider_subscription_id,
        "key_id": info.key_id,
        "completion_url": info.completion_url,
        "completion_token": info.completion_token,
        "price": {"amount_paise": settings.PRO_PRICE_MONTHLY_PAISE, "currency": "INR", "interval": "monthly"},
    }


class CancelBody(BaseModel):
    at_cycle_end: bool = True


@router.post("/cancel", response_model=dict)
def cancel(user: Person, db: DbSession, body: CancelBody | None = None) -> dict[str, Any]:
    body = body or CancelBody()
    sub = billing.latest_subscription(db, user.id)
    if sub is None or sub.status in ("cancelled", "completed"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "You have no subscription to cancel.")
    try:
        billing.cancel(db, sub, body.at_cycle_end)
    except BillingError as exc:
        raise _provider_error(exc) from None
    db.commit()
    return _sub_out(sub)


@router.post("/webhook", response_model=dict, dependencies=[Depends(public_limit)])
async def webhook(
    request: Request,
    db: DbSession,
    x_razorpay_signature: Annotated[str | None, Header(alias="X-Razorpay-Signature")] = None,
    x_razorpay_event_id: Annotated[str | None, Header(alias="X-Razorpay-Event-Id")] = None,
) -> dict[str, Any]:
    raw = await request.body()  # the exact bytes; the signature covers these, not a re-encoding
    try:
        outcome = await run_in_threadpool(
            billing.handle_webhook, db, raw, x_razorpay_signature, x_razorpay_event_id
        )
    except BillingConfigError as exc:
        raise _provider_error(exc) from None
    except BillingError as exc:
        if str(exc) == "bad signature":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid signature") from None
        raise _provider_error(exc) from None  # fetch failed: 5xx so the provider retries
    db.commit()
    return {"ok": True, "outcome": "duplicate" if outcome == "duplicate" else "received"}


class SimulateBody(BaseModel):
    event: str
    subscription_id: str | None = None


@router.post("/fake/simulate", response_model=dict)
def fake_simulate(
    body: SimulateBody, principal: Annotated[Principal, Depends(get_principal)], db: DbSession
) -> dict[str, Any]:
    """Private-journey driver: only with BILLING_PROVIDER=fake. Same code path as a webhook."""
    if settings.BILLING_PROVIDER != "fake":
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_AVAILABLE)
    user = person(principal)
    if body.event not in SIMULATED_EVENTS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Event must be one of {', '.join(SIMULATED_EVENTS)}"
        )
    if body.subscription_id:
        sub = db.execute(
            select(Subscription).where(Subscription.provider_subscription_id == body.subscription_id)
        ).scalar_one_or_none()
    else:
        sub = billing.latest_subscription(db, user.id)
    if sub is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such subscription.")
    if sub.user_id != user.id and not principal.is_owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "That subscription is not yours.")
    try:
        provider = billing.get_provider()
        provider.simulate(sub.provider_subscription_id, body.event)  # type: ignore[attr-defined]
        billing.process_event(
            db,
            provider_name="fake",
            event_id=f"fake-{uuid.uuid4().hex}",
            event_type=f"subscription.{body.event}",
            payload_hash=None,
            provider_subscription_id=sub.provider_subscription_id,
            provider=provider,
        )
    except BillingError as exc:
        raise _provider_error(exc) from None
    db.commit()
    return _sub_out(sub)


# ---------------------------------------------------------------- owner: complimentary grants


class GrantCreate(BaseModel):
    plan_key: str = "pro"
    reason: str = Field(..., min_length=3, max_length=500)
    starts_at: datetime | None = None
    expires_at: datetime | None = None


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _grant_out(g: PlanGrant) -> dict[str, Any]:
    return {
        "id": g.id,
        "user_id": g.user_id,
        "plan_key": g.plan_key,
        "starts_at": _iso(g.starts_at),
        "expires_at": _iso(g.expires_at),
        "granted_by_user_id": g.granted_by_user_id,
        "reason": g.reason,
        "created_at": _iso(g.created_at),
        "revoked_at": _iso(g.revoked_at),
    }


@admin.get("/users/{user_id}/grants", response_model=list[dict], dependencies=[StepUp])
def list_grants(user_id: int, db: DbSession) -> list[dict[str, Any]]:
    rows = db.execute(select(PlanGrant).where(PlanGrant.user_id == user_id).order_by(PlanGrant.id)).scalars()
    return [_grant_out(g) for g in rows]


@admin.post(
    "/users/{user_id}/grants",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    dependencies=[StepUp],
)
def create_grant(
    user_id: int, body: GrantCreate, db: DbSession, principal: PrincipalDep, request: Request
) -> dict[str, Any]:
    if body.plan_key != "pro":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Only a pro grant can be given.")
    if db.get(User, user_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    starts = _utc(body.starts_at) if body.starts_at else datetime.now(UTC)
    expires = _utc(body.expires_at) if body.expires_at else None
    if expires is not None and expires <= starts:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The end date must be after the start.")
    grant = PlanGrant(
        user_id=user_id,
        plan_key=body.plan_key,
        starts_at=starts,
        expires_at=expires,
        granted_by_user_id=principal.user.id if principal.user is not None else None,
        reason=body.reason.strip(),
    )
    db.add(grant)
    db.flush()
    audit.record(
        db,
        "plan.grant",
        actor=principal.user,
        actor_label=actor_name(principal),
        target_type="user",
        target_id=user_id,
        after={
            "grant_id": grant.id,
            "plan": grant.plan_key,
            "expires_at": _iso(expires),
            "reason": grant.reason,
        },
        request=request,
    )
    db.commit()
    return _grant_out(grant)


@admin.delete("/users/{user_id}/grants/{grant_id}", response_model=dict, dependencies=[StepUp])
def revoke_grant(
    user_id: int, grant_id: int, db: DbSession, principal: PrincipalDep, request: Request
) -> dict[str, Any]:
    grant = db.get(PlanGrant, grant_id)
    if grant is None or grant.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Grant not found")
    if grant.revoked_at is None:
        grant.revoked_at = datetime.now(UTC)
        audit.record(
            db,
            "plan.grant_revoke",
            actor=principal.user,
            actor_label=actor_name(principal),
            target_type="user",
            target_id=user_id,
            before={"grant_id": grant.id},
            request=request,
        )
    db.commit()
    return _grant_out(grant)
