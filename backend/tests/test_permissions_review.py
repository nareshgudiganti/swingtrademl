"""Permissions review (tracker task tv5, 2026-10-14): every route that changes something refuses a
signed-in non-owner, and every non-public route refuses a caller with no credentials.

The owner-only rule lives in one place (api/deps.require_auth: any write needs the owner, whatever the
plans switch says, audit F-17), and test_brain_owner_only_writes.py checks a handful of routes by hand.
This file walks EVERY route the app serves, so a new endpoint that forgets the guard fails here before
it can reach prod. A route that is meant to be open has to be named in an allow-list below, with why.
"""

from __future__ import annotations

import re

import pytest

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.session import User
from swing_trade_ml.main import app

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
PREFIX = settings.API_V1_PREFIX

_SIGN_IN = "signing in cannot require being signed in"
_SIGNUP = "creates an ordinary account only when sign-up is open or with an approved invite; never an owner"
_INVITE = "asking for an invite happens before having an account; it only stores a request for the owner"

# Writes a signed-in non-owner may make, and why. Everything else must answer 401/403.
OPEN_WRITES: dict[tuple[str, str], str] = {
    ("POST", "/auth/login"): _SIGN_IN,
    ("POST", "/auth/signup"): _SIGNUP,
    ("POST", "/auth/password"): "a signed-in person changes their own password, nobody else's",
    ("POST", "/auth/logout-all"): "a signed-in person ends their own sessions, nobody else's",
    ("POST", "/auth/google/exchange"): "finishes Google sign-in; the one-time code is the credential",
    ("POST", "/auth/invite-request"): _INVITE,
}

# Routes anyone may call without credentials, and why. Everything else must answer 401/403.
# Deliberately NOT here: GET /auth/kite/session, which until 2026-10-14 told anyone on the internet the
# owner's Zerodha client ID, name and token expiry.
PUBLIC: dict[tuple[str, str], str] = {
    ("GET", "/health"): "uptime checks; says only that the API answers",
    ("GET", "/ready"): "uptime checks; says only that the database answers",
    ("GET", "/auth/options"): "the sign-in page asks which sign-in options are open",
    ("POST", "/auth/login"): _SIGN_IN,
    ("POST", "/auth/signup"): _SIGNUP,
    ("POST", "/auth/google/exchange"): "finishes Google sign-in; the one-time code is the credential",
    ("GET", "/auth/google/login"): "starts Google sign-in",
    ("POST", "/auth/invite-request"): _INVITE,
    ("GET", "/auth/google/callback"): "Google sends the browser back here and cannot add our credentials",
    ("GET", "/auth/kite/login"): "starts Zerodha login; the token is only kept for the owner's own client ID",
    (
        "GET",
        "/auth/kite/callback",
    ): "Zerodha sends the browser back here; refuses any client ID but the owner's",
}


def _routes() -> list[tuple[str, str]]:
    """Every (method, path) the app documents. The OpenAPI list is used rather than app.routes, which
    this FastAPI version wraps in lazily-built included routers. A route hidden from the schema
    (include_in_schema=False) would not be seen; none of ours is."""
    found = []
    for full, ops in app.openapi()["paths"].items():
        if full.startswith(PREFIX):
            for method in ops:
                if method.upper() in WRITE_METHODS | {"GET"}:
                    found.append((method.upper(), full[len(PREFIX) :]))
    return sorted(set(found))


def _url(path: str) -> str:
    # Any value works: the guard must refuse before the path is ever looked up.
    return PREFIX + re.sub(r"\{[^}]+\}", "1", path)


def _guest(db_session) -> dict[str, str]:
    user = User(username="perm-guest", hashed_password="x", is_active=True, is_superuser=False, plan="free")
    db_session.add(user)
    db_session.flush()
    return {"Authorization": f"Bearer {create_access_token(user.username, {'uid': user.id})}"}


def test_the_route_walk_sees_the_whole_app():
    routes = _routes()
    writes = [r for r in routes if r[0] in WRITE_METHODS]
    assert len(routes) > 150 and len(writes) > 60  # a broken walk must not pass by finding nothing


@pytest.mark.parametrize(("method", "path"), [r for r in _routes() if r[0] in WRITE_METHODS])
def test_every_write_refuses_a_signed_in_non_owner(client, db_session, method, path):
    if (method, path) in OPEN_WRITES:
        pytest.skip(OPEN_WRITES[(method, path)])
    r = client.request(method, _url(path), json={}, headers=_guest(db_session))
    assert r.status_code in (401, 403), f"{method} {path} let a non-owner through: {r.status_code}"


@pytest.mark.parametrize(("method", "path"), _routes())
def test_every_route_refuses_a_caller_with_no_credentials(client, method, path):
    if (method, path) in PUBLIC:
        pytest.skip(PUBLIC[(method, path)])
    r = client.request(method, _url(path), json={} if method in WRITE_METHODS else None)
    assert r.status_code in (401, 403), f"{method} {path} answered {r.status_code} without credentials"
