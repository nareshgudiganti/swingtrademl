"""One-time codes that hand a finished Google sign-in to the app. The code,
not a session token, is what travels in the browser's address bar."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.db.models.audit import LoginCode
from swing_trade_ml.db.models.session import User

CODE_TTL_SECONDS = 60


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def issue(db: Session, user: User) -> str:
    code = secrets.token_urlsafe(32)
    db.add(
        LoginCode(
            code_hash=_hash(code),
            user_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(seconds=CODE_TTL_SECONDS),
        )
    )
    db.flush()
    return code


def redeem(db: Session, code: str) -> User | None:
    """The account the code was issued for, once; None if unknown, used, expired or disabled."""
    row = db.execute(
        select(LoginCode).where(LoginCode.code_hash == _hash(code)).with_for_update()
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if row is None or row.used_at is not None or row.expires_at <= now:
        return None
    row.used_at = now
    db.flush()
    user = db.get(User, row.user_id)
    return user if user is not None and user.is_active else None
