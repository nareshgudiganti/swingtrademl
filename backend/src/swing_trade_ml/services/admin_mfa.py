"""Admin two-step sign-in: authenticator-app codes (TOTP), recovery codes, and a short step-up token.

The step-up token is signed with a key derived from the session secret, so it can never be used
as a normal sign-in token, and it is tied to one admin and their current session version.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

import jwt
import pyotp
from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.admin_mfa import AdminMfa, AdminRecoveryCode
from swing_trade_ml.db.models.session import User

ISSUER = "TradeMind"
STEP_UP_MINUTES = 15
MAX_FAILURES = 5
LOCK_MINUTES = 15
RECOVERY_CODE_COUNT = 10


class MfaError(Exception):
    """Plain-English reason a code was not accepted."""


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime | None) -> datetime | None:
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=UTC)


def get(db: Session, user: User) -> AdminMfa | None:
    return db.get(AdminMfa, user.id)


def is_enrolled(db: Session, user: User) -> bool:
    row = get(db, user)
    return row is not None and row.enabled_at is not None


def start_setup(db: Session, user: User) -> tuple[str, str]:
    """New secret (not active until the first code is proven). Returns (secret, otpauth uri)."""
    row = get(db, user)
    secret = pyotp.random_base32()
    if row is None:
        db.add(AdminMfa(user_id=user.id, secret=secret))
    else:
        row.secret, row.enabled_at, row.last_step, row.failed_count, row.locked_until = (
            secret,
            None,
            0,
            0,
            None,
        )
    db.flush()
    label = user.email or user.username
    return secret, pyotp.TOTP(secret).provisioning_uri(name=label, issuer_name=ISSUER)


def _hash_recovery(code: str) -> str:
    return hashlib.sha256(code.replace("-", "").replace(" ", "").strip().lower().encode()).hexdigest()


def _check_totp(row: AdminMfa, code: str) -> bool:
    """True once per time step. The same code cannot be used twice."""
    code = (code or "").replace(" ", "")
    if not (code.isdigit() and len(code) == 6):
        return False
    totp = pyotp.TOTP(row.secret)
    now = _now()
    for offset in (-1, 0, 1):
        step = int(now.timestamp() // 30) + offset
        if hmac.compare_digest(totp.at(step * 30), code):
            if step <= (row.last_step or 0):
                return False
            row.last_step = step
            return True
    return False


def _use_recovery(db: Session, user: User, code: str) -> bool:
    digest = _hash_recovery(code)
    for rc in db.execute(
        select(AdminRecoveryCode).where(
            AdminRecoveryCode.user_id == user.id, AdminRecoveryCode.used_at.is_(None)
        )
    ).scalars():
        if hmac.compare_digest(rc.code_hash, digest):
            rc.used_at = _now()
            return True
    return False


def _guard_lock(row: AdminMfa) -> None:
    locked = _aware(row.locked_until)
    if locked is not None and locked > _now():
        raise MfaError("Too many wrong codes. Try again in a few minutes.")


def _fail(row: AdminMfa) -> None:
    row.failed_count = (row.failed_count or 0) + 1
    if row.failed_count >= MAX_FAILURES:
        row.locked_until = _now() + timedelta(minutes=LOCK_MINUTES)
        row.failed_count = 0


def new_recovery_codes(db: Session, user: User) -> list[str]:
    """Replace all recovery codes. The plain codes are returned once and never stored."""
    for rc in db.execute(select(AdminRecoveryCode).where(AdminRecoveryCode.user_id == user.id)).scalars():
        db.delete(rc)
    codes = [f"{secrets.token_hex(3)}-{secrets.token_hex(3)}" for _ in range(RECOVERY_CODE_COUNT)]
    for c in codes:
        db.add(AdminRecoveryCode(user_id=user.id, code_hash=_hash_recovery(c)))
    db.flush()
    return codes


def enable(db: Session, user: User, code: str) -> list[str]:
    """Prove the first code, switch MFA on and hand out recovery codes (shown once)."""
    row = get(db, user)
    if row is None or row.enabled_at is not None:
        raise MfaError("Start setup first.")
    _guard_lock(row)
    if not _check_totp(row, code):
        _fail(row)
        db.commit()
        raise MfaError("That code is not right. Check the time on your phone and try the next code.")
    row.enabled_at, row.failed_count = _now(), 0
    return new_recovery_codes(db, user)


def verify(db: Session, user: User, *, code: str | None, recovery_code: str | None) -> None:
    """Accept an authenticator code or a recovery code, or raise MfaError."""
    row = get(db, user)
    if row is None or row.enabled_at is None:
        raise MfaError("Two-step sign-in is not set up yet.")
    _guard_lock(row)
    ok = _use_recovery(db, user, recovery_code) if recovery_code else _check_totp(row, code or "")
    if not ok:
        _fail(row)
        db.commit()
        raise MfaError("That code is not right.")
    row.failed_count = 0


def remaining_recovery_codes(db: Session, user: User) -> int:
    return len(
        db.execute(
            select(AdminRecoveryCode.id).where(
                AdminRecoveryCode.user_id == user.id, AdminRecoveryCode.used_at.is_(None)
            )
        ).all()
    )


def _step_up_key() -> str:
    return hashlib.sha256(f"{settings.JWT_SECRET_KEY}:admin-mfa".encode()).hexdigest()


def issue_step_up(user: User) -> tuple[str, datetime]:
    exp = _now() + timedelta(minutes=STEP_UP_MINUTES)
    payload = {"typ": "admin_mfa", "uid": user.id, "tv": user.token_version or 0, "exp": exp}
    return jwt.encode(payload, _step_up_key(), algorithm="HS256"), exp


def step_up_valid(token: str | None, user: User) -> bool:
    if not token:
        return False
    try:
        p = jwt.decode(token, _step_up_key(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return False
    return (
        p.get("typ") == "admin_mfa" and p.get("uid") == user.id and p.get("tv") == (user.token_version or 0)
    )
