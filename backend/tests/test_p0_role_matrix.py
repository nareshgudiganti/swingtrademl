"""Every route x every role. A new route that forgets its guard fails here."""

from __future__ import annotations

import pytest
from test_permissions_review import (
    OPEN_WRITES,
    WRITE_METHODS,
    _routes,
    _url,
)  # sibling import, like brain_fakes

from swing_trade_ml.api.deps import TESTER_WRITES
from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.session import User

# Routes that touch the real Zerodha account (My Holdings). Only the owner may reach them.
REAL_ACCOUNT_PREFIXES = ("/portfolio/real/", "/real-report")
REAL_ACCOUNT_EXPLICIT = {
    ("GET", "/portfolio/holdings"),
    ("POST", "/portfolio/positions/import-holdings"),
    ("GET", "/portfolio/real/orders-status"),
    ("GET", "/portfolio/real/account"),
    ("GET", "/portfolio/real/quote"),
    ("POST", "/portfolio/real/buy"),
    ("POST", "/portfolio/real/positions/{position_id}/sell"),
}


def _is_real_account(method: str, path: str) -> bool:
    return path.startswith(REAL_ACCOUNT_PREFIXES) or (method, path) in REAL_ACCOUNT_EXPLICIT


REAL_ROUTES = [r for r in _routes() if _is_real_account(*r)]


def _as(db, username, role, active=True) -> dict[str, str]:
    user = User(username=username, hashed_password="x", is_active=active, role=role, plan="free")
    db.add(user)
    db.flush()
    return {"Authorization": f"Bearer {create_access_token(user.username, {'uid': user.id, 'tv': 0})}"}


WRITES = [r for r in _routes() if r[0] in WRITE_METHODS]


def test_the_real_account_walk_finds_every_known_route():
    assert len(REAL_ROUTES) >= 8
    assert REAL_ACCOUNT_EXPLICIT <= set(REAL_ROUTES), REAL_ACCOUNT_EXPLICIT - set(REAL_ROUTES)
    assert any(p.startswith("/real-report") for _, p in REAL_ROUTES)


@pytest.mark.parametrize(("method", "path"), WRITES)
def test_tester_writes_only_the_testing_book(client, db_session, method, path):
    if (method, path) in OPEN_WRITES or (method, path) in TESTER_WRITES:
        pytest.skip("self-service or tester route")
    r = client.request(method, _url(path), json={}, headers=_as(db_session, "mx-tester", "tester"))
    assert r.status_code in (401, 403), f"{method} {path} let a tester through: {r.status_code}"


@pytest.mark.parametrize(("method", "path"), REAL_ROUTES)
def test_real_account_is_never_open_to_testers_or_members(client, db_session, method, path):
    for role in ("tester", "member"):
        r = client.request(
            method,
            _url(path),
            json={} if method in WRITE_METHODS else None,
            headers=_as(db_session, f"mx-real-{role}", role),
        )
        assert r.status_code in (401, 403), f"{role} reached {method} {path}: {r.status_code}"


@pytest.mark.parametrize("role", ["tester", "member"])
def test_real_book_summary_is_refused(client, db_session, role):
    r = client.get(_url("/portfolio/summary") + "?book=real", headers=_as(db_session, f"mx-sum-{role}", role))
    assert r.status_code in (401, 403), f"{role} reached summary?book=real: {r.status_code}"


def test_disabled_account_is_refused(client, db_session):
    r = client.get("/api/v1/auth/me", headers=_as(db_session, "mx-off", "owner", active=False))
    assert r.status_code == 401


def test_api_key_still_owner(client):
    assert client.get("/api/v1/strategies", headers={"X-API-Key": "test-api-key"}).status_code == 200
