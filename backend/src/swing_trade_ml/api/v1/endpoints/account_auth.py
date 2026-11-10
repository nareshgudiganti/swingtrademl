"""Self-service sign-up, email verification and password recovery (backend only).

- `POST /auth/register`: 404 unless ALLOW_SIGNUP is on. Same answer for a new or an existing email;
  never returns a login token.
  New email: makes a Free `member`, sends a verification email. Existing email: changes nothing,
  privately sends a rate-limited "someone tried to sign up" notice.
- `POST /auth/verify-email`, `/auth/resend-verification`, `/auth/forgot-password`, `/auth/reset-password`.
  The resend/forgot routes give the SAME answer whether or not the account exists.
- `POST /admin/users/{id}/send-reset`: the signed-in owner can send someone a reset email. The owner never
  sets or sees the password, and the token is never returned.

Emails are sent after the response (background task), so the answer takes the same time either way.
Tokens: services/auth_tokens.py (hash only, single use). Sign-in enforcement lives in endpoints/auth.py
behind REQUIRE_EMAIL_VERIFICATION (default off).
"""

from __future__ import annotations

import hashlib
import threading
import time
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from swing_trade_ml.api.deps import DbSession, Principal
from swing_trade_ml.api.rate_limit import auth_limit, claim_once, public_limit
from swing_trade_ml.api.v1.endpoints.auth import _unique_username_from_email
from swing_trade_ml.api.v1.endpoints.invites import normalise_email, require_owner_signed_in, valid_email
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.core.mobile import normalise_full_name, normalise_mobile
from swing_trade_ml.core.password_policy import check_password
from swing_trade_ml.core.security import hash_password
from swing_trade_ml.db.models.session import User
from swing_trade_ml.services import audit, auth_tokens
from swing_trade_ml.services.email import get_sender
from swing_trade_ml.services.email.templates import already_registered_email, reset_email, verification_email

log = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])
admin = APIRouter(prefix="/admin/users", tags=["auth"])

REGISTER_CLOSED = "Not found"
REGISTER_ACCEPTED = "If this email can be used, we have sent you a message with the next steps."
NOTICE_EVERY_SECONDS = 3600  # at most one "already registered" notice per address per hour
VERIFY_RESENT = "If that email belongs to an account that still needs confirming, we have sent a new link."
RESET_SENT = "If that email belongs to an account, we have sent a link to reset the password."
BAD_LINK = "This link is not valid any more. Please ask for a new one."


class RegisterIn(BaseModel):
    full_name: str = Field(..., max_length=200)
    email: str = Field(..., max_length=254)
    password: str = Field(..., max_length=512)
    mobile: str | None = Field(None, max_length=40)


class TokenIn(BaseModel):
    token: str = Field(..., min_length=1, max_length=256)


class EmailIn(BaseModel):
    email: str = Field(..., max_length=254)


class ResetIn(BaseModel):
    token: str = Field(..., min_length=1, max_length=256)
    new_password: str = Field(..., max_length=512)


_notice_lock = threading.Lock()
_notice_last: dict[str, float] = {}


def _notice_allowed(email: str) -> bool:
    """True at most once per hour per address. Shared across workers through Redis (the same client the
    request limiters use); if Redis is off or down it falls back to this process's memory, where several
    workers could each send one per hour. Either way it never changes the HTTP answer."""
    digest = hashlib.sha256(email.encode("utf-8")).hexdigest()  # never the raw email in a Redis key
    shared = claim_once(f"notice:already-registered:{digest}", NOTICE_EVERY_SECONDS)
    if shared is not None:
        return shared
    now = time.monotonic()
    with _notice_lock:
        if len(_notice_last) > 5000:  # keep memory bounded
            for k in [k for k, t in _notice_last.items() if now - t >= NOTICE_EVERY_SECONDS]:
                del _notice_last[k]
        last = _notice_last.get(email)
        if last is not None and now - last < NOTICE_EVERY_SECONDS:
            return False
        _notice_last[email] = now
        return True


def _send(to: str, message: tuple[str, str, str]) -> None:
    subject, text, html = message
    get_sender().send(to, subject, text, html)


def _bad(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail)


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("/register", status_code=status.HTTP_201_CREATED, dependencies=[Depends(auth_limit)])
def register(payload: RegisterIn, db: DbSession, request: Request, background: BackgroundTasks) -> dict:
    """Same public answer whether the email is new or already registered (no account enumeration).

    Validation comes first and never looks at the database. After that both cases do the same work
    (hash the password, look the email up with one query), return the same 201 + message, and queue one
    email: a verification link for a new address, a private "someone tried to sign up" notice for an
    existing one. No login token is ever returned; the client signs in afterwards.
    """
    if not settings.ALLOW_SIGNUP:
        raise HTTPException(status.HTTP_404_NOT_FOUND, REGISTER_CLOSED)
    try:
        name = normalise_full_name(payload.full_name)
        mobile = normalise_mobile(payload.mobile) if payload.mobile and payload.mobile.strip() else None
    except ValueError as exc:
        raise _bad(str(exc)) from exc
    email = normalise_email(payload.email)
    if not valid_email(email):
        raise _bad("Enter a valid email address.")
    problems = check_password(payload.password, email=email, name=name)
    if problems:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, " ".join(problems))

    hashed = hash_password(payload.password)  # done in both cases so the work is the same shape
    taken = db.execute(select(User.id).where(func.lower(User.email) == email).limit(1)).first()
    message: tuple[str, str, str] | None = None
    if not taken:
        user = User(
            username=_unique_username_from_email(db, email),
            email=email,
            full_name=name,
            mobile=mobile,
            hashed_password=hashed,
            auth_provider="local",
            email_verified_at=None,
            is_active=True,
            # Spelled out, never inferred: a self-made account is an ordinary free member.
            role="member",
            is_superuser=False,
        )
        db.add(user)
        try:
            db.flush()
        except IntegrityError:  # raced with another sign-up for the same email/username
            db.rollback()
            taken = True
        else:
            raw = auth_tokens.issue(db, user, "verify_email", _ip(request))
            audit.record(
                db,
                "auth.register",
                actor=user,
                target_type="user",
                target_id=user.id,
                after={"verification_required": settings.REQUIRE_EMAIL_VERIFICATION},
                request=request,
            )
            db.commit()
            message = verification_email(raw)
    if taken and _notice_allowed(email):
        message = already_registered_email()
    if message is not None:
        background.add_task(_send, email, message)
    return {"message": REGISTER_ACCEPTED}


@router.post("/verify-email", dependencies=[Depends(auth_limit)])
def verify_email(payload: TokenIn, db: DbSession, request: Request) -> dict:
    user = auth_tokens.redeem(db, payload.token, "verify_email")
    if user is None:
        db.commit()
        raise _bad(BAD_LINK)
    if user.email_verified_at is None:
        user.email_verified_at = datetime.now(UTC)
    audit.record(
        db, "auth.email_verified", actor=user, target_type="user", target_id=user.id, request=request
    )
    db.commit()
    return {"message": "Your email is confirmed. You can sign in."}


@router.post("/resend-verification", dependencies=[Depends(public_limit)])
def resend_verification(
    payload: EmailIn, db: DbSession, request: Request, background: BackgroundTasks
) -> dict:
    email = normalise_email(payload.email)
    user = db.execute(select(User).where(func.lower(User.email) == email).limit(1)).scalar_one_or_none()
    raw = None
    if (
        user is not None
        and user.auth_provider == "local"
        and user.is_active
        and user.email_verified_at is None
    ):
        raw = auth_tokens.issue(db, user, "verify_email", _ip(request))
        db.commit()
    if raw is not None:
        background.add_task(_send, email, verification_email(raw))
    else:
        auth_tokens.hash_token("equalise-timing")  # same shape of work either way
    return {"message": VERIFY_RESENT}


@router.post("/forgot-password", dependencies=[Depends(public_limit)])
def forgot_password(payload: EmailIn, db: DbSession, request: Request, background: BackgroundTasks) -> dict:
    email = normalise_email(payload.email)
    user = db.execute(select(User).where(func.lower(User.email) == email).limit(1)).scalar_one_or_none()
    if user is not None and user.auth_provider == "local" and user.is_active:
        raw = auth_tokens.issue(db, user, "reset_password", _ip(request))
        audit.record(
            db, "auth.reset_requested", actor=user, target_type="user", target_id=user.id, request=request
        )
        db.commit()
        background.add_task(_send, email, reset_email(raw))
    else:
        auth_tokens.hash_token("equalise-timing")
    return {"message": RESET_SENT}


@router.post("/reset-password", dependencies=[Depends(auth_limit)])
def reset_password(payload: ResetIn, db: DbSession, request: Request) -> dict:
    owner = auth_tokens.peek(db, payload.token, "reset_password")
    if owner is None:
        raise _bad(BAD_LINK)
    problems = check_password(payload.new_password, email=owner.email, name=owner.full_name)
    if problems:  # checked before the link is used up, so a weak try does not burn it
        raise HTTPException(status.HTTP_400_BAD_REQUEST, " ".join(problems))
    user = auth_tokens.redeem(db, payload.token, "reset_password")
    if user is None:
        db.commit()
        raise _bad(BAD_LINK)
    user.hashed_password = hash_password(payload.new_password)
    user.token_version = (user.token_version or 0) + 1  # ends every existing session
    user.failed_login_count = 0
    user.locked_until = None
    if user.email_verified_at is None:
        user.email_verified_at = datetime.now(UTC)  # they just proved they own the inbox
    audit.record(db, "auth.reset_done", actor=user, target_type="user", target_id=user.id, request=request)
    db.commit()
    return {"message": "Your password has been changed. Please sign in."}


@admin.post("/{user_id}/send-reset")
def admin_send_reset(
    user_id: int,
    db: DbSession,
    request: Request,
    background: BackgroundTasks,
    principal: Principal = Depends(require_owner_signed_in),
) -> dict:
    target = db.get(User, user_id)
    if target is None or not target.email:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such account, or it has no email address.")
    raw = auth_tokens.issue(db, target, "reset_password", _ip(request))
    audit.record(
        db,
        "auth.admin_reset_sent",
        actor=principal.user,
        target_type="user",
        target_id=target.id,
        request=request,
    )
    db.commit()
    background.add_task(_send, target.email, reset_email(raw))
    return {"message": "A password reset email has been sent to that member."}
