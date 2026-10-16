"""S1: a signed-in non-owner no longer sees the house book just because plans are off."""

from __future__ import annotations

from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.session import User

API_KEY = {"X-API-Key": "test-api-key"}


def _as(db, username: str, role: str) -> dict[str, str]:
    user = User(username=username, hashed_password="x", is_active=True, role=role, plan="free")
    db.add(user)
    db.flush()
    return {"Authorization": f"Bearer {create_access_token(user.username, {'uid': user.id})}"}


def test_member_is_refused_owner_screens_while_plans_are_off(client, db_session):
    member = _as(db_session, "m-read", "member")
    for path in ("/api/v1/strategies", "/api/v1/status", "/api/v1/risk/limits", "/api/v1/portfolio/summary"):
        assert client.get(path, headers=member).status_code == 403, path


def test_member_me_plan_is_restricted(client, db_session):
    me = client.get("/api/v1/me/plan", headers=_as(db_session, "m-me", "member")).json()
    assert me["unrestricted"] is False and me["can_manage_plans"] is False


def test_tester_still_reads_like_today_while_plans_are_off(client, db_session):
    tester = _as(db_session, "t-read", "tester")
    assert client.get("/api/v1/strategies", headers=tester).status_code == 200
    assert client.get("/api/v1/portfolio/summary?book=tester", headers=tester).status_code == 200


def test_tester_is_not_owner_and_cannot_see_real_account(client, db_session):
    tester = _as(db_session, "t-real", "tester")
    me = client.get("/api/v1/me/plan", headers=tester).json()
    assert me["can_manage_plans"] is False and me["can_see_real_account"] is False
    assert client.get("/api/v1/portfolio/summary?book=real", headers=tester).status_code == 403


def test_owner_and_api_key_unchanged(client, db_session):
    owner = _as(db_session, "o-read", "owner")
    for headers in (owner, API_KEY):
        assert client.get("/api/v1/strategies", headers=headers).status_code == 200


def test_me_reports_role(client, db_session):
    assert client.get("/api/v1/auth/me", headers=_as(db_session, "t-me", "tester")).json()["role"] == "tester"
