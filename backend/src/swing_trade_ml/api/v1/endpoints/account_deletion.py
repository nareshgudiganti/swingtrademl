"""Customer account deletion (behind ACCOUNT_DELETION_ENABLED).

- `POST /account/deletion/request`  signed-in person + password (local accounts). Sends a confirm link.
- `POST /account/deletion/confirm`  public; the one-time emailed token is the credential. Cancels a live Pro
  subscription first (a failure schedules nothing), signs the person out everywhere, starts the grace period
  (ACCOUNT_DELETION_GRACE_DAYS, default 14) and emails a "keep my account" link.
- `POST /account/deletion/cancel`   public; the "keep my account" token. Always works during the grace period,
  even while the switch is off.
- `GET  /account/deletion`          signed-in person: where their request stands.
- `GET  /account/export`            signed-in person: their own data as JSON.

request / confirm / status / export answer 404 while the switch is off. The owner account is refused.
Signing in is blocked from confirmation onward (endpoints/auth.py), which is why cancel uses an emailed token.
The actual removal is the daily job (services/account_deletion.py::process_due).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from swing_trade_ml.api.deps import DbSession, Principal, get_principal
from swing_trade_ml.api.rate_limit import auth_limit
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.session import User
from swing_trade_ml.services import account_deletion as svc
from swing_trade_ml.services import audit
from swing_trade_ml.services.billing.base import BillingError
from swing_trade_ml.services.email import get_sender
from swing_trade_ml.services.email.templates import deletion_confirm_email, deletion_scheduled_email

log = get_logger(__name__)

NOT_AVAILABLE = "Not found"
BAD_LINK = "This link is not valid any more."
BILLING_FAILED = (
    "We could not cancel your Pro subscription just now, so nothing has been changed. "
    "Please try the link again in a few minutes."
)


def deletion_enabled() -> None:
    if not settings.ACCOUNT_DELETION_ENABLED:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_AVAILABLE)


router = APIRouter(prefix="/account", tags=["account"])
gated = [Depends(deletion_enabled)]


def person(principal: Annotated[Principal, Depends(get_principal)]) -> User:
    """A signed-in person. The shared API key has no person behind it, so it is refused."""
    if principal.user is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sign in as a person to manage your account.")
    return principal.user


class RequestIn(BaseModel):
    password: str | None = Field(None, max_length=512)


class TokenIn(BaseModel):
    token: str = Field(..., min_length=1, max_length=256)


def _send(to: str, message: tuple[str, str, str]) -> None:
    subject, text, html = message
    try:
        get_sender().send(to, subject, text, html)
    except Exception as exc:  # noqa: BLE001 - an email failure must not undo a committed change
        log.error("account_deletion.email_failed", error=str(exc))


@router.post("/deletion/request", dependencies=[*gated, Depends(auth_limit)])
def request_deletion(
    payload: RequestIn,
    db: DbSession,
    request: Request,
    background: BackgroundTasks,
    user: Annotated[User, Depends(person)],
) -> dict:
    ip = request.client.host if request.client else None
    try:
        raw = svc.request_deletion(db, user, payload.password, ip)
    except svc.DeletionRefusedError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    audit.record(
        db, "account.deletion_requested", actor=user, target_type="user", target_id=user.id, request=request
    )
    db.commit()
    if user.email:
        background.add_task(_send, user.email, deletion_confirm_email(raw))
    return {"message": "We have emailed you a link. Open it to confirm. Nothing is deleted until you do."}


@router.post("/deletion/confirm", dependencies=[*gated, Depends(auth_limit)])
def confirm_deletion(payload: TokenIn, db: DbSession, request: Request, background: BackgroundTasks) -> dict:
    try:
        with db.begin_nested():  # a failed cancel undoes the token use and everything else here
            scheduled = svc.confirm_deletion(db, payload.token)
    except BillingError as exc:  # the token is not used up: the link still works
        log.warning("account_deletion.confirm_billing_failed", error=str(exc))
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, BILLING_FAILED) from exc
    if scheduled is None:
        db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, BAD_LINK)
    user = scheduled.user
    audit.record(
        db,
        "account.deletion_confirmed",
        actor=user,
        target_type="user",
        target_id=user.id,
        after={
            "scheduled_for": scheduled.scheduled_for.isoformat(),
            "cancelled_subscriptions": scheduled.cancelled_subscriptions,
        },
        request=request,
    )
    db.commit()
    when = scheduled.scheduled_for.strftime("%d %b %Y")
    if user.email:
        background.add_task(
            _send,
            user.email,
            deletion_scheduled_email(scheduled.cancel_token, when, scheduled.cancelled_subscriptions > 0),
        )
    return {
        "message": (
            f"Your account will be deleted on {when}. You are signed out. Use the link we emailed to keep it."
        ),
        "scheduled_for": scheduled.scheduled_for.isoformat(),
    }


@router.post("/deletion/cancel", dependencies=[Depends(auth_limit)])
def cancel_deletion(payload: TokenIn, db: DbSession, request: Request) -> dict:
    user = svc.cancel_deletion(db, payload.token)
    if user is None:
        db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, BAD_LINK)
    audit.record(
        db, "account.deletion_cancelled", actor=user, target_type="user", target_id=user.id, request=request
    )
    db.commit()
    return {"message": "Your account is kept. You can sign in again. Start Pro again if you had it."}


@router.get("/deletion", dependencies=gated)
def deletion_status(db: DbSession, user: Annotated[User, Depends(person)]) -> dict:
    row = svc.latest_request(db, user.id)
    return {
        "enabled": True,
        "protected": svc.is_protected(user),
        "grace_days": settings.ACCOUNT_DELETION_GRACE_DAYS,
        "status": row.status if row else None,
        "scheduled_for": row.scheduled_for.isoformat() if row and row.scheduled_for else None,
    }


@router.get("/export", dependencies=gated)
def export(db: DbSession, user: Annotated[User, Depends(person)]) -> dict:
    return svc.export_data(db, user)
