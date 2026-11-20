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


def _hash(code: str, binding: str | None = None) -> str:
    """What is stored. With a `binding` (the browser's sign-in cookie, issue #373) the stored hash
    covers code and binding together, so the code alone, or with another browser's cookie, finds
    no row: it can only be redeemed by the browser that started the sign-in."""
    material = code if binding is None else f"{code}:{binding}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def issue(db: Session, user: User, binding: str | None = None) -> str:
    code = secrets.token_urlsafe(32)
    db.add(
        LoginCode(
            code_hash=_hash(code, binding),
            user_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(seconds=CODE_TTL_SECONDS),
        )
    )
    db.flush()
    return code


def redeem(db: Session, code: str, binding: str | None = None) -> User | None:
    """The account the code was issued for, once; None if unknown, used, expired or disabled,
    or if `binding` is not the one it was issued with (a wrong browser does not spend the code)."""
    row = db.execute(
        select(LoginCode).where(LoginCode.code_hash == _hash(code, binding)).with_for_update()
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if row is None or row.used_at is not None or row.expires_at <= now:
        return None
    row.used_at = now
    db.flush()
    user = db.get(User, row.user_id)
    return user if user is not None and user.is_active else None
