from __future__ import annotations

from swing_trade_ml.core.security import create_access_token, hash_password
from swing_trade_ml.db.models.audit import AuditLog
from swing_trade_ml.db.models.session import User


def _user(db, name="s1", password="correct-horse-1", role="member") -> User:
    user = User(
        username=name, hashed_password=hash_password(password), is_active=True, role=role, plan="free"
    )
    db.add(user)
    db.flush()
    return user


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_login_token_carries_uid_and_version(client, db_session):
    user = _user(db_session, "s-claims")
    tok = client.post(
        "/api/v1/auth/login", json={"username": "s-claims", "password": "correct-horse-1"}
    ).json()["access_token"]
    from swing_trade_ml.core.security import decode_access_token

    claims = decode_access_token(tok)
    assert (claims["sub"], claims["uid"], claims["tv"]) == ("s-claims", user.id, 0)


def test_legacy_token_works_until_version_bumped(client, db_session):
    user = _user(db_session, "s-legacy")
    legacy = _bearer(create_access_token(user.username, {"uid": user.id}))
    assert client.get("/api/v1/auth/me", headers=legacy).status_code == 200
    user.token_version += 1
    db_session.flush()
    assert client.get("/api/v1/auth/me", headers=legacy).status_code == 401


def test_password_change_ends_old_sessions_and_returns_a_new_one(client, db_session):
    user = _user(db_session, "s-pw")
    old = _bearer(create_access_token(user.username, {"uid": user.id, "tv": 0}))
    r = client.post(
        "/api/v1/auth/password",
        headers=old,
        json={"current_password": "correct-horse-1", "new_password": "battery-staple-2"},
    )
    assert r.status_code == 200
    assert client.get("/api/v1/auth/me", headers=old).status_code == 401
    assert client.get("/api/v1/auth/me", headers=_bearer(r.json()["access_token"])).status_code == 200
    assert (
        client.post(
            "/api/v1/auth/login", json={"username": "s-pw", "password": "battery-staple-2"}
        ).status_code
        == 200
    )
    assert (
        db_session.query(AuditLog).filter_by(action="auth.password_change", actor_user_id=user.id).count()
        == 1
    )


def test_password_change_needs_the_current_password(client, db_session):
    user = _user(db_session, "s-pw2")
    tok = _bearer(create_access_token(user.username, {"uid": user.id, "tv": 0}))
    r = client.post(
        "/api/v1/auth/password",
        headers=tok,
        json={"current_password": "wrong", "new_password": "battery-staple-2"},
    )
    assert r.status_code == 400


def test_new_password_must_be_8_or_more(client, db_session):
    user = _user(db_session, "s-pw3")
    tok = _bearer(create_access_token(user.username, {"uid": user.id, "tv": 0}))
    r = client.post(
        "/api/v1/auth/password",
        headers=tok,
        json={"current_password": "correct-horse-1", "new_password": "short"},
    )
    assert r.status_code == 422


def test_logout_all_ends_every_session(client, db_session):
    user = _user(db_session, "s-out")
    tok = _bearer(create_access_token(user.username, {"uid": user.id, "tv": 0}))
    assert client.post("/api/v1/auth/logout-all", headers=tok).status_code == 200
    assert client.get("/api/v1/auth/me", headers=tok).status_code == 401


def test_uid_and_username_must_agree(client, db_session):
    a, b = _user(db_session, "s-a"), _user(db_session, "s-b")
    forged = _bearer(create_access_token(a.username, {"uid": b.id, "tv": 0}))
    assert client.get("/api/v1/auth/me", headers=forged).status_code == 401


def test_disabled_user_is_rejected(client, db_session):
    user = _user(db_session, "s-off")
    tok = _bearer(create_access_token(user.username, {"uid": user.id, "tv": 0}))
    user.is_active = False
    db_session.flush()
    assert client.get("/api/v1/auth/me", headers=tok).status_code == 401
