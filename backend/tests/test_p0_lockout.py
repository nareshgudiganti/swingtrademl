from __future__ import annotations

from datetime import UTC, datetime, timedelta

from swing_trade_ml.api.v1.endpoints.auth import LOGIN_FAILED
from swing_trade_ml.core.security import hash_password, verify_password
from swing_trade_ml.db.models.audit import AuditLog
from swing_trade_ml.db.models.session import User

PW = "correct-horse-1"


def _user(db, name) -> User:
    user = User(username=name, hashed_password=hash_password(PW), is_active=True, role="member", plan="free")
    db.add(user)
    db.flush()
    return user


def _login(client, name, pw):
    return client.post("/api/v1/auth/login", json={"username": name, "password": pw})


def test_five_wrong_passwords_lock_the_account(client, db_session):
    user = _user(db_session, "lk1")
    for _ in range(5):
        assert _login(client, "lk1", "nope").status_code == 401
    db_session.refresh(user)
    assert user.locked_until is not None and user.locked_until > datetime.now(UTC)
    assert _login(client, "lk1", PW).status_code == 401  # right password refused while locked


def test_lock_lifts_after_15_minutes(client, db_session):
    user = _user(db_session, "lk2")
    user.locked_until = datetime.now(UTC) - timedelta(seconds=1)
    db_session.flush()
    assert _login(client, "lk2", PW).status_code == 200
    db_session.refresh(user)
    assert user.failed_login_count == 0 and user.locked_until is None


def test_success_resets_the_count(client, db_session):
    user = _user(db_session, "lk3")
    for _ in range(4):
        _login(client, "lk3", "nope")
    assert _login(client, "lk3", PW).status_code == 200
    db_session.refresh(user)
    assert user.failed_login_count == 0


def test_unknown_locked_and_wrong_look_identical(client, db_session):
    _user(db_session, "lk4")
    locked = _user(db_session, "lk5")
    locked.locked_until = datetime.now(UTC) + timedelta(minutes=10)
    db_session.flush()
    answers = [_login(client, "nobody-here", "x"), _login(client, "lk4", "nope"), _login(client, "lk5", PW)]
    assert {(r.status_code, r.json()["detail"]) for r in answers} == {(401, LOGIN_FAILED)}


def test_every_attempt_is_audited(client, db_session):
    _user(db_session, "lk6")
    _login(client, "lk6", "nope")
    _login(client, "lk6", PW)
    actions = [
        a.action
        for a in db_session.query(AuditLog).filter(AuditLog.actor_label == "lk6").order_by(AuditLog.id)
    ]
    assert actions[-2:] == ["auth.login_failed", "auth.login"]


def test_google_only_account_cannot_password_login(client, db_session):
    db_session.add(
        User(username="g-only", hashed_password=None, auth_provider="google", is_active=True, plan="free")
    )
    db_session.flush()
    r = _login(client, "g-only", "anything")
    assert (r.status_code, r.json()["detail"]) == (401, LOGIN_FAILED)


def test_disabled_account_with_the_right_password_gets_the_same_answer(client, db_session):
    user = _user(db_session, "lk-off")
    user.is_active = False
    db_session.flush()
    r = _login(client, "lk-off", PW)
    assert (r.status_code, r.json()["detail"]) == (401, LOGIN_FAILED)
    assert (
        db_session.query(AuditLog).filter_by(action="auth.login_disabled", actor_label="lk-off").count() == 1
    )


def _change(client, user, current):
    from swing_trade_ml.core.security import create_access_token

    token = create_access_token(user.username, {"uid": user.id, "tv": user.token_version or 0})
    return client.post(
        "/api/v1/auth/password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": current, "new_password": "battery-staple-2"},
    )


def test_wrong_current_passwords_count_toward_the_lock(client, db_session):
    user = _user(db_session, "lk-pw")
    for _ in range(5):
        r = _change(client, user, "nope")
        assert (r.status_code, r.json()["detail"]) == (400, "Your current password is not right.")
    db_session.refresh(user)
    assert user.locked_until is not None and user.locked_until > datetime.now(UTC)
    assert _login(client, "lk-pw", PW).status_code == 401  # right password refused while locked
    assert _change(client, user, PW).status_code == 400  # and no password change while locked
    db_session.refresh(user)
    assert verify_password(PW, user.hashed_password)


def test_wrong_current_password_is_audited(client, db_session):
    user = _user(db_session, "lk-pw-audit")
    _change(client, user, "nope")
    assert (
        db_session.query(AuditLog)
        .filter_by(action="auth.password_change_failed", actor_user_id=user.id)
        .count()
        == 1
    )
    db_session.refresh(user)
    assert user.failed_login_count == 1


def test_login_and_password_change_failures_share_one_count(client, db_session):
    user = _user(db_session, "lk-mix")
    for _ in range(2):
        _login(client, "lk-mix", "nope")
    for _ in range(3):
        _change(client, user, "nope")
    db_session.refresh(user)
    assert user.locked_until is not None and user.locked_until > datetime.now(UTC)
