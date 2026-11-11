"""One-time email tokens (verify email, reset password). Only the sha256 hash is stored."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from swing_trade_ml.db.models.auth_tokens import AuthToken
from swing_trade_ml.db.models.session import User

TTL = {
    "verify_email": timedelta(hours=24),
    "reset_password": timedelta(hours=1),
    "delete_account": timedelta(hours=1),
    # The "changed my mind" link sent when deletion is confirmed; the grace period (default 14 days) is
    # the real limit, enforced by services/account_deletion.py.
    "cancel_delete": timedelta(days=30),
}


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def issue(db: Session, user: User, purpose: str, ip: str | None = None) -> str:
    """Make a new token; older unused ones for the same purpose stop working. Caller commits."""
    now = datetime.now(UTC)
    db.execute(
        update(AuthToken)
        .where(AuthToken.user_id == user.id, AuthToken.purpose == purpose, AuthToken.used_at.is_(None))
        .values(used_at=now)
    )
    raw = secrets.token_urlsafe(32)
    db.add(
        AuthToken(
            user_id=user.id,
            purpose=purpose,
            token_hash=hash_token(raw),
            created_at=now,
            expires_at=now + TTL[purpose],
            requested_ip=ip,
        )
    )
    db.flush()
    return raw


def _live_row(db: Session, raw: str, purpose: str, lock: bool) -> AuthToken | None:
    q = select(AuthToken).where(AuthToken.token_hash == hash_token(raw or ""), AuthToken.purpose == purpose)
    row = db.execute(q.with_for_update() if lock else q).scalar_one_or_none()
    if row is None or row.used_at is not None or row.expires_at <= datetime.now(UTC):
        return None
    return row


def peek(db: Session, raw: str, purpose: str) -> User | None:
    """Who the token belongs to, without using it up (None if unknown/used/expired)."""
    row = _live_row(db, raw, purpose, lock=False)
    return db.get(User, row.user_id) if row else None


def redeem(db: Session, raw: str, purpose: str) -> User | None:
    """Single use: returns the user and marks the token used, or None if unknown/used/expired."""
    row = _live_row(db, raw, purpose, lock=True)
    if row is None:
        return None
    row.used_at = datetime.now(UTC)
    return db.get(User, row.user_id)
