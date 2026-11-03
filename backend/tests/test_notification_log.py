"""The Telegram status log: one send per key, honest states, no token, alert still sent if the log is down."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest

from swing_trade_ml.db.models.notification_log import NotificationLog
from swing_trade_ml.notifications.telegram import SendResult, TelegramNotifier, scrub
from swing_trade_ml.services import notification_log as nl

HEADERS = {"X-API-Key": "test-api-key"}
TOKEN = "123456789:AAH_fake_token_value_for_tests_only_1234"


class FakeNotifier:
    def __init__(self, *results: SendResult) -> None:
        self.results = list(results) or [SendResult(True, http_status=200)]
        self.calls = 0
        self.plain_calls = 0

    def send_sync_result(self, text, event="fill"):
        self.calls += 1
        return self.results[min(self.calls - 1, len(self.results) - 1)]

    def send_sync(self, text, event="fill"):
        self.plain_calls += 1
        return True


@pytest.fixture()
def sessions(db_session):
    """The log's own sessions, bound to the test transaction so nothing leaks between tests."""

    @contextmanager
    def scope():
        yield db_session
        db_session.flush()

    return scope


def _send(notifier, sessions, key="sell:1:100", **kw):
    return nl.send_logged(
        "text",
        dedupe_key=key,
        message_type="sell_full",
        book="Testing",
        symbol="ABC",
        trade_id=1,
        position_id=2,
        notifier=notifier,
        sessions=sessions,
        **kw,
    )


def _row(db, key="sell:1:100"):
    return db.query(NotificationLog).filter_by(dedupe_key=key).one()


def test_sent_means_accepted_and_keeps_a_trade_reference(db_session, sessions):
    n = FakeNotifier()
    assert _send(n, sessions) == "sent"
    row = _row(db_session)
    assert (row.status, row.book, row.trade_id, row.position_id, row.symbol) == (
        "SENT",
        "Testing",
        1,
        2,
        "ABC",
    )
    assert row.sent_at is not None and row.http_status == 200 and row.attempts == 1 and row.error_kind is None


def test_the_same_alert_is_never_sent_twice(db_session, sessions):
    n = FakeNotifier()
    assert _send(n, sessions) == "sent"
    assert _send(n, sessions) == "duplicate"
    assert n.calls == 1


def test_a_failure_is_recorded_with_safe_error_info_and_can_be_retried_to_success(db_session, sessions):
    n = FakeNotifier(
        SendResult(False, http_status=502, error_kind="http_502", error_detail="Bad Gateway"),
        SendResult(True, http_status=200),
    )
    assert _send(n, sessions) == "failed"
    row = _row(db_session)
    assert (row.status, row.error_kind, row.http_status, row.sent_at) == ("FAILED", "http_502", 502, None)
    assert _send(n, sessions) == "sent"  # same key: a FAILED alert is retried
    row = _row(db_session)
    assert row.status == "SENT" and row.attempts == 2 and row.error_kind is None
    assert _send(n, sessions) == "duplicate" and n.calls == 2


def test_retries_stop_after_the_limit(db_session, sessions):
    n = FakeNotifier(SendResult(False, error_kind="ConnectError"))
    outcomes = [_send(n, sessions) for _ in range(nl.MAX_ATTEMPTS + 2)]
    assert outcomes[: nl.MAX_ATTEMPTS] == ["failed"] * nl.MAX_ATTEMPTS
    assert outcomes[nl.MAX_ATTEMPTS :] == ["gave_up"] * 2
    assert n.calls == nl.MAX_ATTEMPTS


def test_a_send_in_flight_is_left_alone_but_a_dead_one_is_retried(db_session, sessions):
    n = FakeNotifier()
    now = datetime.now(UTC)
    db_session.add(
        NotificationLog(
            dedupe_key="sell:1:100",
            message_type="sell_full",
            book="Bot",
            status="PENDING",
            attempts=1,
            created_at=now,
            last_attempt_at=now,
        )
    )
    db_session.flush()
    assert _send(n, sessions) == "in_flight" and n.calls == 0
    _row(db_session).last_attempt_at = now - nl.PENDING_STALE_AFTER - timedelta(seconds=1)
    db_session.flush()
    assert _send(n, sessions) == "sent" and n.calls == 1


def test_telegram_switched_off_is_recorded_as_skipped_not_sent(db_session, sessions):
    n = FakeNotifier(SendResult(False, skipped=True))
    assert _send(n, sessions) == "skipped"
    assert _row(db_session).status == "SKIPPED"
    assert _send(n, sessions) == "duplicate"


def test_no_token_or_message_text_is_ever_stored(db_session, sessions):
    leaky = SendResult(
        False,
        error_kind="ConnectError",
        error_detail=f"failed for https://api.telegram.org/bot{TOKEN}/sendMessage",
    )
    _send(FakeNotifier(leaky), sessions)
    row = _row(db_session)
    stored = " ".join(str(getattr(row, c.name)) for c in NotificationLog.__table__.columns)
    assert TOKEN not in stored and "123456789:" not in stored
    assert "text" not in {c.name for c in NotificationLog.__table__.columns}  # no message body column at all


def test_scrub_removes_the_configured_token_and_anything_token_shaped():
    assert TOKEN not in scrub(f"bad {TOKEN} here", TOKEN)
    assert "[token]" in scrub("x 987654321:ABCDEFGHIJKLMNOPQRSTUVWXYZ0123 y")
    assert scrub(None) is None and len(scrub("a" * 500)) == 160


def test_the_alert_still_goes_out_when_the_log_cannot_be_used():
    @contextmanager
    def broken():
        raise RuntimeError("database is down")
        yield  # pragma: no cover

    n = FakeNotifier()
    out = nl.send_logged(
        "text", dedupe_key="k", message_type="sell_full", book="Bot", notifier=n, sessions=broken
    )
    assert out == "logged_off" and n.plain_calls == 1 and n.calls == 0


def test_a_failing_notifier_never_raises_into_the_caller(db_session, sessions):
    class Boom(FakeNotifier):
        def send_sync_result(self, text, event="fill"):
            raise ValueError("network exploded")

    assert _send(Boom(), sessions) == "failed"
    assert _row(db_session).error_kind == "ValueError"


def test_notifier_result_for_a_switched_off_telegram_is_skipped():
    assert TelegramNotifier().send_sync_result("hi", "fill").skipped is True  # tests run outside production


def test_endpoint_lists_the_log_and_counts(client, db_session):
    now = datetime.now(UTC)
    for i, status in enumerate(("SENT", "FAILED", "SENT")):
        db_session.add(
            NotificationLog(
                dedupe_key=f"sell:{i}:1",
                message_type="sell_full",
                book="Bot",
                status=status,
                attempts=1,
                created_at=now,
            )
        )
    db_session.flush()
    r = client.get("/api/v1/admin/notification-log", headers=HEADERS)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["last_7_days"]["SENT"] >= 2 and body["last_7_days"]["FAILED"] >= 1
    assert "does not mean delivered" in body["meaning"]
    assert all("text" not in row and "token" not in str(row).lower() for row in body["rows"])
    only_failed = client.get("/api/v1/admin/notification-log?status=FAILED", headers=HEADERS).json()["rows"]
    assert only_failed and all(row["status"] == "FAILED" for row in only_failed)
    assert client.get("/api/v1/admin/notification-log?status=BOGUS", headers=HEADERS).status_code == 422
