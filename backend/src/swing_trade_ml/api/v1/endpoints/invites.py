"""Invite-only access (New look wave 4, owner decision 2026-10-25).

- `POST /auth/invite-request` (public): anyone may ask for a place. The answer is the same
  whether or not the email already asked, already has an account, or was stored at all,
  so the form can't be used to learn who is a member.
- `/admin/invites/*` (the signed-in owner only, not the shared API key): list requests,
  approve (which makes a one-time invite code, shown once), reject, or make a new code.
- Sign-up itself stays in endpoints/auth.py: it accepts an approved, unused invite code
  for the matching email even while ALLOW_SIGNUP is off, and creates an ordinary member.

No email is ever sent from here: there is no email service. The owner passes the sign-up
link on by hand.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from swing_trade_ml.api.deps import DbSession, Principal, require_owner
from swing_trade_ml.api.rate_limit import auth_limit
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.invites import EXPERIENCE_LEVELS, LANGUAGES, InviteRequest
from swing_trade_ml.db.models.session import User
from swing_trade_ml.services import audit

log = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

#: Same words for every outcome of a request (stored, already waiting, already a member, list full).
REQUEST_RECEIVED = (
    "Thanks. Your request is with the owner, who will contact you if a place opens. "
    "Nothing is sent automatically."
)
#: More waiting requests than this and new ones are not stored (still the same answer), so a
#: flood can't fill the table. The owner clears the list in Admin > Invites.
MAX_PENDING = 1000

_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s.]{2,}$")
_PHONE_RE = re.compile(r"^\+?[0-9][0-9 \-]{5,18}$")


def normalise_email(email: str) -> str:
    return email.strip().lower()


def valid_email(email: str) -> bool:
    return len(email) <= 254 and bool(_EMAIL_RE.match(email))


def hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def code_matches(code: str, code_hash: str | None) -> bool:
    return bool(code_hash) and hmac.compare_digest(hash_code(code), code_hash or "")


class InviteRequestIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    email: str = Field(..., max_length=254)
    phone: str | None = Field(None, max_length=20)
    experience: str
    language: str = "english"

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, v: object) -> object:
        return " ".join(v.split()) if isinstance(v, str) else v

    @field_validator("email", mode="before")
    @classmethod
    def _email(cls, v: object) -> object:
        if not isinstance(v, str) or not valid_email(normalise_email(v)):
            raise ValueError("Please enter a valid email address.")
        return normalise_email(v)

    @field_validator("phone", mode="before")
    @classmethod
    def _phone(cls, v: object) -> object:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        if not isinstance(v, str) or not _PHONE_RE.match(v.strip()):
            raise ValueError("Please enter a phone number with digits only, or leave it empty.")
        return v.strip()

    @field_validator("experience")
    @classmethod
    def _experience(cls, v: str) -> str:
        if v not in EXPERIENCE_LEVELS:
            raise ValueError(f"Choose one of: {', '.join(EXPERIENCE_LEVELS)}")
        return v

    @field_validator("language")
    @classmethod
    def _language(cls, v: str) -> str:
        if v not in LANGUAGES:
            raise ValueError(f"Choose one of: {', '.join(LANGUAGES)}")
        return v


@router.post("/invite-request", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(auth_limit)])
def request_invite(payload: InviteRequestIn, db: DbSession, request: Request) -> dict[str, str]:
    """Ask for a place. Always the same answer once the input is valid (see REQUEST_RECEIVED)."""
    already_waiting = db.execute(
        select(InviteRequest.id).where(
            InviteRequest.email == payload.email, InviteRequest.status == "pending"
        )
    ).first()
    pending_count = db.execute(
        select(func.count()).select_from(InviteRequest).where(InviteRequest.status == "pending")
    ).scalar_one()
    if already_waiting is None and pending_count < MAX_PENDING:
        row = InviteRequest(
            name=payload.name,
            email=payload.email,
            phone=payload.phone,
            experience=payload.experience,
            language=payload.language,
            status="pending",
        )
        try:
            with db.begin_nested():  # a twin request racing this one hits the unique index, not a 500
                db.add(row)
                db.flush()
            audit.record(
                db,
                "invite.requested",
                actor_label="public",
                target_type="invite",
                target_id=row.id,
                request=request,
            )
            db.commit()
        except IntegrityError:
            pass  # the savepoint above was rolled back; the twin request is already stored
    elif already_waiting is None:
        log.warning("invite.request_list_full", pending=pending_count)
    return {"message": REQUEST_RECEIVED}


# ------------------------------------------------------------------ admin --


async def require_owner_signed_in(principal: Annotated[Principal, Depends(require_owner)]) -> Principal:
    """Invites name real people and open accounts, so they need the owner signed in as a person:
    the shared API key (scripts) is refused, and every decision records who made it."""
    if principal.user is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sign in as the owner to manage invites.")
    return principal


OwnerDep = Annotated[Principal, Depends(require_owner_signed_in)]

admin = APIRouter(prefix="/admin/invites", tags=["invites"], dependencies=[Depends(require_owner_signed_in)])


class DecisionIn(BaseModel):
    note: str | None = Field(None, max_length=500)


def _out(row: InviteRequest, has_account: bool) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "email": row.email,
        "phone": row.phone,
        "experience": row.experience,
        "language": row.language,
        "status": row.status,
        "created_at": row.created_at,
        "decided_at": row.decided_at,
        "decided_by": row.decided_by,
        "note": row.note,
        "used": row.used_at is not None,
        "used_at": row.used_at,
        "has_account": has_account,
    }


def _emails_with_accounts(db: Session, emails: set[str]) -> set[str]:
    if not emails:
        return set()
    found = db.execute(select(func.lower(User.email)).where(func.lower(User.email).in_(emails))).scalars()
    return {e for e in found if e}


@admin.get("", response_model=list[dict])
def list_invites(
    db: DbSession, status_filter: Annotated[str | None, Query(alias="status")] = None
) -> list[dict[str, Any]]:
    query = select(InviteRequest).order_by(InviteRequest.created_at.desc(), InviteRequest.id.desc())
    if status_filter:
        query = query.where(InviteRequest.status == status_filter)
    rows = db.execute(query.limit(500)).scalars().all()
    members = _emails_with_accounts(db, {r.email for r in rows})
    # Waiting requests first, newest first within each group.
    rows = sorted(rows, key=lambda r: r.status != "pending")
    return [_out(r, r.email in members) for r in rows]


def _load(db: Session, invite_id: int) -> InviteRequest:
    row = db.execute(
        select(InviteRequest).where(InviteRequest.id == invite_id).with_for_update()
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such invite request.")
    return row


def _new_code(row: InviteRequest) -> str:
    code = secrets.token_urlsafe(12)
    row.code_hash = hash_code(code)
    return code


def _with_code(db: Session, row: InviteRequest, code: str) -> dict[str, Any]:
    out = _out(row, row.email in _emails_with_accounts(db, {row.email}))
    # Shown once: only its hash is kept. The owner sends this link on by hand.
    out["invite_code"] = code
    out["signup_path"] = "/signup?" + urlencode({"invite": code, "email": row.email})
    return out


@admin.post("/{invite_id}/approve", response_model=dict)
def approve_invite(
    invite_id: int, db: DbSession, principal: OwnerDep, request: Request, body: DecisionIn | None = None
) -> dict[str, Any]:
    row = _load(db, invite_id)
    if row.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, f"This request is already {row.status}.")
    code = _new_code(row)
    row.status = "approved"
    row.decided_at = datetime.now(UTC)
    row.decided_by = principal.user.username  # type: ignore[union-attr]  (require_owner_signed_in)
    row.note = body.note if body else None
    audit.record(
        db,
        "invite.approved",
        actor=principal.user,
        target_type="invite",
        target_id=row.id,
        after={"status": "approved"},
        request=request,
    )
    db.commit()
    return _with_code(db, row, code)


@admin.post("/{invite_id}/new-code", response_model=dict)
def new_invite_code(invite_id: int, db: DbSession, principal: OwnerDep, request: Request) -> dict[str, Any]:
    """A fresh code for an approved, unused invite (the old one stops working)."""
    row = _load(db, invite_id)
    if row.status != "approved" or row.used_at is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Only an approved invite that is not used yet gets a new code."
        )
    code = _new_code(row)
    audit.record(
        db, "invite.new_code", actor=principal.user, target_type="invite", target_id=row.id, request=request
    )
    db.commit()
    return _with_code(db, row, code)


@admin.post("/{invite_id}/reject", response_model=dict)
def reject_invite(
    invite_id: int, db: DbSession, principal: OwnerDep, request: Request, body: DecisionIn | None = None
) -> dict[str, Any]:
    """Refuse a waiting request, or withdraw an approved invite nobody has used yet."""
    row = _load(db, invite_id)
    if row.used_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This invite was already used to make an account.")
    if row.status == "rejected":
        raise HTTPException(status.HTTP_409_CONFLICT, "This request is already rejected.")
    before = row.status
    row.status = "rejected"
    row.code_hash = None
    row.decided_at = datetime.now(UTC)
    row.decided_by = principal.user.username  # type: ignore[union-attr]
    row.note = body.note if body else None
    audit.record(
        db,
        "invite.rejected",
        actor=principal.user,
        target_type="invite",
        target_id=row.id,
        before={"status": before},
        after={"status": "rejected"},
        request=request,
    )
    db.commit()
    return _out(row, row.email in _emails_with_accounts(db, {row.email}))
