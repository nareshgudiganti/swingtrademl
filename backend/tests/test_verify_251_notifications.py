# ruff: noqa: E501 (long lines in test code)
"""#251: notification preferences and delivery failures, checked against the code on main (`5de3b9c`).

Tests only: no alert, notification or order code is changed. Nothing is ever sent: the Telegram network call
(`_post`) and the HTTP client are replaced by recorders, the email sender is the in-memory log sender or a stub,
and every token and chat id is a made-up placeholder.

What is already proved elsewhere is cited, not repeated: `test_alert_policy.py` (per-type switches, quiet hours, digest),
`test_alert_settings.py` (stored settings, owner-only API, held outbox), `test_account_auth_email.py` (email senders, one
notice per hour), `test_brain_alerts_service.py` (brain alerts recorded only when sent), `test_telegram_production_only.py`,
and Developer-1's #250 note (`docs/verification/250-alerts.md` on `test/250-alerts`: a stop-loss send that fails is still
marked sent, e2/e3).

Gaps are strict expected failures (`xfail(strict=True, raises=AssertionError)`): they state what the code SHOULD do.
"""

from __future__ import annotations

import ast
import asyncio
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import select

import swing_trade_ml
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.alerts import AlertOutbox, AlertSettings
from swing_trade_ml.db.models.audit import AuditLog
from swing_trade_ml.db.models.session import User
from swing_trade_ml.notifications import alert_policy as policy
from swing_trade_ml.notifications import telegram as telegram_module
from swing_trade_ml.notifications.alert_policy import AlertPrefs
from swing_trade_ml.notifications.telegram import TelegramNotifier
from swing_trade_ml.services import alert_settings
from swing_trade_ml.services.email import LogEmailSender, set_sender_for_tests

IST = ZoneInfo("Asia/Kolkata")
API = "/api/v1"
KEY = {"X-API-Key": "test-api-key"}
SETTINGS_URL = f"{API}/notifications/alert-settings"
SRC = Path(swing_trade_ml.__file__).parent


def ist(h: int, m: int = 0, day: int = 20) -> datetime:
    return datetime(2026, 10, day, h, m, tzinfo=IST)


@pytest.fixture()
def sessions(db_session, monkeypatch):
    @contextmanager
    def factory():
        yield db_session

    monkeypatch.setattr(alert_settings, "_default_sessions", lambda: factory)
    return factory


class Recorder:
    """Stands in for the Telegram network call. `answers` is consumed one per call (default: delivered)."""

    def __init__(self, answers: list[bool] | None = None) -> None:
        self.texts: list[str] = []
        self.answers = list(answers or [])

    async def __call__(self, text: str) -> bool:
        self.texts.append(text)
        return self.answers.pop(0) if self.answers else True


@pytest.fixture()
def notifier(monkeypatch):
    n = TelegramNotifier()
    monkeypatch.setattr(TelegramNotifier, "enabled", property(lambda self: True))
    n.recorder = Recorder()
    monkeypatch.setattr(n, "_post", n.recorder)
    return n


def person(db, username: str, role: str) -> dict:
    user = User(
        username=username,
        hashed_password="x",
        is_active=True,
        is_superuser=role == "owner",
        plan="pro",
        role=role,
    )
    db.add(user)
    db.flush()
    return {"Authorization": f"Bearer {create_access_token(user.username, {'uid': user.id})}"}


# =========================================================================== 1. preferences
def test_p1_defaults_when_nothing_is_stored_everything_on_nothing_held(client, db_session):
    """Baseline `5de3b9c`, `services/alert_settings.py:40-55` (`_prefs(None)`), `notifications/alert_policy.py:117`.
    Expected: no stored row means every switchable alert on, no quiet hours, no digest. (Also
    `test_alert_settings.py::test_owner_reads_defaults`.)"""
    assert db_session.scalar(select(AlertSettings.id).limit(1)) is None
    body = client.get(SETTINGS_URL, headers=KEY).json()
    assert body["disabled"] == [] and all(t["on"] for t in body["switchable"])
    assert (body["quiet_enabled"], body["digest_enabled"], body["held"]) == (False, False, 0)
    assert (body["quiet_start"], body["quiet_end"], body["digest_time"], body["timezone"]) == (
        "22:00",
        "07:00",
        "18:00",
        "IST",
    )


def test_p2_a_stored_row_with_empty_or_missing_values_mutes_nothing(db_session):
    """`alert_settings.py:40-55`. A row whose list is empty or NULL must not mute anything."""
    db_session.add(AlertSettings(scope="owner", disabled_kinds=None))
    db_session.flush()
    assert alert_settings.load(db_session).disabled == frozenset()


def test_p3_every_switchable_type_is_dropped_when_off_and_sent_when_on():
    """`alert_policy.py:168-176` (`route`), through the real list. (Also `test_alert_policy.py::test_each_informational_type_respects_on_off`.)"""
    for kind in policy.SWITCHABLE_KEYS:
        assert policy.route(kind, AlertPrefs(disabled=frozenset({kind})), ist(12)) == "drop"
        assert policy.route(kind, AlertPrefs(), ist(12)) == "send"
        other = next(k for k in policy.SWITCHABLE_KEYS if k != kind)
        assert policy.route(kind, AlertPrefs(disabled=frozenset({other})), ist(12)) == "send"


def test_p4_a_safety_type_can_never_be_switched_off_not_even_by_a_stored_value(client):
    """`alert_policy.py:87-120, 192-198`. Every always-on type is refused by the API (422) and ignored by the router
    even if a row naming it were stored by other means. (Also `test_alert_settings.py::test_bad_settings_are_refused_in_plain_words` for `sells`.)"""
    for always_on in policy.ALWAYS_ON:
        response = client.put(SETTINGS_URL, json={"disabled": [always_on.key]}, headers=KEY)
        assert response.status_code == 422, always_on.key
        assert policy.route(always_on.key, AlertPrefs(disabled=frozenset({always_on.key})), ist(23)) == "send"
        assert (
            policy.route(
                None, AlertPrefs(disabled=frozenset(policy.SWITCHABLE_KEYS), quiet_enabled=True), ist(23)
            )
            == "send"
        )


def _kind_arguments() -> list[tuple[str, int, str | None]]:
    """(file, line, kind) of every call in the app that passes `kind=`; kind is None when it is a variable."""
    names = {
        name: getattr(policy, name)
        for name in dir(policy)
        if name.isupper() and isinstance(getattr(policy, name), str)
    }
    found: list[tuple[str, int, str | None]] = []
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                called = (
                    node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else node.func.id
                    if isinstance(node.func, ast.Name)
                    else ""
                )
                if called not in {"send", "send_sync", "notify_daily_summary", "default_sender"}:
                    continue  # `kind=` is also an unrelated word elsewhere (a brain run's kind)
                for kw in node.keywords:
                    if kw.arg == "kind":
                        v = kw.value
                        label = (
                            v.attr
                            if isinstance(v, ast.Attribute)
                            else v.id
                            if isinstance(v, ast.Name)
                            else None
                        )
                        value = (
                            names.get(label) if label else (v.value if isinstance(v, ast.Constant) else None)
                        )
                        found.append((path.relative_to(SRC).as_posix(), node.lineno, value))
    return found


def test_p5_the_only_alerts_tagged_as_mutable_are_the_six_informational_types():
    """Every `kind=` in the app is one of the six switchable types, or a variable passed through by two helpers.
    A sell, a real-money order, a halt, a login problem or a system problem carries no kind, so it cannot be muted."""
    found = _kind_arguments()
    assert found, "the scan found no kind= at all: the test is broken"
    resolved = {(f, k) for f, _l, k in found if k is not None}
    assert {k for _f, k in resolved} <= policy.SWITCHABLE_KEYS, resolved
    passthrough = {f for f, _l, k in found if k is None}
    assert passthrough <= {
        "notifications/telegram.py",
        "brain/alerts/service.py",
        "api/v1/endpoints/notifications.py",
        "services/execution.py",  # `_buy_alert_kind(mode)` and one paper-only conditional: checked just below
    }, passthrough
    # and no call that is about a sell, a real order or a halt sits among the tagged files except where it is paper-only
    assert not any(f == "services/risk.py" for f, _k in resolved)


def test_p5b_a_buy_alert_is_mutable_only_when_it_is_paper_money():
    """`services/execution.py:1937-1939` (`_buy_alert_kind`): a paper buy may be switched off, a real-money buy never. (#250 b4.)"""
    from swing_trade_ml.services import execution

    assert execution._buy_alert_kind("paper") == policy.PAPER_BUYS
    assert execution._buy_alert_kind("live") is None


def test_p6_the_notifier_templates_for_signals_fills_exits_errors_and_system_messages_carry_no_kind(
    notifier, monkeypatch
):
    """`notifications/telegram.py:164-298`. These are the sell, fill, error and system messages: untagged, so always sent."""
    seen: list[str | None] = []

    async def capture(text, event="system", kind=None):
        seen.append(kind)
        return True

    monkeypatch.setattr(notifier, "send", capture)
    asyncio.run(notifier.notify_signal("ABC", "SELL", 100.0, 0.5, "r", "s", mode="live"))
    asyncio.run(notifier.notify_fill("ABC", "SELL", 1, 100.0, "o1", mode="live"))
    asyncio.run(notifier.notify_exit("ABC", 1, 100.0, 96.0, -4.0, -0.04, 3, "stop", mode="live"))
    asyncio.run(notifier.notify_error("job", "boom"))
    asyncio.run(notifier.notify_system("hello"))
    assert seen == [None] * 5


def test_p7_quiet_hours_hold_an_informational_alert_but_never_a_stop_loss_and_the_flush_sends_once(
    notifier, sessions, db_session, monkeypatch
):
    """End to end through the real notifier, gate and outbox (`telegram.py:52-83`, `alert_settings.py:134-211`).
    At 23:00 IST with quiet hours on: a trade-idea message is held, a stop-loss message (no kind) is sent; at 07:01 the held one
    goes out once, as one message, and is not sent again."""
    alert_settings.save(db_session, AlertPrefs(quiet_enabled=True), by="251 test")
    original = alert_settings.gate
    monkeypatch.setattr(
        alert_settings, "gate", lambda kind, text: original(kind, text, now=ist(23), sessions=sessions)
    )

    assert (
        asyncio.run(notifier.send("idea for ABC", "signal", kind=policy.TRADE_IDEAS)) is True
    )  # held counts as delivered
    assert asyncio.run(notifier.send("STOP-LOSS hit ABC", "signal")) is True
    assert notifier.recorder.texts == ["STOP-LOSS hit ABC"]
    assert [r.text for r in db_session.scalars(select(AlertOutbox).where(AlertOutbox.sent_at.is_(None)))] == [
        "idea for ABC"
    ]

    delivered: list[str] = []
    out = alert_settings.flush(db_session, ist(7, 1, day=21), lambda text: delivered.append(text) or True)
    assert out["sent"] == 1 and len(delivered) == 1 and "idea for ABC" in delivered[0]
    again = alert_settings.flush(db_session, ist(7, 2, day=21), lambda text: delivered.append(text) or True)
    assert again["sent"] == 0 and len(delivered) == 1


def test_p8_saving_the_settings_is_recorded_in_the_audit_log_with_who_changed_it(client, db_session):
    """`api/v1/endpoints/notifications.py:87-102`. A change is an audit row naming the actor."""
    owner = person(db_session, "251-owner-a", "owner")
    before = db_session.scalar(select(AuditLog.id).where(AuditLog.action == "alerts.settings").limit(1))
    assert before is None
    assert client.put(SETTINGS_URL, json={"disabled": ["paper_buys"]}, headers=owner).status_code == 200
    rows = db_session.scalars(select(AuditLog).where(AuditLog.action == "alerts.settings")).all()
    assert len(rows) == 1 and rows[0].actor_label == "251-owner-a"


def test_p9_the_screen_gets_every_type_in_plain_words_and_the_always_on_ones_have_no_switch(client):
    """`services/alert_settings.py:104-125` (`as_dict`) is what the Alerts screen renders
    (`frontend/src/trademind/pages/Alerts.tsx`, tested in `alerts.test.tsx`: 'shows the safety messages as always on, with
    the reason, and no switch'). Here: the data the screen is given."""
    body = client.get(SETTINGS_URL, headers=KEY).json()
    assert [t["key"] for t in body["always_on"]] == [
        "sells",
        "real_orders",
        "risk_halts",
        "login_problems",
        "system_problems",
    ]
    assert all(t["on"] is True and t["explain"].strip() for t in body["always_on"])
    for t in [*body["always_on"], *body["switchable"]]:
        assert (
            "_" not in t["label"] and t["label"].strip() and t["explain"].strip()
        )  # words, no internal codes
    assert {t["key"] for t in body["switchable"]}.isdisjoint({t["key"] for t in body["always_on"]})


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="GAP (#251): alert settings are one shared row (scope 'owner', db/models/alerts.py:25-31), not per user: every owner "
    "account and the shared key read and overwrite the same settings. The model comment says a per-user scope is planned (tracker mu6).",
)
def test_gap_two_owner_accounts_have_independent_alert_settings(client, db_session):
    first = person(db_session, "251-owner-a", "owner")
    second = person(db_session, "251-owner-b", "owner")
    assert client.put(SETTINGS_URL, json={"disabled": ["paper_buys"]}, headers=first).status_code == 200
    assert client.get(SETTINGS_URL, headers=second).json()["disabled"] == []


def test_p10_only_an_owner_reads_or_changes_the_settings_a_member_a_tester_and_a_stranger_cannot(
    client, db_session
):
    """`notifications.py:69` (`require_owner`). (Also `test_alert_settings.py::test_non_owner_cannot_read_or_change_alert_settings`.)"""
    for role in ("member", "tester"):
        who = person(db_session, f"251-{role}", role)
        assert client.get(SETTINGS_URL, headers=who).status_code == 403
        assert client.put(SETTINGS_URL, json={"disabled": ["paper_buys"]}, headers=who).status_code == 403
    assert client.get(SETTINGS_URL).status_code == 401
    assert (
        db_session.scalar(select(AlertSettings.id).limit(1)) is None
    )  # nothing was stored by the refused calls


# =========================================================================== 2. delivery failures
def test_f1_a_refused_direct_send_returns_false_and_leaves_only_a_log_line(notifier, monkeypatch, caplog):
    """`telegram.py:85-107` (`_post`): any non-200 or exception returns False with a `telegram.send_failed` log. (#250 e1.)
    Uses a stubbed HTTP client: no network."""
    monkeypatch.undo()  # drop the recorder from the fixture: this test drives the real _post against a fake HTTP client
    calls: list[str] = []

    class FakeClient:
        def __init__(self, *a, **k) -> None: ...
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            calls.append("x")
            return httpx.Response(500, text="oops")

    monkeypatch.setattr(telegram_module.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(telegram_module.settings, "TELEGRAM_ENABLED", True)
    n = TelegramNotifier()
    n._token, n._chat_id = "000000:PLACEHOLDER", "0"
    monkeypatch.setattr(TelegramNotifier, "enabled", property(lambda self: True))
    assert asyncio.run(n.send("stop-loss", "signal")) is False
    assert calls == ["x"]


def test_gap_a_refused_direct_send_is_retried_or_recorded(monkeypatch):
    """Closed by #358: a refused urgent alert is recorded and two retries are scheduled (30 s, 2 min)."""
    calls: list[int] = []
    scheduled: list = []

    class FakeClient:
        def __init__(self, *a, **k) -> None: ...
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            calls.append(429)
            return httpx.Response(429, text="slow down")

    async def no_wait(_seconds):
        return None

    monkeypatch.setattr(telegram_module.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(telegram_module, "_spawn", scheduled.append)
    monkeypatch.setattr(telegram_module, "_sleep", no_wait)
    monkeypatch.setattr(TelegramNotifier, "enabled", property(lambda self: True))
    n = TelegramNotifier()
    n._token, n._chat_id = "000000:PLACEHOLDER", "0"
    assert asyncio.run(n.send("real-money order refused", "error")) is False
    assert len(scheduled) == 1, "the refused message was not scheduled for a retry"
    asyncio.run(scheduled[0]())
    assert len(calls) == 3  # first attempt plus the two retries


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="GAP (#251): TELEGRAM_NOTIFY_ON (a server setting) filters by event before any safety rule: leaving 'signal' out silently "
    "drops stop-loss alerts (they use the 'signal' event). Not a user preference, but the 'can't be muted' promise does not cover it.",
)
def test_gap_a_stop_loss_alert_is_sent_whatever_the_event_filter_says(monkeypatch):
    n = TelegramNotifier()
    n.recorder = Recorder()
    monkeypatch.setattr(n, "_post", n.recorder)
    monkeypatch.setattr(TelegramNotifier, "enabled", property(lambda self: True))
    monkeypatch.setattr(
        settings, "TELEGRAM_NOTIFY_ON", "daily_summary"
    )  # an operator left the safety events out
    asyncio.run(n.send("STOP-LOSS hit ABC", "signal"))
    assert n.recorder.texts == ["STOP-LOSS hit ABC"]


def test_f2_the_default_event_filter_lets_every_event_the_app_uses_through():
    """`core/config.py:357` default `signal,order,fill,error,daily_summary,system` covers every NotificationEvent."""
    from swing_trade_ml.core.enums import NotificationEvent

    assert {e.value for e in NotificationEvent} <= settings.telegram_events


def test_f3_a_failed_delivery_of_held_alerts_keeps_the_rest_held_and_a_partial_run_marks_only_what_arrived(
    db_session,
):
    """`alert_settings.py:196-211`: a message is marked sent only after Telegram took it. First text delivered, second
    refused: the first is marked sent, the second stays held for the next run. (Also `test_alert_settings.py::test_failed_delivery_keeps_the_message_held`.)"""
    day = ist(1)
    for n in range(2):
        db_session.add(
            AlertOutbox(
                scope="owner", kind=policy.TRADE_IDEAS, text=f"idea {n} " + "x" * 3000, created_at=day
            )
        )
    db_session.flush()
    answers = iter([True, False])
    out = alert_settings.flush(db_session, ist(8), lambda text: next(answers))
    sent = db_session.scalars(select(AlertOutbox).where(AlertOutbox.sent_at.is_not(None))).all()
    held = db_session.scalars(select(AlertOutbox).where(AlertOutbox.sent_at.is_(None))).all()
    assert out["sent"] == 1 and len(sent) == 1 and len(held) == 1
    retry = alert_settings.flush(db_session, ist(8, 5), lambda text: True)
    assert (
        retry["sent"] == 1
        and not db_session.scalars(select(AlertOutbox).where(AlertOutbox.sent_at.is_(None))).all()
    )


def test_f4_an_unreadable_settings_table_never_silences_an_alert(db_session):
    """`alert_settings.py:134-159`: any failure answers 'send'. (Also `test_alert_settings.py::test_settings_read_failure_sends`.)"""

    @contextmanager
    def broken():
        raise ConnectionError("database is down")
        yield  # pragma: no cover

    assert alert_settings.gate(policy.TRADE_IDEAS, "x", now=datetime.now(UTC), sessions=broken) == "send"


def test_f5_a_muted_message_is_not_a_failed_one_the_notifier_says_so_without_posting(notifier, monkeypatch):
    """`telegram.py:52-83`: a switched-off type returns False (nothing posted); held returns True. A caller that records
    'told' only on True (the brain alerts) therefore re-checks a muted message on the next run, which is harmless."""
    monkeypatch.setattr(alert_settings, "gate", lambda kind, text: "drop")
    assert asyncio.run(notifier.send("idea", "signal", kind=policy.TRADE_IDEAS)) is False
    assert notifier.recorder.texts == []


@pytest.fixture()
def failing_email():
    class Failing(LogEmailSender):
        def send(self, to, subject, text, html=None) -> bool:
            self.outbox.append(None)  # type: ignore[arg-type]
            return False

    sender = Failing()
    set_sender_for_tests(sender)
    yield sender
    set_sender_for_tests(None)


def _register(client, email: str):
    return client.post(
        f"{API}/auth/register",
        json={"full_name": "Test Person", "email": email, "password": "correct horse battery staple"},
    )


def test_f6_a_failed_email_does_not_change_the_public_answer_and_never_raises(
    client, failing_email, monkeypatch
):
    """`api/v1/endpoints/account_auth.py:101-103` (`_send` ignores the result) and `services/email/senders.py:50-68`.
    Registration answers the same 201 whether the mail went or not (no way to tell an address exists), and a failed send
    cannot break the request."""
    monkeypatch.setattr(settings, "ALLOW_SIGNUP", True)
    monkeypatch.setattr(settings, "REQUIRE_EMAIL_VERIFICATION", False)
    response = _register(client, "251-new@example.com")
    assert response.status_code == 201
    assert len(failing_email.outbox) == 1  # one attempt was made


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="GAP (#251): a verification or reset email that could not be sent leaves only a log line (senders.py:50-68, "
    "account_auth.py:101-103); nothing the owner can see. The person can ask for a resend, the owner is not told.",
)
def test_gap_a_failed_email_is_recorded_where_the_owner_can_see_it(
    client, failing_email, db_session, monkeypatch
):
    monkeypatch.setattr(settings, "ALLOW_SIGNUP", True)
    monkeypatch.setattr(settings, "REQUIRE_EMAIL_VERIFICATION", False)
    assert _register(client, "251-new2@example.com").status_code == 201
    actions = list(db_session.scalars(select(AuditLog.action)))
    assert any("email" in a for a in actions), "no audit row or other record names the failed email"


def test_f7_there_is_no_delivery_dedupe_at_the_notifier_so_repeats_are_stopped_at_the_source(notifier):
    """Documents the design: the notifier posts every message it is given (`telegram.py:52-107`). Duplicates are prevented
    where the alert is born: the per-position flags (#250 a1/a4), the brain's one-per-day key (`test_brain_alerts_service.py`)
    and the email notice throttle (`test_account_auth_email.py::test_register_notice_is_limited_to_one_per_hour_per_address`)."""
    asyncio.run(notifier.send("same text", "signal"))
    asyncio.run(notifier.send("same text", "signal"))
    assert notifier.recorder.texts == ["same text", "same text"]
