"""Dashboard login (local + Google) and the Zerodha Kite OAuth flow."""

from __future__ import annotations

import secrets
import time
from datetime import UTC, datetime
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.api.deps import CurrentUser, DbSession
from swing_trade_ml.brokers.kite import kite_broker
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.core.security import create_access_token, hash_password, verify_password
from swing_trade_ml.db.models.session import BrokerSession, User
from swing_trade_ml.schemas import (
    CurrentUserOut,
    KiteLoginResponse,
    KiteSessionResponse,
    LoginRequest,
    SignupRequest,
    TokenResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])
log = get_logger(__name__)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: DbSession) -> TokenResponse:
    user = db.execute(select(User).where(User.username == payload.username)).scalar_one_or_none()
    # One generic message for both branches — distinguishing "no such user" from
    # "wrong password" would let an attacker enumerate valid usernames. Also
    # covers Google-only accounts, whose hashed_password is None.
    if (
        user is None
        or not user.hashed_password
        or not verify_password(payload.password, user.hashed_password)
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect username or password")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is disabled")

    user.last_login_at = datetime.now(UTC)
    db.commit()

    return TokenResponse(
        access_token=create_access_token(user.username, {"uid": user.id}),
        expires_in_minutes=settings.JWT_EXPIRE_MINUTES,
    )


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: SignupRequest, db: DbSession) -> TokenResponse:
    """Self-registration.

    Gated by ALLOW_SIGNUP because this system can place real trades once
    TRADING_MODE=live is set — an open registration endpoint on that is an
    account-takeover surface, not a convenience. Turn it off in .env once
    everyone who should have an account does.
    """
    if not settings.ALLOW_SIGNUP:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sign-up is disabled on this instance")

    exists = db.execute(select(User).where(User.username == payload.username)).scalar_one_or_none()
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "That username is already taken")

    user = User(
        username=payload.username,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        auth_provider="local",
        is_active=True,
        last_login_at=datetime.now(UTC),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    log.info("auth.signup", username=user.username)
    return TokenResponse(
        access_token=create_access_token(user.username, {"uid": user.id}),
        expires_in_minutes=settings.JWT_EXPIRE_MINUTES,
    )


@router.get("/me", response_model=CurrentUserOut)
def me(user: CurrentUser) -> User:
    return user


@router.get("/kite/login", response_model=KiteLoginResponse)
def kite_login() -> KiteLoginResponse:
    """Start the Kite login. Must be repeated every trading day."""
    if not settings.kite_configured:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "KITE_API_KEY and KITE_API_SECRET are not configured in .env",
        )
    return KiteLoginResponse(
        login_url=kite_broker.login_url(),
        instructions=(
            "Open this URL, log in to Zerodha, and you will be redirected back "
            "automatically. Kite access tokens expire daily at ~06:00 IST, so this "
            "must be repeated each trading morning."
        ),
    )


@router.get("/kite/callback", response_class=HTMLResponse)
def kite_callback(request_token: str, db: DbSession) -> HTMLResponse:
    """Kite redirects the browser here with a request_token.

    Returns HTML rather than JSON because a human's browser lands on this page —
    Kite controls the redirect and cannot be asked to send an API key header,
    which is also why this route sits outside the X-API-Key guard.
    """
    try:
        session = kite_broker.complete_login(request_token, db)
    except Exception as exc:  # noqa: BLE001
        log.error("auth.kite.callback_failed", error=str(exc))
        return HTMLResponse(_page("❌", "Kite login failed", str(exc), ok=False), status_code=400)

    return HTMLResponse(
        _page(
            "✅",
            "Kite login successful",
            f"Authenticated as <b>{session.user_name or session.kite_user_id}</b>.<br>"
            f"This token is valid until roughly 06:00 IST tomorrow.<br>"
            f"You can close this tab.",
            ok=True,
        )
    )


@router.get("/kite/session", response_model=KiteSessionResponse)
def kite_session(db: DbSession) -> KiteSessionResponse:
    session = db.execute(
        select(BrokerSession)
        .where(BrokerSession.is_active.is_(True))
        .order_by(BrokerSession.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    if session is None:
        return KiteSessionResponse(authenticated=False)
    return KiteSessionResponse(
        authenticated=kite_broker.is_authenticated,
        kite_user_id=session.kite_user_id,
        user_name=session.user_name,
        expires_at=session.expires_at,
    )


# ------------------------------------------------------------- google oauth --

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
_STATE_TTL_SECONDS = 600

#: CSRF state tokens issued by /google/login, consumed once by /google/callback.
#: An in-memory dict is enough here: this only ever needs to survive the few
#: seconds between the two, and only the `api` container (the one instance
#: with a published port a browser can reach) ever serves this flow.
_oauth_states: dict[str, float] = {}


def _issue_state() -> str:
    now = time.monotonic()
    for token, issued_at in list(_oauth_states.items()):
        if now - issued_at > _STATE_TTL_SECONDS:
            del _oauth_states[token]

    token = secrets.token_urlsafe(24)
    _oauth_states[token] = now
    return token


def _consume_state(token: str) -> bool:
    issued_at = _oauth_states.pop(token, None)
    if issued_at is None:
        return False
    return (time.monotonic() - issued_at) <= _STATE_TTL_SECONDS


@router.get("/google/login")
def google_login() -> RedirectResponse:
    """Redirect straight to Google's consent screen.

    A real redirect, not a JSON login_url like the Kite flow — this is meant
    to be the target of a plain "Sign in with Google" link/button, not
    fetched and re-navigated to by the SPA.
    """
    if not settings.google_oauth_configured:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Google sign-in is not configured: set GOOGLE_CLIENT_ID, "
            "GOOGLE_CLIENT_SECRET, and at least one email in "
            "GOOGLE_ALLOWED_EMAILS in .env",
        )

    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URL,
        "response_type": "code",
        "scope": "openid email profile",
        "state": _issue_state(),
        "access_type": "online",
        "prompt": "select_account",
    }
    return RedirectResponse(f"{GOOGLE_AUTH_URL}?{urlencode(params)}")


@router.get("/google/callback", response_model=None)
def google_callback(code: str, state: str, db: DbSession) -> HTMLResponse | RedirectResponse:
    """Google redirects the browser here after consent.

    Errors render an HTML page (this is loaded by a browser via redirect, the
    same reason /kite/callback does); success redirects on to the SPA with a
    JWT in the query string for it to pick up and store.
    """
    if not _consume_state(state):
        return HTMLResponse(
            _page(
                "❌", "Google login failed", "Invalid or expired login attempt — please try again.", ok=False
            ),
            status_code=400,
        )

    try:
        token_response = httpx.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": settings.GOOGLE_REDIRECT_URL,
                "grant_type": "authorization_code",
            },
            timeout=10.0,
        )
        token_response.raise_for_status()
        google_access_token = token_response.json()["access_token"]

        userinfo_response = httpx.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {google_access_token}"},
            timeout=10.0,
        )
        userinfo_response.raise_for_status()
        info = userinfo_response.json()
    except httpx.HTTPError as exc:
        log.error("auth.google.token_exchange_failed", error=str(exc))
        return HTMLResponse(
            _page(
                "❌",
                "Google login failed",
                "Could not verify your Google account. Please try again.",
                ok=False,
            ),
            status_code=502,
        )

    email = (info.get("email") or "").lower()
    if not info.get("email_verified") or not email:
        return HTMLResponse(
            _page("❌", "Google login failed", "Your Google account has no verified email.", ok=False),
            status_code=400,
        )

    if email not in settings.google_allowed_emails:
        log.warning("auth.google.email_not_allowed", email=email)
        return HTMLResponse(
            _page(
                "🚫",
                "Access not permitted",
                f"<b>{email}</b> is not on this instance's allow-list "
                "(GOOGLE_ALLOWED_EMAILS in .env). Ask the owner to add it, or "
                "sign in with a different Google account.",
                ok=False,
            ),
            status_code=403,
        )

    google_id = info["sub"]
    user = db.execute(select(User).where(User.google_id == google_id)).scalar_one_or_none()

    if user is None:
        # Someone who already has a local password account, now also signing
        # in with the matching Google email — link rather than duplicate.
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()

    if user is None:
        username = _unique_username_from_email(db, email)
        user = User(
            username=username,
            email=email,
            hashed_password=None,
            auth_provider="google",
            google_id=google_id,
            is_active=True,
        )
        db.add(user)
        log.info("auth.google.account_created", email=email, username=username)
    elif user.google_id is None:
        user.google_id = google_id

    if not user.is_active:
        return HTMLResponse(
            _page("🚫", "Account disabled", "This account has been disabled.", ok=False),
            status_code=403,
        )

    user.last_login_at = datetime.now(UTC)
    db.commit()
    db.refresh(user)

    jwt_token = create_access_token(user.username, {"uid": user.id})
    return RedirectResponse(f"{settings.FRONTEND_URL}/?token={jwt_token}")


def _unique_username_from_email(db: Session, email: str) -> str:
    base = email.split("@")[0]
    candidate = base
    suffix = 1
    while db.execute(select(User).where(User.username == candidate)).scalar_one_or_none():
        suffix += 1
        candidate = f"{base}{suffix}"
    return candidate


def _page(icon: str, title: str, body: str, ok: bool) -> str:
    colour = "#16a34a" if ok else "#dc2626"
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>
  body {{ font-family: system-ui, -apple-system, sans-serif; display: grid;
         place-items: center; min-height: 100vh; margin: 0; background: #0f172a;
         color: #e2e8f0; }}
  .card {{ background: #1e293b; padding: 2.5rem 3rem; border-radius: 12px;
          text-align: center; max-width: 32rem; border-top: 4px solid {colour}; }}
  h1 {{ margin: 0.5rem 0; font-size: 1.35rem; }}
  p {{ color: #94a3b8; line-height: 1.6; }}
  .icon {{ font-size: 3rem; }}
</style></head>
<body><div class="card">
  <div class="icon">{icon}</div>
  <h1>{title}</h1>
  <p>{body}</p>
</div></body></html>"""
