"""Authentication primitives: the machine-to-machine API key and dashboard JWTs."""

from __future__ import annotations

import hmac
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt
from fastapi import Header, HTTPException, status

from swing_trade_ml.core.config import settings

# bcrypt directly, not passlib's CryptContext wrapper: passlib has been
# unmaintained since 2020 and its bcrypt handler breaks against bcrypt>=4.0's
# API (misreports "password too long" for ordinary short passwords). bcrypt
# itself needs no wrapper — hash/checkpw is the whole interface.
_BCRYPT_MAX_BYTES = 72  # bcrypt's own hard limit; truncate rather than error


def hash_password(plain: str) -> str:
    truncated = plain.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(truncated, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    truncated = plain.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.checkpw(truncated, hashed.encode("utf-8"))


def create_access_token(subject: str, extra: dict[str, Any] | None = None) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES),
        **(extra or {}),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token has expired") from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc


async def require_api_key(x_api_key: str = Header(..., alias="X-API-Key")) -> None:
    """Guard protected routes with the shared secret.

    Compared with `hmac.compare_digest` rather than `==` so the comparison time
    doesn't leak how many leading characters a guess got right.
    """
    if not hmac.compare_digest(x_api_key, settings.API_KEY):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing API key")
