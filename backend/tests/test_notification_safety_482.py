# ruff: noqa: E501 (long plain-English test text)
"""#482: safety alerts never depend on TELEGRAM_NOTIFY_ON, and a failed verification or reset email is recorded.

Nothing real is sent: Telegram's `_post` and the email sender are fakes. Per-user alert settings, order placement, sizing,
risk and frozen files are untouched.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import select

from swing_trade_ml.api.v1.endpoints import account_auth
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.security import create_access_token, hash_password
from swing_trade_ml.db.models.audit import AuditLog
from swing_trade_ml.db.models.session import User
from swing_trade_ml.notifications import alert_policy
from swing_trade_ml.notifications.telegram import TelegramNotifier
from swing_trade_ml.services.email import LogEmailSender, set_sender_for_tests

API = "/api/v1"
PW = "Correct-horse-9battery"

# ------------------------------------------------------------------------------- 1. TELEGRAM_NOTIFY_ON and safety alerts


@pytest.fixture()
def telegram(monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "TELEGRAM_ENABLED", True)
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "fake-chat")

    async def fake_post(self, text):
        sent.append(text)
        return True

    monkeypatch.setattr(TelegramNotifier, "_post", fake_post)
    return sent


STOP_LOSS = "STOP-LOSS HIT - ACME: sold at the stop"


def test_a_stop_loss_alert_still_goes_out_when_the_setting_leaves_out_signal(telegram, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_NOTIFY_ON", "daily_summary,system")
    assert "signal" not in settings.telegram_events
    assert TelegramNotifier().send_sync(STOP_LOSS, "signal") is True
    assert telegram == [STOP_LOSS]


@pytest.mark.parametrize("category", ["signal", "order", "fill", "error", "system"])
def test_a_safety_alert_is_sent_whichever_category_the_setting_leaves_out(telegram, monkeypatch, category):
    monkeypatch.setattr(settings, "TELEGRAM_NOTIFY_ON", "nothing_matches")
    assert TelegramNotifier().send_sync(f"safety {category}", category) is True
    assert telegram == [f"safety {category}"]


def test_an_informational_alert_still_follows_the_setting(telegram, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_NOTIFY_ON", "daily_summary,system")
    sent = TelegramNotifier().send_sync("New idea: ACME", "signal", kind=alert_policy.TRADE_IDEAS)
    assert sent is False and telegram == []


def test_an_informational_alert_goes_out_when_the_setting_includes_its_category(telegram, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_NOTIFY_ON", "signal")
    monkeypatch.setattr("swing_trade_ml.services.alert_settings.gate", lambda kind, text: "send")
    assert TelegramNotifier().send_sync("New idea: ACME", "signal", kind=alert_policy.TRADE_IDEAS) is True
    assert telegram == ["New idea: ACME"]


def test_telegram_switched_off_still_sends_nothing_at_all(telegram, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_ENABLED", False)
    assert TelegramNotifier().send_sync(STOP_LOSS, "signal") is False and telegram == []


def test_outside_production_nothing_is_sent_even_for_a_safety_alert(telegram, monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "TELEGRAM_SEND_OUTSIDE_PRODUCTION", False)
    assert TelegramNotifier().send_sync(STOP_LOSS, "signal") is False and telegram == []


# ------------------------------------------------------------------------------- 2. a failed email is recorded


class _FailingSender:
    def __init__(self, raises: bool = False):
        self.raises = raises
        self.tried: list[str] = []

    def send(self, to, subject, text, html=None):
        self.tried.append(to)
        if self.raises:
            raise RuntimeError("provider down")
        return False


@pytest.fixture()
def failing(monkeypatch, db_session):
    account_auth._notice_last.clear()
    monkeypatch.setattr(settings, "ALLOW_SIGNUP", True)
    monkeypatch.setattr(settings, "APP_BASE_URL", "https://app.test")

    @contextmanager
    def same_session():
        yield db_session

    monkeypatch.setattr(account_auth, "session_scope", same_session)  # the background task writes into the test's transaction
    sender = _FailingSender()
    set_sender_for_tests(sender)
    yield sender
    set_sender_for_tests(None)


def _failures(db):
    return list(db.scalars(select(AuditLog).where(AuditLog.action == "auth.email_failed").order_by(AuditLog.id)))


def _member(db, name="mem"):
    user = User(username=name, email=f"{name}@example.com", hashed_password=hash_password(PW), is_active=True, role="member")
    db.add(user)
    db.flush()
    return user


def _owner_headers(db):
    owner = User(username="own482", email="own482@example.com", hashed_password=hash_password(PW), is_active=True, role="owner", is_superuser=True)
    db.add(owner)
    db.flush()
    return {"Authorization": "Bearer " + create_access_token(owner.username, {"uid": owner.id, "tv": 0})}


def test_a_failed_verification_email_at_sign_up_is_recorded_and_the_request_still_succeeds(client, db_session, failing):
    r = client.post(f"{API}/auth/register", json={"full_name": "Asha Rao", "email": "asha482@example.com", "password": PW})
    assert r.status_code == 201 and failing.tried == ["asha482@example.com"]
    rows = _failures(db_session)
    assert len(rows) == 1 and rows[0].after["kind"] == "verify_email"
    user = db_session.scalar(select(User).where(User.email == "asha482@example.com"))
    assert rows[0].target_type == "user" and rows[0].target_id == str(user.id)


def test_a_failed_resend_of_the_verification_email_is_recorded(client, db_session, failing):
    user = _member(db_session)
    r = client.post(f"{API}/auth/resend-verification", json={"email": user.email})
    assert r.status_code == 200
    rows = _failures(db_session)
    assert [(x.after["kind"], x.target_id) for x in rows] == [("verify_email", str(user.id))]


def test_a_failed_password_reset_email_is_recorded_and_the_answer_is_unchanged(client, db_session, failing):
    user = _member(db_session)
    known = client.post(f"{API}/auth/forgot-password", json={"email": user.email})
    unknown = client.post(f"{API}/auth/forgot-password", json={"email": "nobody482@example.com"})
    assert known.status_code == unknown.status_code == 200 and known.json() == unknown.json()  # no account enumeration
    rows = _failures(db_session)
    assert [(x.after["kind"], x.target_id) for x in rows] == [("reset_password", str(user.id))]


def test_a_failed_admin_triggered_reset_email_is_recorded(client, db_session, failing):
    user = _member(db_session)
    r = client.post(f"{API}/admin/users/{user.id}/send-reset", headers=_owner_headers(db_session))
    assert r.status_code == 200
    assert [(x.after["kind"], x.target_id) for x in _failures(db_session)] == [("reset_password", str(user.id))]


def test_a_sender_that_raises_is_recorded_and_never_breaks_the_request(client, db_session, failing):
    failing.raises = True
    user = _member(db_session)
    assert client.post(f"{API}/auth/forgot-password", json={"email": user.email}).status_code == 200
    assert len(_failures(db_session)) == 1


def test_the_failure_record_holds_no_token_no_password_and_no_full_address(client, db_session, failing):
    user = _member(db_session, "private482")
    client.post(f"{API}/auth/forgot-password", json={"email": user.email})
    text = str([(r.before, r.after, r.target_id, r.actor_label) for r in _failures(db_session)])
    assert "token=" not in text and PW not in text and user.email not in text


def test_a_successful_send_records_no_failure(client, db_session, monkeypatch):
    account_auth._notice_last.clear()
    sender = LogEmailSender()
    set_sender_for_tests(sender)
    try:
        user = _member(db_session, "fine482")
        assert client.post(f"{API}/auth/forgot-password", json={"email": user.email}).status_code == 200
        assert len(sender.outbox) == 1 and _failures(db_session) == []
    finally:
        set_sender_for_tests(None)
