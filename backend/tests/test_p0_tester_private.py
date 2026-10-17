"""A tester sees the shared app while plans are off, never the owner's private areas:
money, the Zerodha session, safety switches, alerts, the brain's go-live controls,
the Plans Manager, or the house (bot) book."""

from __future__ import annotations

import pytest

from swing_trade_ml.api.deps import PRIVATE_AREA, TESTER_PRIVATE_PREFIXES
from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.session import User
from test_permissions_review import _routes, _url  # sibling import, like test_p0_role_matrix

# Public by design (no sign-in): the browser lands on the callback from Zerodha, and the
# login route only hands out Zerodha's own login page address.
PUBLIC_KITE = {"/auth/kite/login", "/auth/kite/callback"}


def _as(db, username: str, role: str) -> dict[str, str]:
    user = User(username=username, hashed_password="x", is_active=True, role=role, plan="free")
    db.add(user)
    db.flush()
    return {"Authorization": f"Bearer {create_access_token(user.username, {'uid': user.id})}"}


def _private_reads() -> list[str]:
    return [
        path
        for method, path in _routes()
        if method == "GET"
        and path not in PUBLIC_KITE
        and any(path == p or path.startswith(p + "/") for p in TESTER_PRIVATE_PREFIXES)
    ]


def test_every_private_area_has_a_read_route_in_the_walk():
    found = _private_reads()
    for prefix in TESTER_PRIVATE_PREFIXES:
        assert any(p == prefix or p.startswith(prefix + "/") for p in found), prefix


@pytest.mark.parametrize("path", _private_reads())
def test_tester_cannot_read_private_areas(client, db_session, path):
    r = client.get(_url(path), headers=_as(db_session, "tp-tester", "tester"))
    assert r.status_code == 403, f"GET {path} let a tester through: {r.status_code}"
    if not path.startswith("/admin"):  # /admin answers with the owner-only message itself
        assert r.json()["detail"] == PRIVATE_AREA


def test_tester_cannot_read_the_kite_session(client, db_session):
    r = client.get("/api/v1/auth/kite/session", headers=_as(db_session, "tp-kite", "tester"))
    assert r.status_code == 403
    assert r.json()["detail"] == PRIVATE_AREA


def test_tester_cannot_start_a_kite_auto_login(client, db_session):
    r = client.post("/api/v1/auth/kite/auto-login", headers=_as(db_session, "tp-auto", "tester"))
    assert r.status_code == 403


@pytest.mark.parametrize("book", ["bot", "all", "real"])
def test_tester_cannot_read_the_house_book(client, db_session, book):
    tester = _as(db_session, f"tp-book-{book}", "tester")
    assert client.get(f"/api/v1/portfolio/summary?book={book}", headers=tester).status_code == 403
    assert client.get(f"/api/v1/portfolio/positions/detailed?book={book}", headers=tester).status_code == 403
    assert client.get(f"/api/v1/portfolio/trades?book={book}", headers=tester).status_code == 403


def test_tester_still_reads_the_shared_app_and_the_tester_book(client, db_session):
    tester = _as(db_session, "tp-shared", "tester")
    assert client.get("/api/v1/portfolio/summary?book=tester", headers=tester).status_code == 200
    assert client.get("/api/v1/portfolio/positions/detailed?book=tester", headers=tester).status_code == 200
    assert client.get("/api/v1/portfolio/positions", headers=tester).status_code == 200
    assert client.get("/api/v1/signals/picks", headers=tester).status_code == 200
    assert client.get("/api/v1/strategies", headers=tester).status_code == 200


def test_owner_still_reads_finance_and_the_house_book(client, db_session):
    owner = _as(db_session, "tp-owner", "owner")
    assert client.get("/api/v1/finance/categories", headers=owner).status_code == 200
    assert client.get("/api/v1/portfolio/summary?book=bot", headers=owner).status_code == 200
