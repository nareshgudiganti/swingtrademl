"""Shared FastAPI dependencies."""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.security import decode_access_token
from swing_trade_ml.db.models.session import User
from swing_trade_ml.db.session import get_db

DbSession = Annotated[Session, Depends(get_db)]

bearer_scheme = HTTPBearer(auto_error=False)


def _user_from_bearer(credentials: HTTPAuthorizationCredentials, db: Session) -> User:
    payload = decode_access_token(credentials.credentials)
    username = payload.get("sub")
    if not username:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Malformed token")

    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")
    return user


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: DbSession,
) -> User:
    """Resolve the dashboard user from a bearer token. Used where a human user
    identity is actually needed (e.g. showing "logged in as"), not just any
    valid credential — see `require_auth` for that."""
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    return _user_from_bearer(credentials, db)


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_auth(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: DbSession,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    """Gate for every route that can read positions or move money.

    Accepts either credential:
    - A bearer JWT from `POST /auth/login` — what the dashboard sends after a
      real username/password login.
    - The shared `X-API-Key` secret — kept for scripts, curl, CI, and other
      machine callers that have no user account and shouldn't need one.

    The bearer token is checked first when present, since a JWT identifies a
    specific person and is preferable for anything the dashboard does.
    """
    if credentials is not None:
        _user_from_bearer(credentials, db)
        return

    if x_api_key is not None and hmac.compare_digest(x_api_key, settings.API_KEY):
        return

    raise HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Provide a valid Authorization bearer token or X-API-Key header",
    )
