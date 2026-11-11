"""Customer account deletion against the scratch test database. No network: fake billing, log email sender."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.security import create_access_token, hash_password
from swing_trade_ml.db.models.account_deletion import AccountDeletion
from swing_trade_ml.db.models.audit import AuditLog
from swing_trade_ml.db.models.auth_tokens import AuthToken
from swing_trade_ml.db.models.billing import PlanGrant, Subscription
from swing_trade_ml.db.models.invites import InviteRequest
from swing_trade_ml.db.models.session import User
from swing_trade_ml.db.models.user_watchlist import UserWatchlistItem
from swing_trade_ml.services import account_deletion as svc
from swing_trade_ml.services.billing import service as billing
from swing_trade_ml.services.billing.base import BillingError
from swing_trade_ml.services.billing.fake import FakeProvider
from swing_trade_ml.services.email import LogEmailSender, set_sender_for_tests

API = "/api/v1"
PW = "correct horse battery staple"


@pytest.fixture(autouse=True)
def _on(monkeypatch):
    monkeypatch.setattr(settings, "ACCOUNT_DELETION_ENABLED", True)
    monkeypatch.setattr(settings, "ACCOUNT_DELETION_GRACE_DAYS", 14)
    monkeypatch.setattr(settings, "APP_BASE_URL", "https://app.test")
    monkeypatch.setattr(settings, "BILLING_ENABLED", True)
    monkeypatch.setattr(settings, "BILLING_PROVIDER", "fake")
    fake = FakeProvider()
    billing.set_provider(fake)
    sender = LogEmailSender()
    set_sender_for_tests(sender)
    yield {"fake": fake, "mail": sender}
    billing.set_provider(None)
    set_sender_for_tests(None)


@pytest.fixture()
def mail(_on) -> LogEmailSender:
    return _on["mail"]


@pytest.fixture()
def fake(_on) -> FakeProvider:
    return _on["fake"]


def make_user(db, name="asha", *, role="member", pw=PW, provider="local") -> User:
    u = User(
        username=name,
        email=f"{name}@example.com",
        full_name="Asha Rao",
        mobile="9876543210",
        hashed_password=hash_password(pw) if pw else None,
        google_id=f"g-{name}" if provider == "google" else None,
        auth_provider=provider,
        is_active=True,
        role=role,
        is_superuser=(role == "owner"),
    )
    db.add(u)
    db.flush()
    return u


def bearer(u: User) -> dict[str, str]:
    return {
        "Authorization": "Bearer "
        + create_access_token(u.username, {"uid": u.id, "tv": u.token_version or 0})
    }


def token_from(mail: LogEmailSender, path: str) -> str:
    link = next(w for w in mail.outbox[-1].text.split() if f"/{path}?token=" in w)
    return link.split("token=")[1]


def start(client, user, pw=PW):
    return client.post(f"{API}/account/deletion/request", json={"password": pw}, headers=bearer(user))


def confirm(client, mail):
    return client.post(
        f"{API}/account/deletion/confirm", json={"token": token_from(mail, "confirm-deletion")}
    )


def go_live_pro(db, user, fake) -> Subscription:
    info = fake.create_subscription(user, "pro")
    sub = Subscription(
        user_id=user.id,
        provider="fake",
        provider_subscription_id=info.provider_subscription_id,
        status="active",
        current_end=datetime.now(UTC) + timedelta(days=20),
    )
    db.add(sub)
    db.flush()
    fake._subs[info.provider_subscription_id] = fake._subs[info.provider_subscription_id].__class__(
        provider_subscription_id=info.provider_subscription_id, status="active", provider_plan_id="p"
    )
    return sub


# ---------------------------------------------------------------- switch off


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/account/deletion/request"),
        ("POST", "/account/deletion/confirm"),
        ("GET", "/account/deletion"),
        ("GET", "/account/export"),
    ],
)
def test_routes_are_404_when_switched_off(client, db_session, monkeypatch, method, path):
    monkeypatch.setattr(settings, "ACCOUNT_DELETION_ENABLED", False)
    u = make_user(db_session)
    assert client.request(method, API + path, headers=bearer(u), json={"token": "x"}).status_code == 404


def test_job_does_nothing_when_switched_off(db_session, monkeypatch):
    monkeypatch.setattr(settings, "ACCOUNT_DELETION_ENABLED", False)
    assert svc.process_due(db_session) == {"completed": 0, "skipped": 0, "protected": 0}


# ---------------------------------------------------------------- request


def test_request_needs_sign_in_and_refuses_the_api_key(client):
    assert client.post(f"{API}/account/deletion/request", json={}).status_code == 401
    r = client.post(f"{API}/account/deletion/request", json={}, headers={"X-API-Key": "test-api-key"})
    assert r.status_code == 403


def test_wrong_password_refused_and_nothing_stored(client, db_session, mail):
    u = make_user(db_session)
    r = start(client, u, "not the password at all")
    assert r.status_code == 400
    assert mail.outbox == []
    assert db_session.execute(select(AccountDeletion)).scalars().all() == []


def test_request_sends_confirm_link_and_deletes_nothing(client, db_session, mail):
    u = make_user(db_session)
    assert start(client, u).status_code == 200
    assert mail.outbox[-1].to == "asha@example.com" and "/confirm-deletion?token=" in mail.outbox[-1].text
    row = svc.open_request(db_session, u.id)
    assert row.status == "pending"
    assert u.email == "asha@example.com" and u.is_active
    # still signed in: a request alone changes nothing
    assert client.get(f"{API}/account/deletion", headers=bearer(u)).json()["status"] == "pending"


def test_owner_cannot_request(client, db_session, mail):
    owner = make_user(db_session, "boss", role="owner")
    r = start(client, owner)
    assert r.status_code == 400 and mail.outbox == []


def test_google_account_needs_no_password_only_email_link(client, db_session, mail):
    u = make_user(db_session, "gina", pw=None, provider="google")
    assert start(client, u, None).status_code == 200
    assert "/confirm-deletion?token=" in mail.outbox[-1].text


def test_asking_twice_keeps_one_open_request(client, db_session, mail):
    u = make_user(db_session)
    start(client, u)
    start(client, u)
    rows = db_session.execute(select(AccountDeletion).where(AccountDeletion.user_id == u.id)).scalars().all()
    assert len(rows) == 1
    first = mail.outbox[0].text
    assert first != mail.outbox[-1].text  # a fresh link replaced the old one


# ---------------------------------------------------------------- confirm


def test_confirm_schedules_grace_ends_sessions_and_emails_cancel_link(client, db_session, mail):
    u = make_user(db_session)
    old_headers = bearer(u)
    start(client, u)
    r = confirm(client, mail)
    assert r.status_code == 200, r.text
    row = svc.latest_request(db_session, u.id)
    assert row.status == "scheduled"
    assert timedelta(days=13, hours=23) < row.scheduled_for - datetime.now(UTC) <= timedelta(days=14)
    assert "/cancel-deletion?token=" in mail.outbox[-1].text
    # the old session no longer works
    assert client.get(f"{API}/auth/me", headers=old_headers).status_code == 401
    # nothing deleted yet
    assert u.email == "asha@example.com"


def test_confirm_link_works_once(client, db_session, mail):
    u = make_user(db_session)
    start(client, u)
    tok = token_from(mail, "confirm-deletion")
    assert client.post(f"{API}/account/deletion/confirm", json={"token": tok}).status_code == 200
    assert client.post(f"{API}/account/deletion/confirm", json={"token": tok}).status_code == 400


def test_bad_and_expired_token_refused(client, db_session, mail):
    u = make_user(db_session)
    start(client, u)
    assert client.post(f"{API}/account/deletion/confirm", json={"token": "nope"}).status_code == 400
    tok = auth_expire = token_from(mail, "confirm-deletion")
    row = db_session.execute(select(AuthToken).where(AuthToken.user_id == u.id)).scalars().first()
    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.flush()
    assert client.post(f"{API}/account/deletion/confirm", json={"token": auth_expire}).status_code == 400
    assert tok


def test_confirm_cancels_live_pro_first(client, db_session, mail, fake):
    u = make_user(db_session)
    sub = go_live_pro(db_session, u, fake)
    start(client, u)
    assert confirm(client, mail).status_code == 200
    db_session.refresh(sub)
    assert sub.status == "cancelled"
    assert "Pro subscription has been cancelled" in mail.outbox[-1].text


def test_provider_failure_schedules_nothing_and_link_still_works(client, db_session, mail, fake, monkeypatch):
    u = make_user(db_session)
    sub = go_live_pro(db_session, u, fake)
    start(client, u)
    tok = token_from(mail, "confirm-deletion")

    def boom(*a, **k):
        raise BillingError("provider down")

    monkeypatch.setattr(fake, "cancel_subscription", boom)
    r = client.post(f"{API}/account/deletion/confirm", json={"token": tok})
    assert r.status_code == 502
    db_session.expire_all()
    assert svc.open_request(db_session, u.id).status == "pending"
    assert sub.status == "active"
    monkeypatch.undo()
    monkeypatch.setattr(settings, "ACCOUNT_DELETION_ENABLED", True)
    assert client.post(f"{API}/account/deletion/confirm", json={"token": tok}).status_code == 200


# ---------------------------------------------------------------- sign-in blocked / cancel


def test_sign_in_blocked_after_confirm_with_generic_message(client, db_session, mail):
    u = make_user(db_session)
    ok = client.post(f"{API}/auth/login", json={"username": "asha", "password": PW})
    assert ok.status_code == 200
    start(client, u)
    confirm(client, mail)
    r = client.post(f"{API}/auth/login", json={"username": "asha", "password": PW})
    wrong = client.post(f"{API}/auth/login", json={"username": "asha", "password": "wrong wrong wrong wrong"})
    assert r.status_code == 401 and r.json() == wrong.json()
    assert db_session.execute(select(AuditLog).where(AuditLog.action == "auth.login_deleting")).first()


def test_cancel_in_grace_restores_sign_in(client, db_session, mail):
    u = make_user(db_session)
    start(client, u)
    confirm(client, mail)
    tok = token_from(mail, "cancel-deletion")
    assert client.post(f"{API}/account/deletion/cancel", json={"token": tok}).status_code == 200
    assert svc.latest_request(db_session, u.id).status == "cancelled"
    assert client.post(f"{API}/auth/login", json={"username": "asha", "password": PW}).status_code == 200
    # and the person can ask again later
    assert start(client, u).status_code == 200


def test_cancel_works_even_when_the_switch_is_off(client, db_session, mail, monkeypatch):
    u = make_user(db_session)
    start(client, u)
    confirm(client, mail)
    tok = token_from(mail, "cancel-deletion")
    monkeypatch.setattr(settings, "ACCOUNT_DELETION_ENABLED", False)
    assert client.post(f"{API}/account/deletion/cancel", json={"token": tok}).status_code == 200


def test_cancel_after_grace_ended_refused(client, db_session, mail):
    u = make_user(db_session)
    start(client, u)
    confirm(client, mail)
    tok = token_from(mail, "cancel-deletion")
    svc.latest_request(db_session, u.id).scheduled_for = datetime.now(UTC) - timedelta(seconds=1)
    db_session.flush()
    assert client.post(f"{API}/account/deletion/cancel", json={"token": tok}).status_code == 400


def test_cancelled_pro_stays_cancelled(client, db_session, mail, fake):
    u = make_user(db_session)
    sub = go_live_pro(db_session, u, fake)
    start(client, u)
    confirm(client, mail)
    client.post(f"{API}/account/deletion/cancel", json={"token": token_from(mail, "cancel-deletion")})
    db_session.refresh(sub)
    assert sub.status == "cancelled"


# ---------------------------------------------------------------- the job


def _scheduled_user(client, db, mail, name="asha"):
    u = make_user(db, name)
    start(client, u)
    confirm(client, mail)
    svc.latest_request(db, u.id).scheduled_for = datetime.now(UTC) - timedelta(minutes=1)
    db.flush()
    return u


def test_job_waits_until_grace_ends(client, db_session, mail):
    u = make_user(db_session)
    start(client, u)
    confirm(client, mail)
    assert svc.process_due(db_session)["completed"] == 0
    assert u.email == "asha@example.com"


def test_job_anonymises_and_keeps_the_stub(client, db_session, mail, fake):
    u = _scheduled_user(client, db_session, mail)
    db_session.add(UserWatchlistItem(user_id=u.id, symbol="TCS"))
    db_session.add(
        InviteRequest(
            name="Asha Rao",
            email="asha@example.com",
            phone="9876543210",
            experience="just_starting",
            language="english",
            user_id=u.id,
            note="friend of owner",
        )
    )
    db_session.add(PlanGrant(user_id=u.id, plan_key="pro", starts_at=datetime.now(UTC), reason="trial"))
    db_session.add(AuditLog(actor_user_id=u.id, actor_label="asha", action="auth.login"))
    db_session.flush()
    uid = u.id
    assert svc.process_due(db_session)["completed"] == 1
    db_session.expire_all()
    u = db_session.get(User, uid)
    assert u.username == f"deleted-{uid}" and u.email is None and u.full_name is None
    assert u.mobile is None and u.hashed_password is None and u.google_id is None
    assert u.is_active is False and u.plan == "free"
    assert (
        db_session.execute(select(UserWatchlistItem).where(UserWatchlistItem.user_id == uid)).first() is None
    )
    assert db_session.execute(select(AuthToken).where(AuthToken.user_id == uid)).first() is None
    inv = db_session.execute(select(InviteRequest).where(InviteRequest.user_id == uid)).scalar_one()
    assert inv.name == "Deleted" and inv.phone is None and inv.note is None and "asha" not in inv.email
    assert all(
        a.actor_label == f"deleted-{uid}"
        for a in db_session.execute(
            select(AuditLog).where(AuditLog.actor_user_id == uid, AuditLog.action == "auth.login")
        ).scalars()
    )
    # money records stay
    assert db_session.execute(select(PlanGrant).where(PlanGrant.user_id == uid)).first() is not None
    assert svc.latest_request(db_session, uid).status == "completed"
    done = (
        db_session.execute(select(AuditLog).where(AuditLog.action == "account.deletion_completed"))
        .scalars()
        .all()
    )
    assert done and "asha" not in str(done[-1].__dict__)


def test_completed_account_cannot_sign_in_and_email_is_free_again(client, db_session, mail):
    u = _scheduled_user(client, db_session, mail)
    svc.process_due(db_session)
    r = client.post(f"{API}/auth/login", json={"username": "asha", "password": PW})
    assert r.status_code == 401
    make_user(db_session, "asha2")  # unique constraints ok
    again = User(username="new", email="asha@example.com", hashed_password="x", is_active=True)
    db_session.add(again)
    db_session.flush()
    assert u.id != again.id


def test_job_only_touches_the_requester(client, db_session, mail):
    _scheduled_user(client, db_session, mail, "leaver")
    other = make_user(db_session, "stayer")
    db_session.add(UserWatchlistItem(user_id=other.id, symbol="INFY"))
    db_session.flush()
    svc.process_due(db_session)
    db_session.expire_all()
    other = db_session.get(User, other.id)
    assert other.email == "stayer@example.com" and other.is_active
    assert db_session.execute(select(UserWatchlistItem).where(UserWatchlistItem.user_id == other.id)).first()


def test_job_never_deletes_an_owner_promoted_after_the_request(client, db_session, mail):
    u = _scheduled_user(client, db_session, mail)
    u.role = "owner"
    db_session.flush()
    assert svc.process_due(db_session)["protected"] == 1
    assert u.email == "asha@example.com"
    assert svc.latest_request(db_session, u.id).note == "protected_account"


def test_job_skips_when_pro_cannot_be_cancelled_and_retries(client, db_session, mail, fake, monkeypatch):
    u = _scheduled_user(client, db_session, mail)
    sub = go_live_pro(db_session, u, fake)  # a subscription that appeared during the grace period
    orig = fake.cancel_subscription
    monkeypatch.setattr(
        fake, "cancel_subscription", lambda *a, **k: (_ for _ in ()).throw(BillingError("down"))
    )
    assert svc.process_due(db_session)["skipped"] == 1
    assert u.email == "asha@example.com" and sub.status == "active"
    monkeypatch.setattr(fake, "cancel_subscription", orig)
    assert svc.process_due(db_session)["completed"] == 1


# ---------------------------------------------------------------- export


def test_export_is_own_data_only(client, db_session):
    a, b = make_user(db_session, "alice"), make_user(db_session, "bob")
    db_session.add(UserWatchlistItem(user_id=a.id, symbol="TCS"))
    db_session.add(UserWatchlistItem(user_id=b.id, symbol="INFY"))
    db_session.flush()
    body = client.get(f"{API}/account/export", headers=bearer(a)).json()
    assert body["profile"]["email"] == "alice@example.com"
    assert [w["symbol"] for w in body["watchlist"]] == ["TCS"]
    assert "hashed_password" not in str(body) and "bob" not in str(body)
