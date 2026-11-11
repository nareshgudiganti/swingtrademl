"""Every admin-console route refuses a non-admin on the server, whatever the screen shows.

The People screen in the new TradeMind menu is hidden from non-owners and its address redirects them, but that
is only convenience. This walks the documented route list (a route added later is covered too) and
checks that a member, a tester, the shared API key and a caller with no sign-in are all refused on every
admin-console and two-step route, including the ones that change things (plan switch, grants, MFA setup).
Scratch test database.
"""

from __future__ import annotations

import re

import pytest

from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.session import User
from swing_trade_ml.main import app

PREFIX = "/api/v1"
API_KEY = {"X-API-Key": "test-api-key"}
GUARDED = (f"{PREFIX}/admin/console", f"{PREFIX}/admin/mfa")


def _admin_routes() -> list[tuple[str, str]]:
    """Every documented admin-console / two-step route. The OpenAPI list is used because this FastAPI wraps
    routers lazily (see test_permissions_review._routes)."""
    found: list[tuple[str, str]] = []
    for full, ops in app.openapi()["paths"].items():
        if full.startswith(GUARDED):
            for method in ops:
                if method.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                    found.append((method.upper(), PREFIX + re.sub(r"\{[^}]+\}", "1", full[len(PREFIX) :])))
    return sorted(set(found))


def _person(db, name: str, role: str) -> dict[str, str]:
    user = User(username=name, hashed_password="x", is_active=True, role=role, plan="free")
    db.add(user)
    db.flush()
    return {"Authorization": f"Bearer {create_access_token(user.username, {'uid': user.id})}"}


def test_the_walk_finds_the_admin_routes():
    # If the prefixes ever change, this fails instead of the loop below quietly checking nothing.
    routes = _admin_routes()
    assert len(routes) >= 10
    assert ("GET", f"{PREFIX}/admin/console/users") in routes
    assert any(m in {"POST", "PUT", "PATCH", "DELETE"} for m, _ in routes), "no write route found"


@pytest.mark.parametrize("role", ["member", "tester"])
def test_every_admin_route_refuses_a_non_admin(client, db_session, role):
    hdr = _person(db_session, f"nonadmin_{role}", role)
    for method, path in _admin_routes():
        response = client.request(method, path, headers=hdr, json={})
        assert response.status_code == 403, f"{role} got {response.status_code} on {method} {path}"


def test_every_admin_route_refuses_the_shared_api_key(client):
    for method, path in _admin_routes():
        response = client.request(method, path, headers=API_KEY, json={})
        assert response.status_code == 403, f"API key got {response.status_code} on {method} {path}"


def test_every_admin_route_refuses_no_sign_in(client):
    for method, path in _admin_routes():
        response = client.request(method, path, json={})
        assert response.status_code == 401, f"no sign-in got {response.status_code} on {method} {path}"
