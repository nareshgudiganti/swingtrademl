"""Per-IP request limits for sign-in and other no-login endpoints (tracker qa7).

A fixed-window counter in Redis: one key per (group, client IP, minute), bumped
with INCR and given an expiry so it cleans itself up. Over the limit the caller
gets HTTP 429 with a Retry-After header.

This sits next to the per-account lockout in `endpoints/auth.py` (5 wrong
passwords -> that account pauses 15 minutes). The lockout stops guessing one
account's password; this stops one address hammering many accounts, or the
public endpoints, at all.

Fail open: if Redis is down or slow, the request is ALLOWED and a warning is
logged. A broken counter must never stop the owner signing in. After a failure
Redis is left alone for `_BACKOFF_SECONDS`, so an outage costs one short timeout,
not one per request.

Which IP: in production the browser talks to the host's nginx, which proxies
"/api/" to the api container on 127.0.0.1:8000 (docker-compose.prod.yml). Docker
hands that connection over from its bridge gateway (a 172.x address), so the
TCP peer is the same for every visitor and the real address must come from the
proxy's headers. Headers are only believed when the TCP peer itself is one of
our proxies (RATE_LIMIT_TRUSTED_PROXIES: loopback and private ranges, which the
internet cannot reach the api from). nginx's standard `proxy_params` sets
`X-Forwarded-For $proxy_add_x_forwarded_for`, which APPENDS the address nginx saw
to whatever the client sent. The left of that list is client-written and can be
forged; the right-most entry that is not one of our own proxies is the one nginx
wrote, so that is the one used. X-Real-IP is a fallback only when there is no
X-Forwarded-For. A peer that is not a trusted proxy is used as-is, headers ignored.
"""

from __future__ import annotations

import ipaddress
import math
import threading
import time
from functools import lru_cache
from typing import Any

from fastapi import HTTPException, Request, status

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.logging import get_logger

log = get_logger(__name__)

WINDOW_SECONDS = 60
_BACKOFF_SECONDS = 30.0
_REDIS_TIMEOUT_SECONDS = 0.5

TOO_MANY = "Too many attempts from your connection. Please wait {wait} and try again."

# Wall clock for the windows; a name of its own so tests can pin it.
_now = time.time
_lock = threading.Lock()
_client: Any = None
_down_until = 0.0


@lru_cache(maxsize=8)
def _trusted_networks(spec: str) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    nets = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            log.warning("rate_limit.bad_trusted_proxy", value=part)
    return tuple(nets)


def _is_trusted_proxy(host: str) -> bool:
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(addr in net for net in _trusted_networks(settings.RATE_LIMIT_TRUSTED_PROXIES))


def client_ip(request: Request) -> str:
    """The visitor's address, trusting proxy headers only when our own proxy sent them."""
    peer = request.client.host if request.client else "unknown"
    if not _is_trusted_proxy(peer):
        return peer
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        hops = [h.strip() for h in forwarded.split(",") if h.strip()]
        for hop in reversed(hops):
            if not _is_trusted_proxy(hop):
                return hop[:64]
        return peer
    real_ip = request.headers.get("x-real-ip", "").strip()
    return real_ip[:64] if real_ip else peer


def _redis() -> Any:
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                import redis

                _client = redis.Redis.from_url(
                    settings.REDIS_URL,
                    socket_timeout=_REDIS_TIMEOUT_SECONDS,
                    socket_connect_timeout=_REDIS_TIMEOUT_SECONDS,
                )
    return _client


def set_redis_client(client: Any) -> None:
    """Swap the Redis client (tests use an in-memory stand-in). Also clears any back-off."""
    global _client, _down_until
    _client = client
    _down_until = 0.0


def _hit(key: str) -> int | None:
    """Count one request against `key`. None when Redis can't be used (fail open)."""
    global _down_until
    if time.monotonic() < _down_until:
        return None
    try:
        pipe = _redis().pipeline(transaction=True)
        pipe.incr(key)
        pipe.expire(key, WINDOW_SECONDS + 1)
        count, _ = pipe.execute()
        return int(count)
    except Exception as exc:  # noqa: BLE001 — any Redis/network error: allow the request
        _down_until = time.monotonic() + _BACKOFF_SECONDS
        log.warning("rate_limit.redis_unavailable_allowing", error=type(exc).__name__)
        return None


def _wait_text(seconds: int) -> str:
    return "a minute" if seconds >= 45 else f"{seconds} seconds"


class RateLimit:
    """FastAPI dependency: at most N requests per minute per client IP for this group.

    `limit_setting` names the settings field, read on every call so a test or an
    env change takes effect without rebuilding routes.
    """

    def __init__(self, group: str, limit_setting: str) -> None:
        self.group = group
        self.limit_setting = limit_setting

    def __call__(self, request: Request) -> None:
        if not settings.RATE_LIMIT_ENABLED:
            return
        limit = int(getattr(settings, self.limit_setting))
        if limit <= 0:
            return
        now = _now()
        window = int(now // WINDOW_SECONDS)
        ip = client_ip(request)
        count = _hit(f"rl:{self.group}:{ip}:{window}")
        if count is None or count <= limit:
            return
        retry_after = max(1, math.ceil((window + 1) * WINDOW_SECONDS - now))
        log.info("rate_limit.refused", group=self.group, ip=ip, count=count, limit=limit)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            TOO_MANY.format(wait=_wait_text(retry_after)),
            headers={"Retry-After": str(retry_after)},
        )


# Sign-in and account endpoints: one shared counter per IP across all of them.
auth_limit = RateLimit("auth", "RATE_LIMIT_AUTH_PER_MINUTE")
# Endpoints anyone can call without signing in (health, readiness, login-page options).
public_limit = RateLimit("public", "RATE_LIMIT_PUBLIC_PER_MINUTE")
