"""Email senders, one-time tokens, register / verify / forgot / reset, admin send-reset and the
sign-in enforcement switch. DB tests (Postgres). No network, no real email."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from swing_trade_ml.api.v1.endpoints import account_auth
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.security import create_access_token, hash_password
from swing_trade_ml.db.models.audit import AuditLog
from swing_trade_ml.db.models.auth_tokens import AuthToken
from swing_trade_ml.db.models.session import User
from swing_trade_ml.services import auth_tokens
from swing_trade_ml.services.email import (
    LogEmailSender,
    ResendEmailSender,
    get_sender,
    set_sender_for_tests,
)
from swing_trade_ml.services.email.templates import reset_email, verification_email

API = "/api/v1"
GOOD_PW = "correct horse battery staple"
NEW_PW = "another long passphrase here"


@pytest.fixture(autouse=True)
def _outbox(monkeypatch):
    sender = LogEmailSender()
    set_sender_for_tests(sender)
    monkeypatch.setattr(settings, "ALLOW_SIGNUP", True)
    monkeypatch.setattr(settings, "REQUIRE_EMAIL_VERIFICATION", False)
    monkeypatch.setattr(settings, "APP_BASE_URL", "https://app.test")
    yield sender
    set_sender_for_tests(None)


def _token_from(sender: LogEmailSender, path: str) -> str:
    link = next(w for w in sender.outbox[-1].text.split() if f"/{path}?token=" in w)
    return link.split("token=")[1]


def _user(db, username="mem", *, role="member", provider="local", verified=None, pw=GOOD_PW, **kw):
    u = User(
        username=username,
        email=kw.pop("email", f"{username}@example.com"),
        hashed_password=hash_password(pw) if pw else None,
        auth_provider=provider,
        is_active=True,
        role=role,
        is_superuser=(role == "owner"),
        email_verified_at=verified,
        **kw,
    )
    db.add(u)
    db.flush()
    return u


def _bearer(u: User) -> dict[str, str]:
    return {
        "Authorization": "Bearer "
        + create_access_token(u.username, {"uid": u.id, "tv": u.token_version or 0})
    }


def _register(client, **over):
    body = {"full_name": "Asha Rao", "email": "Asha@Example.com", "password": GOOD_PW}
    body.update(over)
    return client.post(f"{API}/auth/register", json=body)


# ----------------------------------------------------------------- senders --


def test_log_sender_records_and_logs_only_recipient_and_subject(caplog):
    s = LogEmailSender()
    with caplog.at_level(logging.DEBUG):
        assert s.send("a@b.com", "Hello", "SECRETBODY token=abc123") is True
    assert s.outbox[0].to == "a@b.com"
    assert "SECRETBODY" not in caplog.text and "abc123" not in caplog.text


def test_resend_sends_expected_request_and_never_logs_key(caplog):
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"id": "x"})

    s = ResendEmailSender("re_KEY123", "TradeMind <no-reply@x.test>", httpx.MockTransport(handler))
    with caplog.at_level(logging.DEBUG):
        assert s.send("a@b.com", "Subj", "body text TOKEN999", "<p>h</p>") is True
    req = seen[0]
    assert str(req.url) == "https://api.resend.com/emails"
    assert req.headers["authorization"] == "Bearer re_KEY123"
    import json

    assert json.loads(req.content) == {
        "from": "TradeMind <no-reply@x.test>",
        "to": ["a@b.com"],
        "subject": "Subj",
        "text": "body text TOKEN999",
        "html": "<p>h</p>",
    }
    assert "re_KEY123" not in caplog.text and "TOKEN999" not in caplog.text


@pytest.mark.parametrize("failure", ["status", "exception"])
def test_resend_failure_returns_false_and_never_raises(failure, caplog):
    def handler(req):
        if failure == "exception":
            raise httpx.ConnectError("boom re_KEY123")
        return httpx.Response(500, json={"error": "x"})

    s = ResendEmailSender("re_KEY123", "f@x.test", httpx.MockTransport(handler))
    with caplog.at_level(logging.DEBUG):
        assert s.send("a@b.com", "S", "t") is False
    assert "re_KEY123" not in caplog.text


@pytest.mark.parametrize(("key", "frm"), [("", "f@x.test"), ("k", ""), ("", "")])
def test_resend_without_key_or_from_fails_closed_without_network(key, frm):
    def handler(req):
        raise AssertionError("no network call expected")

    assert ResendEmailSender(key, frm, httpx.MockTransport(handler)).send("a@b.com", "S", "t") is False


def test_factory_chooses_by_settings(monkeypatch):
    set_sender_for_tests(None)
    monkeypatch.setattr(settings, "EMAIL_PROVIDER", "log")
    assert isinstance(get_sender(), LogEmailSender)
    monkeypatch.setattr(settings, "EMAIL_PROVIDER", "resend")
    assert isinstance(get_sender(), ResendEmailSender)


def test_templates_have_links_and_no_extras(monkeypatch):
    _subj, text, html = verification_email("tok_1")
    assert "https://app.test/verify-email?token=tok_1" in text and "tok_1" in html
    _subj, text, html = reset_email("tok_2")
    assert "https://app.test/reset-password?token=tok_2" in text and "1 hour" in text


# ------------------------------------------------------------------ tokens --


def test_token_hash_only_single_use_and_expiry(db_session):
    u = _user(db_session)
    raw = auth_tokens.issue(db_session, u, "reset_password")
    row = db_session.execute(select(AuthToken)).scalar_one()
    assert row.token_hash == auth_tokens.hash_token(raw) and raw not in (row.token_hash, row.purpose)
    assert row.expires_at - row.created_at <= timedelta(hours=1, seconds=5)
    assert auth_tokens.redeem(db_session, raw, "verify_email") is None  # wrong purpose
    assert auth_tokens.redeem(db_session, raw, "reset_password").id == u.id
    assert auth_tokens.redeem(db_session, raw, "reset_password") is None  # used

    raw2 = auth_tokens.issue(db_session, u, "verify_email")
    r2 = db_session.execute(select(AuthToken).where(AuthToken.purpose == "verify_email")).scalar_one()
    assert r2.expires_at - r2.created_at > timedelta(hours=23)
    r2.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.flush()
    assert auth_tokens.redeem(db_session, raw2, "verify_email") is None


def test_new_token_invalidates_older_unused(db_session):
    u = _user(db_session)
    old = auth_tokens.issue(db_session, u, "reset_password")
    new = auth_tokens.issue(db_session, u, "reset_password")
    assert auth_tokens.redeem(db_session, old, "reset_password") is None
    assert auth_tokens.redeem(db_session, new, "reset_password") is not None


# ---------------------------------------------------------------- register --


def test_register_404_when_signup_closed(client, monkeypatch, _outbox):
    monkeypatch.setattr(settings, "ALLOW_SIGNUP", False)
    assert _register(client).status_code == 404
    assert _outbox.outbox == []


def test_register_creates_free_member_and_sends_verification(client, db_session, _outbox):
    r = _register(client, mobile="98765 43210")
    assert r.status_code == 201, r.text
    assert "token" in r.json()  # switch off: signed in straight away
    u = db_session.execute(select(User).where(User.email == "asha@example.com")).scalar_one()
    assert (u.role, u.plan, u.is_superuser, u.auth_provider) == ("member", "free", False, "local")
    assert u.email_verified_at is None and u.full_name == "Asha Rao" and u.mobile == "9876543210"
    assert len(_outbox.outbox) == 1 and _outbox.outbox[0].to == "asha@example.com"
    assert "/verify-email?token=" in _outbox.outbox[0].text
    acts = [a.action for a in db_session.execute(select(AuditLog)).scalars()]
    assert "auth.register" in acts


def test_register_withholds_login_token_when_verification_required(client, monkeypatch):
    monkeypatch.setattr(settings, "REQUIRE_EMAIL_VERIFICATION", True)
    r = _register(client)
    assert r.status_code == 201 and "token" not in r.json()


def test_register_rejects_weak_password_bad_name_bad_mobile_bad_email(client, _outbox):
    assert _register(client, password="short").status_code == 400
    assert _register(client, password="asha@example.com").status_code == 400
    assert _register(client, full_name="1234").status_code == 400
    assert _register(client, mobile="12345").status_code == 400
    assert _register(client, email="nope").status_code == 400
    assert _outbox.outbox == []


def test_register_duplicate_email_is_409_generic(client, db_session):
    _user(db_session, "old", email="Asha@Example.com")
    r = _register(client)
    assert r.status_code == 409
    assert "already" in r.json()["detail"] and "asha@example.com" not in r.json()["detail"].lower()


def test_audit_never_holds_tokens_or_passwords(client, db_session, _outbox):
    _register(client)
    raw = _token_from(_outbox, "verify-email")
    for a in db_session.execute(select(AuditLog)).scalars():
        blob = f"{a.before}{a.after}"
        assert raw not in blob and GOOD_PW not in blob


# ------------------------------------------------------------ verify email --


def test_verify_email_flow(client, db_session, _outbox):
    _register(client)
    raw = _token_from(_outbox, "verify-email")
    assert client.post(f"{API}/auth/verify-email", json={"token": raw}).status_code == 200
    u = db_session.execute(select(User).where(User.email == "asha@example.com")).scalar_one()
    db_session.refresh(u)
    assert u.email_verified_at is not None
    assert client.post(f"{API}/auth/verify-email", json={"token": raw}).status_code == 400  # single use
    assert client.post(f"{API}/auth/verify-email", json={"token": "bogus"}).status_code == 400


def test_resend_verification_generic_and_sends_only_for_unverified_local(client, db_session, _outbox):
    _user(db_session, "unv")
    _user(db_session, "ver", verified=datetime.now(UTC))
    answers = []
    for email in ("unv@example.com", "ver@example.com", "nobody@example.com", "UNV@example.com"):
        r = client.post(f"{API}/auth/resend-verification", json={"email": email})
        assert r.status_code == 200
        answers.append(r.json())
    assert all(a == answers[0] for a in answers)
    assert [m.to for m in _outbox.outbox] == ["unv@example.com", "unv@example.com"]


# ------------------------------------------------------------ forgot/reset --


def test_forgot_password_generic_for_unknown_and_sends_for_local(client, db_session, _outbox):
    _user(db_session, "loc")
    _user(db_session, "goo", provider="google", pw=None)
    outs = [
        client.post(f"{API}/auth/forgot-password", json={"email": e})
        for e in ("loc@example.com", "ghost@example.com", "goo@example.com")
    ]
    assert all(r.status_code == 200 for r in outs)
    assert outs[0].json() == outs[1].json() == outs[2].json()
    assert [m.to for m in _outbox.outbox] == ["loc@example.com"]


def test_reset_password_changes_password_ends_sessions_single_use(client, db_session, _outbox):
    u = _user(db_session, "loc")
    old_headers = _bearer(u)
    assert client.get(f"{API}/auth/me", headers=old_headers).status_code == 200
    client.post(f"{API}/auth/forgot-password", json={"email": "loc@example.com"})
    raw = _token_from(_outbox, "reset-password")

    weak = client.post(f"{API}/auth/reset-password", json={"token": raw, "new_password": "short"})
    assert weak.status_code == 400
    ok = client.post(f"{API}/auth/reset-password", json={"token": raw, "new_password": NEW_PW})
    assert ok.status_code == 200, ok.text  # a weak try did not burn the link
    assert (
        client.post(f"{API}/auth/reset-password", json={"token": raw, "new_password": NEW_PW}).status_code
        == 400
    )

    assert client.get(f"{API}/auth/me", headers=old_headers).status_code == 401  # old session ended
    assert client.post(f"{API}/auth/login", json={"username": "loc", "password": NEW_PW}).status_code == 200
    assert client.post(f"{API}/auth/login", json={"username": "loc", "password": GOOD_PW}).status_code == 401
    acts = [a.action for a in db_session.execute(select(AuditLog)).scalars()]
    assert {"auth.reset_requested", "auth.reset_done"} <= set(acts)


def test_google_only_account_can_set_password_via_admin_reset(client, db_session, _outbox):
    owner = _user(db_session, "own", role="owner")
    g = _user(db_session, "goo", provider="google", pw=None)
    r = client.post(f"{API}/admin/users/{g.id}/send-reset", headers=_bearer(owner))
    assert r.status_code == 200
    raw = _token_from(_outbox, "reset-password")
    assert raw not in r.text
    assert (
        client.post(f"{API}/auth/reset-password", json={"token": raw, "new_password": NEW_PW}).status_code
        == 200
    )
    db_session.refresh(g)
    assert g.hashed_password


# --------------------------------------------------------------- admin --


def test_admin_send_reset_needs_owner(client, db_session, _outbox):
    owner = _user(db_session, "own", role="owner")
    member = _user(db_session, "mem")
    url = f"{API}/admin/users/{member.id}/send-reset"
    assert client.post(url).status_code == 401
    assert client.post(url, headers=_bearer(member)).status_code == 403
    assert _outbox.outbox == []
    r = client.post(url, headers=_bearer(owner))
    assert r.status_code == 200 and _outbox.outbox[0].to == "mem@example.com"
    a = db_session.execute(select(AuditLog).where(AuditLog.action == "auth.admin_reset_sent")).scalar_one()
    assert a.actor_label == "own" and a.target_id == str(member.id)
    assert client.post(f"{API}/admin/users/999999/send-reset", headers=_bearer(owner)).status_code == 404


# ---------------------------------------------------- login enforcement --


@pytest.mark.parametrize(
    ("switch", "role", "provider", "verified", "expected"),
    [
        (False, "member", "local", None, 200),
        (True, "member", "local", None, 403),
        (True, "member", "local", datetime(2026, 1, 1, tzinfo=UTC), 200),
        (True, "owner", "local", None, 200),
        (True, "member", "google", None, 200),
    ],
)
def test_login_enforcement_matrix(
    client, db_session, monkeypatch, switch, role, provider, verified, expected
):
    monkeypatch.setattr(settings, "REQUIRE_EMAIL_VERIFICATION", switch)
    _user(db_session, "who", role=role, provider=provider, verified=verified)
    r = client.post(f"{API}/auth/login", json={"username": "who", "password": GOOD_PW})
    assert r.status_code == expected, r.text
    if expected == 403:
        assert "verify your email" in r.json()["detail"]


def test_unverified_wrong_password_still_gets_generic_401(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "REQUIRE_EMAIL_VERIFICATION", True)
    _user(db_session, "who")
    assert client.post(f"{API}/auth/login", json={"username": "who", "password": "wrong"}).status_code == 401


# ------------------------------------------------------------ rate limits --


def test_public_routes_have_rate_limit_dependencies():
    from swing_trade_ml.api.rate_limit import auth_limit, public_limit

    wanted = {
        "/auth/register": auth_limit,
        "/auth/verify-email": auth_limit,
        "/auth/reset-password": auth_limit,
        "/auth/resend-verification": public_limit,
        "/auth/forgot-password": public_limit,
    }
    found = {}
    for route in account_auth.router.routes:
        found[route.path.removeprefix("/auth") and route.path] = [
            d.call for d in route.dependant.dependencies
        ]
    for path, limiter in wanted.items():
        assert limiter in found[path], path
