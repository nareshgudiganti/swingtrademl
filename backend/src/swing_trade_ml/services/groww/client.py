"""Read-only Groww API client: get an access token, get holdings. Nothing else.

Request formats copied from the published `growwapi` 1.5.0 package source
(GrowwAPI.get_access_token / get_holdings_for_user). The token, the TOTP code and
response bodies are never logged.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta

import httpx
import pyotp

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.market_session import IST

logger = logging.getLogger(__name__)

BASE_URL = "https://api.groww.in"
ALLOWED_PATHS = frozenset({"/v1/token/api/access", "/v1/holdings/user"})
_TOKEN_KEY = "groww:access_token"
_TIMEOUT = 10.0


class GrowwAuthError(Exception):
    """Groww refused our credentials or token."""


class GrowwUnavailable(Exception):  # noqa: N818 - name fixed by the task interface
    """Groww could not be reached or answered with something unusable."""


def is_configured() -> bool:
    return bool(settings.GROWW_TOTP_TOKEN and settings.GROWW_TOTP_SECRET)


def _get_redis():
    import redis

    return redis.Redis.from_url(settings.REDIS_URL, socket_timeout=2, socket_connect_timeout=2)


def _transport() -> httpx.BaseTransport | None:
    """Overridden in tests; None means the real network."""
    return None


def _headers(bearer: str) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {bearer}",
        "X-API-VERSION": "1.0",
        "x-request-id": str(uuid.uuid4()),
    }


def _token_request(totp_token: str, totp_code: str) -> httpx.Request:
    return httpx.Request(
        "POST",
        BASE_URL + "/v1/token/api/access",
        headers=_headers(totp_token),
        json={"key_type": "totp", "totp": totp_code.strip()},
    )


def _holdings_request(access_token: str) -> httpx.Request:
    return httpx.Request("GET", BASE_URL + "/v1/holdings/user", headers=_headers(access_token))


def _send(request: httpx.Request) -> httpx.Response:
    if request.url.path not in ALLOWED_PATHS:  # defence in depth
        raise GrowwUnavailable("blocked path")
    try:
        with httpx.Client(transport=_transport(), timeout=_TIMEOUT) as http:
            return http.send(request)
    except httpx.HTTPError as exc:
        raise GrowwUnavailable(f"network error: {type(exc).__name__}") from None


def _seconds_until_next_6am_ist() -> int:
    now = datetime.now(IST)
    target = now.replace(hour=6, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return max(1, int((target - now).total_seconds()))


def _mint_token() -> str:
    code = pyotp.TOTP(settings.GROWW_TOTP_SECRET).now()
    resp = _send(_token_request(settings.GROWW_TOTP_TOKEN, code))
    if resp.status_code in (401, 403):
        raise GrowwAuthError("Groww rejected the TOTP credentials")
    if resp.status_code != 200:
        raise GrowwUnavailable(f"token request failed ({resp.status_code})")
    try:
        token = resp.json()["token"]
    except (ValueError, KeyError, TypeError):
        raise GrowwUnavailable("token response not understood") from None
    if not isinstance(token, str) or not token:
        raise GrowwUnavailable("token response not understood")
    return token


def get_access_token(*, force: bool = False) -> str:
    if not is_configured():
        raise GrowwAuthError("Groww credentials are not set")
    redis_client = None
    try:
        redis_client = _get_redis()
        if not force:
            cached = redis_client.get(_TOKEN_KEY)
            if cached:
                return cached.decode() if isinstance(cached, bytes) else cached
    except Exception:  # noqa: BLE001 - a cache failure must never block a sync
        logger.warning("groww token cache unavailable; minting without cache")
        redis_client = None
    token = _mint_token()
    if redis_client is not None:
        try:
            redis_client.set(_TOKEN_KEY, token, ex=_seconds_until_next_6am_ist())
        except Exception:  # noqa: BLE001 - a cache failure must never block a sync
            logger.warning("groww token could not be cached")
    return token


def fetch_holdings() -> list[dict]:
    token = get_access_token()
    resp = _send(_holdings_request(token))
    if resp.status_code == 401:
        token = get_access_token(force=True)
        resp = _send(_holdings_request(token))
    if resp.status_code in (401, 403):
        raise GrowwAuthError("Groww rejected the access token")
    if resp.status_code != 200:
        raise GrowwUnavailable(f"holdings request failed ({resp.status_code})")
    try:
        body = resp.json()
        holdings = (body.get("payload") or body)["holdings"]
    except (ValueError, KeyError, TypeError, AttributeError):
        raise GrowwUnavailable("holdings response not understood") from None
    if not isinstance(holdings, list):
        raise GrowwUnavailable("holdings response not understood")
    return holdings
