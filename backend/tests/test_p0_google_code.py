from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.audit import LoginCode
from swing_trade_ml.db.models.session import User
from swing_trade_ml.services import login_codes


def _user(db, name="g1", active=True) -> User:
    user = User(username=name, hashed_password=None, auth_provider="google", is_active=active, plan="free")
    db.add(user)
    db.flush()
    return user


def test_code_is_stored_hashed_and_redeems_once(db_session):
    user = _user(db_session)
    code = login_codes.issue(db_session, user)
    row = db_session.query(LoginCode).filter_by(user_id=user.id).one()
    assert row.code_hash == hashlib.sha256(code.encode()).hexdigest()
    assert row.code_hash != code  # raw code never stored
    assert login_codes.redeem(db_session, code).id == user.id
    assert login_codes.redeem(db_session, code) is None


def test_expired_code_is_refused(db_session):
    user = _user(db_session, "g2")
    code = login_codes.issue(db_session, user)
    row = db_session.query(LoginCode).filter_by(user_id=user.id).one()
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.flush()
    assert login_codes.redeem(db_session, code) is None


def test_disabled_user_code_is_refused(db_session):
    user = _user(db_session, "g3")
    code = login_codes.issue(db_session, user)
    user.is_active = False
    db_session.flush()
    assert login_codes.redeem(db_session, code) is None


def test_exchange_route(client, db_session):
    user = _user(db_session, "g4")
    code = login_codes.issue(db_session, user)
    r = client.post("/api/v1/auth/google/exchange", json={"code": code})
    assert r.status_code == 200 and r.json()["access_token"]
    again = client.post("/api/v1/auth/google/exchange", json={"code": code})
    assert again.status_code == 401


def test_callback_puts_a_code_not_a_token_in_the_url(client, db_session, monkeypatch):
    from swing_trade_ml.api.v1.endpoints import auth as auth_ep

    monkeypatch.setattr(settings, "GOOGLE_ALLOWED_EMAILS", "g5@example.com")
    state = auth_ep._issue_state()

    class _Resp:
        def __init__(self, data):
            self._d = data

        def raise_for_status(self):
            pass

        def json(self):
            return self._d

    monkeypatch.setattr(auth_ep.httpx, "post", lambda *a, **k: _Resp({"access_token": "google-at"}))
    monkeypatch.setattr(
        auth_ep.httpx,
        "get",
        lambda *a, **k: _Resp({"sub": "google-sub-g5", "email": "g5@example.com", "email_verified": True}),
    )
    r = client.get(f"/api/v1/auth/google/callback?code=abc&state={state}", follow_redirects=False)
    assert r.status_code in (302, 307)
    query = parse_qs(urlparse(r.headers["location"]).query)
    assert "login_code" in query and "token" not in query
