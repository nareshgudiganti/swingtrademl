"""Dashboard login and the Zerodha Kite OAuth flow."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from swing_trade_ml.api.deps import DbSession
from swing_trade_ml.brokers.kite import kite_broker
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.core.security import create_access_token, verify_password
from swing_trade_ml.db.models.session import BrokerSession, User
from swing_trade_ml.schemas import (
    KiteLoginResponse,
    KiteSessionResponse,
    LoginRequest,
    TokenResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])
log = get_logger(__name__)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: DbSession) -> TokenResponse:
    user = db.execute(select(User).where(User.username == payload.username)).scalar_one_or_none()
    # One generic message for both branches — distinguishing "no such user" from
    # "wrong password" would let an attacker enumerate valid usernames.
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect username or password")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is disabled")

    user.last_login_at = datetime.now(UTC)
    db.commit()

    return TokenResponse(
        access_token=create_access_token(user.username, {"uid": user.id}),
        expires_in_minutes=settings.JWT_EXPIRE_MINUTES,
    )


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
        return HTMLResponse(
            _page("❌", "Kite login failed", str(exc), ok=False), status_code=400
        )

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
