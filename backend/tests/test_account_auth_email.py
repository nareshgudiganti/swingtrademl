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
from swing_trade_ml.core.security import create_access_token, hash_password, verify_password
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
from swing_trade_ml.services.email.templates import (
    already_registered_email,
    reset_email,
    verification_email,
)

API = "/api/v1"
GOOD_PW = "correct horse battery staple"
NEW_PW = "another long passphrase here"


@pytest.fixture(autouse=True)
def _outbox(monkeypatch):
    account_auth._notice_last.clear()
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
    assert set(r.json()) == {"message"}  # never a login token, whatever the switch says
    u = db_session.execute(select(User).where(User.email == "asha@example.com")).scalar_one()
    assert (u.role, u.plan, u.is_superuser, u.auth_provider) == ("member", "free", False, "local")
    assert u.email_verified_at is None and u.full_name == "Asha Rao" and u.mobile == "9876543210"
    assert len(_outbox.outbox) == 1 and _outbox.outbox[0].to == "asha@example.com"
    assert "/verify-email?token=" in _outbox.outbox[0].text
    acts = [a.action for a in db_session.execute(select(AuditLog)).scalars()]
    assert "auth.register" in acts


@pytest.mark.parametrize("switch", [False, True])
@pytest.mark.parametrize("existing", [False, True])
def test_register_never_returns_a_token(client, db_session, monkeypatch, switch, existing):
    monkeypatch.setattr(settings, "REQUIRE_EMAIL_VERIFICATION", switch)
    if existing:
        _user(db_session, "old", email="asha@example.com")
    r = _register(client)
    assert r.status_code == 201 and set(r.json()) == {"message"}
    assert "token" not in r.text and "access" not in r.text


def test_register_rejects_weak_password_bad_name_bad_mobile_bad_email(client, _outbox):
    assert _register(client, password="short").status_code == 400
    assert _register(client, password="asha@example.com").status_code == 400
    assert _register(client, full_name="1234").status_code == 400
    assert _register(client, mobile="12345").status_code == 400
    assert _register(client, email="nope").status_code == 400
    assert _outbox.outbox == []


def test_register_new_and_existing_email_get_identical_public_answer(client, db_session, _outbox):
    _user(db_session, "old", email="Taken@Example.com", verified=datetime(2026, 1, 1, tzinfo=UTC))
    old = db_session.execute(select(User).where(User.username == "old")).scalar_one()
    before = (old.hashed_password, old.email_verified_at, old.role, old.full_name, old.is_superuser)
    n_users = len(db_session.execute(select(User)).scalars().all())

    existing = _register(client, email="taken@example.com", full_name="Someone Else", password=NEW_PW)
    fresh = _register(client, email="brand-new@example.com")
    assert (existing.status_code, existing.json()) == (fresh.status_code, fresh.json())
    assert existing.status_code == 201 and set(existing.json()) == {"message"}
    for h in ("content-type", "content-length", "set-cookie", "location", "www-authenticate"):
        assert existing.headers.get(h) == fresh.headers.get(h), h

    db_session.expire_all()
    old = db_session.execute(select(User).where(User.username == "old")).scalar_one()
    assert (old.hashed_password, old.email_verified_at, old.role, old.full_name, old.is_superuser) == before
    assert len(db_session.execute(select(User)).scalars().all()) == n_users + 1  # only the new one
    assert db_session.execute(select(AuthToken).where(AuthToken.user_id == old.id)).first() is None


def test_register_existing_email_sends_notice_new_email_sends_verification(client, db_session, _outbox):
    _user(db_session, "old", email="taken@example.com")
    _register(client, email="taken@example.com")
    assert len(_outbox.outbox) == 1 and _outbox.outbox[0].to == "taken@example.com"
    note = _outbox.outbox[0]
    assert note.subject == already_registered_email()[0]
    assert "Someone tried to sign up" in note.text
    assert "https://app.test/login" in note.text and "https://app.test/reset-password" in note.text
    assert "token=" not in note.text and "/verify-email" not in note.text

    _register(client, email="fresh@example.com")
    assert len(_outbox.outbox) == 2 and _outbox.outbox[1].to == "fresh@example.com"
    assert "/verify-email?token=" in _outbox.outbox[1].text


def test_register_notice_is_limited_to_one_per_hour_per_address(client, db_session, _outbox, monkeypatch):
    _user(db_session, "old", email="taken@example.com")
    r1 = _register(client, email="taken@example.com")
    r2 = _register(client, email="TAKEN@example.com")
    assert (r1.status_code, r1.json()) == (r2.status_code, r2.json())
    assert len(_outbox.outbox) == 1  # second one suppressed, answer unchanged
    _register(client, email="taken@example.com", password=NEW_PW)  # other password, same address
    assert len(_outbox.outbox) == 1
    monkeypatch.setattr(account_auth, "NOTICE_EVERY_SECONDS", 0)
    _register(client, email="taken@example.com")
    assert len(_outbox.outbox) == 2


def test_register_validation_errors_do_not_depend_on_the_email_existing(client, db_session, _outbox):
    _user(db_session, "old", email="taken@example.com")
    for email in ("taken@example.com", "free@example.com"):
        assert _register(client, email=email, password="short").status_code == 400
        assert _register(client, email=email, full_name="1234").status_code == 400
    assert _outbox.outbox == []


def test_already_registered_template_has_links_and_no_token(monkeypatch):
    monkeypatch.setattr(settings, "APP_BASE_URL", "https://app.test/")
    _, text, html = already_registered_email()
    assert "https://app.test/login" in text and "https://app.test/reset-password" in html
    assert "token" not in text and "token" not in html


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


# ------------------------------------------------- common-password list --


def _long_common() -> str:
    from swing_trade_ml.core.password_policy import load_common_passwords

    return sorted(w for w in load_common_passwords() if len(w) >= 15)[0]


def test_bundled_common_password_list_is_loaded_and_has_long_entries():
    from swing_trade_ml.core.password_policy import check_password, load_common_passwords

    assert len(load_common_passwords()) > 100
    assert "passwordpassword" in load_common_passwords()
    assert any("too common" in p for p in check_password("passwordpassword"))  # default None = bundled list


def test_no_caller_overrides_the_common_password_list():
    import pathlib

    root = pathlib.Path(account_auth.__file__).parents[2]
    for f in root.rglob("*.py"):
        if f.name != "password_policy.py":
            assert "common_passwords=" not in f.read_text(encoding="utf-8"), f


@pytest.mark.parametrize("pw", ["passwordpassword", "PasswordPassword"])
def test_register_refuses_a_common_password_even_when_long_enough(client, db_session, _outbox, pw):
    assert len(pw) >= 15
    r = _register(client, password=pw)
    assert r.status_code == 400 and "too common" in r.json()["detail"]
    r2 = _register(client, password=_long_common())
    assert r2.status_code == 400 and "too common" in r2.json()["detail"]
    assert _outbox.outbox == []
    assert db_session.execute(select(User).where(User.email == "asha@example.com")).first() is None


def test_reset_password_refuses_a_common_password_and_keeps_the_link(client, db_session, _outbox):
    u = _user(db_session, "who")
    raw = auth_tokens.issue(db_session, u, "reset_password")
    for pw in ("passwordpassword", _long_common()):
        r = client.post(f"{API}/auth/reset-password", json={"token": raw, "new_password": pw})
        assert r.status_code == 400 and "too common" in r.json()["detail"]
    db_session.refresh(u)
    assert verify_password(GOOD_PW, u.hashed_password)  # unchanged
    ok = client.post(f"{API}/auth/reset-password", json={"token": raw, "new_password": NEW_PW})
    assert ok.status_code == 200  # the link was not burned by the refused tries


def test_admin_triggered_reset_goes_through_the_same_checked_route(client, db_session, _outbox):
    owner = _user(db_session, "boss", role="owner")
    target = _user(db_session, "who")
    r = client.post(f"{API}/admin/users/{target.id}/send-reset", headers=_bearer(owner))
    assert r.status_code == 200
    raw = _token_from(_outbox, "reset-password")
    bad = client.post(f"{API}/auth/reset-password", json={"token": raw, "new_password": "passwordpassword"})
    assert bad.status_code == 400 and "too common" in bad.json()["detail"]




def _approved_invite(db, email: str, code: str) -> None:
    """An approved, unused invite for `email` whose one-time code is `code` (as Admin > Invites makes)."""
    from swing_trade_ml.api.v1.endpoints.invites import hash_code
    from swing_trade_ml.db.models.invites import InviteRequest

    db.add(
        InviteRequest(
            name="Invited Person",
            email=email,
            experience="just_starting",
            language="english",
            status="approved",
            code_hash=hash_code(code),
        )
    )
    db.flush()


def test_invite_signup_refuses_weak_and_common_passwords(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_SIGNUP", False)
    code = "made-up-invite-code-1"
    _approved_invite(db_session, "newperson@example.com", code)
    for pw in ("passwordpassword", "short", "newperson@example.com"):
        body = {"username": "gapuser", "password": pw, "email": "newperson@example.com", "invite_code": code}
        assert client.post(f"{API}/auth/signup", json=body).status_code == 400, pw
    assert db_session.execute(select(User).where(User.username == "gapuser")).first() is None
    ok_body = {"username": "gapuser", "password": NEW_PW, "email": "newperson@example.com", "invite_code": code}
    ok = client.post(f"{API}/auth/signup", json=ok_body)
    assert ok.status_code == 201


def test_change_password_refuses_weak_and_common_but_keeps_old_password(client, db_session):
    u = _user(db_session, "who")
    for pw in ("passwordpassword", "short", "who@example.com"):
        body = {"current_password": GOOD_PW, "new_password": pw}
        r = client.post(f"{API}/auth/password", headers=_bearer(u), json=body)
        assert r.status_code == 400 and r.json()["detail"], pw
    db_session.refresh(u)
    assert verify_password(GOOD_PW, u.hashed_password)
    body = {"current_password": GOOD_PW, "new_password": NEW_PW}
    assert client.post(f"{API}/auth/password", headers=_bearer(u), json=body).status_code == 200


def test_existing_short_legacy_password_still_logs_in_and_me_works(client, db_session):
    _user(db_session, "legacy", pw="short1")  # 6 characters, set before the policy
    r = client.post(f"{API}/auth/login", json={"username": "legacy", "password": "short1"})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    me = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json()["username"] == "legacy"


def test_cli_create_user_refuses_weak_and_common_passwords(monkeypatch, capsys):
    import argparse

    from swing_trade_ml import cli
    from swing_trade_ml.db import session as db_session_mod

    def boom(*a, **k):
        raise AssertionError("must not reach the database")

    monkeypatch.setattr(db_session_mod, "session_scope", boom)
    for pw in ("short", "passwordpassword"):
        args = argparse.Namespace(username="x", password=pw, email="x@example.com", role="member")
        assert cli.cmd_create_user(args) == 1
        out = capsys.readouterr().out
        assert "at least 15" in out or "too common" in out


def test_cli_create_user_accepts_a_good_password(db_session, monkeypatch):
    import argparse
    from contextlib import contextmanager

    from swing_trade_ml import cli
    from swing_trade_ml.db import session as db_session_mod

    @contextmanager
    def scope():
        yield db_session

    monkeypatch.setattr(db_session_mod, "session_scope", scope)
    args = argparse.Namespace(username="cliuser", password=NEW_PW, email=None, role="member")
    assert cli.cmd_create_user(args) == 0
    u = db_session.execute(select(User).where(User.username == "cliuser")).scalar_one()
    assert verify_password(NEW_PW, u.hashed_password)


def test_invite_signup_conflicts_use_one_generic_message(client, db_session, monkeypatch):
    """Even a real invite holder is told one thing for a taken username and for a taken email."""
    monkeypatch.setattr(settings, "ALLOW_SIGNUP", False)
    _user(db_session, "taken", email="taken@example.com")
    _approved_invite(db_session, "fresh@example.com", "made-up-invite-code-2")
    _approved_invite(db_session, "taken@example.com", "made-up-invite-code-3")
    by_name = client.post(
        f"{API}/auth/signup",
        json={"username": "taken", "password": NEW_PW, "email": "fresh@example.com", "invite_code": "made-up-invite-code-2"},
    )
    by_mail = client.post(
        f"{API}/auth/signup",
        json={"username": "other", "password": NEW_PW, "email": "TAKEN@example.com", "invite_code": "made-up-invite-code-3"},
    )
    assert by_name.status_code == by_mail.status_code == 409
    assert by_name.json() == by_mail.json()


# ------------------------------------------------ notice throttle: Redis --


class _SetNxRedis:
    def __init__(self):
        self.keys: dict[str, tuple[str, int | None]] = {}

    def pipeline(self, transaction=True):  # the per-IP request limiter also talks to Redis
        class _P:
            def incr(self, key): ...
            def expire(self, key, ttl): ...
            def execute(self):
                return [1, True]

        return _P()

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.keys:
            return None
        self.keys[key] = (value, ex)
        return True


class _BrokenRedis:
    def set(self, *a, **k):
        raise ConnectionError("down")


def test_notice_throttle_uses_shared_redis_with_hashed_key_and_one_hour_expiry(
    client, db_session, _outbox, monkeypatch
):
    from swing_trade_ml.api import rate_limit

    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    fake = _SetNxRedis()
    rate_limit.set_redis_client(fake)
    try:
        _user(db_session, "old", email="taken@example.com")
        _register(client, email="taken@example.com")
        _register(client, email="taken@example.com")
        assert len(_outbox.outbox) == 1
        ((key, (_, ttl)),) = fake.keys.items()
        assert ttl == 3600 and key.startswith("notice:already-registered:")
        assert "taken" not in key and "example" not in key and len(key.rsplit(":", 1)[1]) == 64
        assert account_auth._notice_last == {}  # in-process memory unused while Redis answers
        _register(client, email="taken@example.com")  # "another worker": same Redis
        assert len(_outbox.outbox) == 1
    finally:
        rate_limit.set_redis_client(None)


def test_notice_throttle_falls_back_to_memory_when_redis_is_down(client, db_session, _outbox, monkeypatch):
    from swing_trade_ml.api import rate_limit

    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    rate_limit.set_redis_client(_BrokenRedis())
    try:
        _user(db_session, "old", email="taken@example.com")
        r1 = _register(client, email="taken@example.com")
        r2 = _register(client, email="taken@example.com")
        assert (r1.status_code, r1.json()) == (r2.status_code, r2.json())
        assert r1.status_code == 201 and len(_outbox.outbox) == 1
    finally:
        rate_limit.set_redis_client(None)
