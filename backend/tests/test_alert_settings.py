"""Alert settings (tracker ux3): stored settings, the notifier gate, held messages and
the owner-only API. Telegram is never really called: the notifier's network send
(`_post`) is replaced in every test that switches it on."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.alerts import AlertOutbox, AlertSettings
from swing_trade_ml.db.models.session import User
from swing_trade_ml.notifications import alert_policy as policy
from swing_trade_ml.notifications.alert_policy import AlertPrefs
from swing_trade_ml.notifications.telegram import TelegramNotifier
from swing_trade_ml.services import alert_settings

IST = ZoneInfo("Asia/Kolkata")
API_KEY = {"X-API-Key": "test-api-key"}
URL = "/api/v1/notifications/alert-settings"


def ist(h: int, m: int = 0, day: int = 20) -> datetime:
    return datetime(2026, 10, day, h, m, tzinfo=IST)


@pytest.fixture()
def sessions(db_session):
    @contextmanager
    def factory():
        yield db_session

    return factory


def _broken_sessions():
    @contextmanager
    def factory():
        raise ConnectionError("database is down")
        yield  # pragma: no cover

    return factory


def _held(db_session) -> list[AlertOutbox]:
    return list(db_session.execute(select(AlertOutbox).where(AlertOutbox.sent_at.is_(None))).scalars())


# ------------------------------------------------------------------ gate --


def test_safety_alert_never_reads_settings_even_when_the_database_is_down():
    for kind in (None, "sells", "real_orders", "risk_halts", "system_problems", "typo"):
        assert alert_settings.gate(kind, "x", sessions=_broken_sessions()) == "send"


def test_settings_read_failure_sends():
    assert alert_settings.gate("trade_ideas", "x", sessions=_broken_sessions()) == "send"


def test_bad_stored_value_sends(db_session, sessions):
    db_session.add(AlertSettings(scope="owner", disabled_kinds=["trade_ideas"], quiet_start="99:99"))
    db_session.commit()
    assert alert_settings.gate("trade_ideas", "x", sessions=sessions) == "send"


def test_no_stored_settings_sends(sessions):
    assert alert_settings.gate("trade_ideas", "x", now=ist(23), sessions=sessions) == "send"


@pytest.mark.parametrize("kind", sorted(policy.SWITCHABLE_KEYS))
def test_switched_off_type_is_dropped_and_not_held(db_session, sessions, kind):
    alert_settings.save(db_session, AlertPrefs(disabled=frozenset({kind})), by="t")
    assert alert_settings.gate(kind, "x", sessions=sessions) == "drop"
    assert _held(db_session) == []


def test_quiet_hours_hold_the_message(db_session, sessions):
    alert_settings.save(
        db_session, AlertPrefs(quiet_enabled=True, quiet_start=time(22), quiet_end=time(7)), by="t"
    )
    assert alert_settings.gate("trade_ideas", "idea at night", now=ist(23), sessions=sessions) == "held"
    assert alert_settings.gate("trade_ideas", "idea at noon", now=ist(12), sessions=sessions) == "send"
    assert [r.text for r in _held(db_session)] == ["idea at night"]


# -------------------------------------------------------------- notifier --


class _Recorder:
    def __init__(self):
        self.texts: list[str] = []

    async def __call__(self, text: str) -> bool:
        self.texts.append(text)
        return True


@pytest.fixture()
def notifier(monkeypatch):
    n = TelegramNotifier()
    monkeypatch.setattr(TelegramNotifier, "enabled", property(lambda self: True))
    recorder = _Recorder()
    monkeypatch.setattr(n, "_post", recorder)
    n.posted = recorder.texts
    return n


def test_notifier_sends_safety_alerts_whatever_the_settings(notifier, monkeypatch):
    def gate_must_not_run(*a, **k):
        raise AssertionError("a safety alert must not consult the settings")

    monkeypatch.setattr(alert_settings, "gate", gate_must_not_run)
    assert asyncio.run(notifier.send("🛑 stop-loss hit", "signal")) is True
    assert notifier.posted == ["🛑 stop-loss hit"]


def test_notifier_respects_a_switched_off_type(notifier, monkeypatch):
    monkeypatch.setattr(alert_settings, "gate", lambda kind, text: "drop")
    assert asyncio.run(notifier.send("idea", "signal", kind="trade_ideas")) is False
    assert notifier.posted == []


def test_notifier_held_message_counts_as_delivered(notifier, monkeypatch):
    monkeypatch.setattr(alert_settings, "gate", lambda kind, text: "held")
    assert asyncio.run(notifier.send("idea", "signal", kind="trade_ideas")) is True
    assert notifier.posted == []


def test_notifier_sends_when_settings_cannot_be_read(notifier, monkeypatch):
    real_gate = alert_settings.gate

    def broken(kind, text):
        return real_gate(kind, text, sessions=_broken_sessions())

    monkeypatch.setattr(alert_settings, "gate", broken)
    assert asyncio.run(notifier.send("idea", "signal", kind="trade_ideas")) is True
    assert notifier.posted == ["idea"]


def test_send_sync_passes_the_kind(notifier, monkeypatch):
    seen = []
    monkeypatch.setattr(alert_settings, "gate", lambda kind, text: seen.append(kind) or "send")
    notifier.send_sync("summary", "daily_summary", kind="daily_summary")
    assert seen == ["daily_summary"]


def test_telegram_switched_off_sends_and_holds_nothing(monkeypatch):
    n = TelegramNotifier()
    monkeypatch.setattr(TelegramNotifier, "enabled", property(lambda self: False))
    monkeypatch.setattr(alert_settings, "gate", lambda *a, **k: pytest.fail("no gate while Telegram is off"))
    assert asyncio.run(n.send("x", "signal", kind="trade_ideas")) is False
    assert n.deliver_sync("x") is False


# ----------------------------------------------------------------- flush --


class _Deliver:
    def __init__(self, ok: bool = True):
        self.ok = ok
        self.texts: list[str] = []

    def __call__(self, text: str) -> bool:
        self.texts.append(text)
        return self.ok


def _hold(db_session, text: str, at: datetime, kind: str = "trade_ideas") -> None:
    db_session.add(AlertOutbox(scope="owner", kind=kind, text=text, created_at=at))
    db_session.commit()


def test_quiet_hours_messages_go_out_together_when_quiet_hours_end(db_session):
    alert_settings.save(
        db_session, AlertPrefs(quiet_enabled=True, quiet_start=time(22), quiet_end=time(7)), by="t"
    )
    _hold(db_session, "one", ist(22, 30, day=19))
    _hold(db_session, "two", ist(23, 10, day=19), kind="daily_summary")
    deliver = _Deliver()
    assert alert_settings.flush(db_session, ist(6, 55), deliver)["sent"] == 0
    assert deliver.texts == []
    assert alert_settings.flush(db_session, ist(7, 0), deliver)["sent"] == 2
    assert len(deliver.texts) == 1 and "one" in deliver.texts[0] and "two" in deliver.texts[0]
    # Sent once, never again.
    assert alert_settings.flush(db_session, ist(7, 5), deliver)["sent"] == 0
    assert len(deliver.texts) == 1


def test_digest_collects_and_sends_once_a_day(db_session):
    alert_settings.save(db_session, AlertPrefs(digest_enabled=True, digest_time=time(18)), by="t")
    for i, h in enumerate((9, 11, 15)):
        _hold(db_session, f"msg{i}", ist(h))
    deliver = _Deliver()
    alert_settings.flush(db_session, ist(17, 55), deliver)
    assert deliver.texts == []
    assert alert_settings.flush(db_session, ist(18, 0), deliver)["sent"] == 3
    assert len(deliver.texts) == 1
    assert all(f"msg{i}" in deliver.texts[0] for i in range(3))
    assert alert_settings.load(db_session).last_digest_on == ist(18).date()
    # Something new after today's digest waits for tomorrow's.
    _hold(db_session, "late", ist(19))
    assert alert_settings.flush(db_session, ist(20), deliver)["sent"] == 0
    assert alert_settings.flush(db_session, ist(18, day=21), deliver)["sent"] == 1
    assert len(deliver.texts) == 2


def test_failed_delivery_keeps_the_message_held(db_session):
    _hold(db_session, "keep me", ist(9))
    assert alert_settings.flush(db_session, ist(12), _Deliver(ok=False))["sent"] == 0
    assert [r.text for r in _held(db_session)] == ["keep me"]
    assert alert_settings.flush(db_session, ist(12, 5), _Deliver())["sent"] == 1
    assert _held(db_session) == []


def test_type_switched_off_after_it_was_held_is_not_sent(db_session):
    _hold(db_session, "old idea", ist(9))
    alert_settings.save(db_session, AlertPrefs(disabled=frozenset({"trade_ideas"})), by="t")
    deliver = _Deliver()
    assert alert_settings.flush(db_session, ist(12), deliver) == {"sent": 0, "held": 0, "dropped": 1}
    assert deliver.texts == []


def test_unreadable_settings_release_held_messages(db_session):
    db_session.add(AlertSettings(scope="owner", digest_enabled=True, digest_time="bad"))
    db_session.commit()
    _hold(db_session, "x", ist(9))
    deliver = _Deliver()
    assert alert_settings.flush(db_session, ist(10), deliver)["sent"] == 1


def test_old_sent_rows_are_cleaned_up(db_session):
    db_session.add(
        AlertOutbox(
            scope="owner",
            kind="trade_ideas",
            text="old",
            created_at=ist(9),
            sent_at=ist(9) - timedelta(days=40),
        )
    )
    db_session.commit()
    alert_settings.flush(db_session, ist(9), _Deliver())
    assert db_session.execute(select(AlertOutbox)).scalars().all() == []


def test_flush_job_skips_quietly_while_telegram_is_off(monkeypatch):
    from swing_trade_ml.workers import jobs

    monkeypatch.setattr(TelegramNotifier, "enabled", property(lambda self: False))
    monkeypatch.setattr(alert_settings, "flush", lambda *a, **k: pytest.fail("must not run"))
    jobs.job_flush_alerts()


def test_flush_job_never_raises(monkeypatch):
    from swing_trade_ml.workers import jobs

    monkeypatch.setattr(TelegramNotifier, "enabled", property(lambda self: True))

    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(alert_settings, "flush", boom)
    monkeypatch.setattr(jobs.notifier, "send_sync", lambda *a, **k: pytest.fail("no Telegram about it"))
    jobs.job_flush_alerts()


# -------------------------------------------------- brain message kinds --


def test_brain_message_of_only_new_ideas_is_switchable_anything_else_is_not():
    from swing_trade_ml.brain.alerts.detectors import AlertItem
    from swing_trade_ml.brain.alerts.service import alert_kind

    idea = AlertItem("trade:A", "trade", "A", "buy A", 1)
    holding = AlertItem("holding:B:EXIT", "holding", "B", "sell B", 0)
    banner = AlertItem("banner:NO_NEW_TRADES", "banner", None, "no new trades", 0)
    assert alert_kind([idea]) == "trade_ideas"
    assert alert_kind([idea, holding]) is None
    assert alert_kind([banner, idea]) is None


def test_paper_buys_switchable_real_buys_never():
    from swing_trade_ml.services.execution import _buy_alert_kind

    assert _buy_alert_kind("paper") == "paper_buys"
    assert _buy_alert_kind("live") is None


# ------------------------------------------------------------------- API --


def _login(db_session, username: str, role: str) -> dict[str, str]:
    user = User(
        username=username,
        hashed_password="x",
        is_active=True,
        is_superuser=role == "owner",
        plan="free",
        role=role,
    )
    db_session.add(user)
    db_session.flush()
    return {"Authorization": f"Bearer {create_access_token(user.username, {'uid': user.id})}"}


def test_owner_reads_defaults(client):
    r = client.get(URL, headers=API_KEY)
    assert r.status_code == 200
    body = r.json()
    assert [t["key"] for t in body["switchable"]] == [t.key for t in policy.SWITCHABLE]
    assert all(t["on"] for t in body["switchable"])
    assert {t["key"] for t in body["always_on"]} >= {
        "sells",
        "real_orders",
        "risk_halts",
        "login_problems",
        "system_problems",
    }
    assert body["quiet_enabled"] is False and body["digest_enabled"] is False and body["held"] == 0


def test_owner_saves_and_the_setting_is_respected(client, db_session, sessions):
    body = {
        "disabled": ["paper_buys"],
        "quiet_enabled": True,
        "quiet_start": "22:00",
        "quiet_end": "07:00",
        "digest_enabled": False,
        "digest_time": "18:00",
    }
    owner = _login(db_session, "alerts-owner", "owner")
    r = client.put(URL, json=body, headers=owner)
    assert r.status_code == 200, r.text
    assert {t["key"]: t["on"] for t in r.json()["switchable"]}["paper_buys"] is False
    assert alert_settings.gate("paper_buys", "x", now=ist(12), sessions=sessions) == "drop"
    assert alert_settings.gate("trade_ideas", "x", now=ist(23), sessions=sessions) == "held"
    assert client.get(URL, headers=owner).json()["disabled"] == ["paper_buys"]


@pytest.mark.parametrize(
    "body",
    [
        {"disabled": ["sells"]},
        {"quiet_start": "25:00"},
        {
            "quiet_enabled": True,
            "quiet_start": "22:00",
            "quiet_end": "07:00",
            "digest_enabled": True,
            "digest_time": "23:00",
        },
    ],
)
def test_bad_settings_are_refused_in_plain_words(client, body):
    r = client.put(URL, json=body, headers=API_KEY)
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], str)


@pytest.mark.parametrize("role", ["tester", "member"])
def test_non_owner_cannot_read_or_change_alert_settings(client, db_session, role):
    who = _login(db_session, f"alerts-{role}", role)
    assert client.get(URL, headers=who).status_code == 403
    assert client.put(URL, json={}, headers=who).status_code == 403


def test_signed_out_is_refused(client):
    assert client.get(URL).status_code == 401
