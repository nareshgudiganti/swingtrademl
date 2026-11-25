"""Urgent Telegram alerts that fail are recorded and retried (#358, audit row 48 of #217).

Owner criteria (2026-11-15): after a temporary failure, two retries at about 30 s and about 2 min,
then one warning; a permanent failure (bad token, blocked chat) is surfaced at once, no retries;
a success on a retry is silent; the token is never logged. No real HTTP and no real waiting.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from swing_trade_ml.core.config import settings
from swing_trade_ml.notifications import failure_log
from swing_trade_ml.notifications import telegram as tg
from swing_trade_ml.notifications.telegram import TelegramNotifier

TOKEN = "123456:SECRET-TOKEN-VALUE"


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "MODEL_ARTIFACT_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "TELEGRAM_ENABLED", True)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")


def _notifier(monkeypatch, responses):
    """A notifier whose HTTP calls return `responses` in order (a number = status, an Exception = raised)."""
    calls: list[str] = []
    queue = list(responses)

    class FakeClient:
        def __init__(self, *a, **k) -> None: ...
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            calls.append(url)
            nxt = queue.pop(0) if queue else 200
            if isinstance(nxt, Exception):
                raise nxt
            return httpx.Response(nxt, text="x")

    monkeypatch.setattr(tg.httpx, "AsyncClient", FakeClient)
    n = TelegramNotifier()
    n._token, n._chat_id = TOKEN, "42"
    monkeypatch.setattr(TelegramNotifier, "enabled", property(lambda self: True))
    return n, calls


@pytest.fixture
def spawned(monkeypatch):
    jobs: list = []
    monkeypatch.setattr(tg, "_spawn", lambda make: jobs.append(make))
    return jobs


def _run_retries(spawned, monkeypatch):
    slept: list[float] = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(tg, "_sleep", fake_sleep)
    for make in spawned:
        asyncio.run(make())
    return slept


def test_transient_failure_retries_at_30s_and_2min_then_one_warning(monkeypatch, spawned, caplog):
    n, calls = _notifier(monkeypatch, [500, 503, 502])
    assert asyncio.run(n.send("stop-loss hit", "signal")) is False
    assert len(calls) == 1 and len(spawned) == 1  # first attempt now, retries scheduled not blocking
    assert failure_log.needing_attention() == []  # still retrying: not yet a warning

    slept = _run_retries(spawned, monkeypatch)

    assert slept == [30.0, 90.0]  # absolute offsets 30 s and 120 s after the first attempt
    assert len(calls) == 3
    (entry,) = failure_log.needing_attention()
    assert entry["state"] == failure_log.GAVE_UP and entry["attempts"] == 3 and entry["status"] == 502


def test_gave_up_logs_exactly_one_warning(monkeypatch, spawned):
    from structlog.testing import capture_logs

    n, _ = _notifier(monkeypatch, [500, 500, 500])
    with capture_logs() as logs:
        asyncio.run(n.send("order refused", "error"))
        _run_retries(spawned, monkeypatch)
    warnings = [entry for entry in logs if entry["log_level"] == "warning"]
    assert [w["event"] for w in warnings] == ["telegram.alert_not_delivered"]


def test_success_on_retry_is_silent(monkeypatch, spawned):
    from structlog.testing import capture_logs

    n, calls = _notifier(monkeypatch, [500, 200])
    with capture_logs() as logs:
        assert asyncio.run(n.send("stop-loss hit", "signal")) is False
        slept = _run_retries(spawned, monkeypatch)
    assert slept == [30.0] and len(calls) == 2  # no third attempt
    assert failure_log.recent() == []
    assert not [entry for entry in logs if entry["log_level"] in ("warning", "critical")]


@pytest.mark.parametrize("code", [401, 403, 400])
def test_permanent_failure_is_not_retried_and_surfaced_at_once(monkeypatch, spawned, code):
    n, calls = _notifier(monkeypatch, [code])
    assert asyncio.run(n.send("stop-loss hit", "signal")) is False
    assert spawned == []  # nothing scheduled
    assert len(calls) == 1
    (entry,) = failure_log.needing_attention()
    assert entry["state"] == failure_log.PERMANENT and entry["status"] == code


def test_permanent_refusal_during_a_retry_stops_there(monkeypatch, spawned):
    n, calls = _notifier(monkeypatch, [500, 403])
    asyncio.run(n.send("stop-loss hit", "signal"))
    slept = _run_retries(spawned, monkeypatch)
    assert slept == [30.0] and len(calls) == 2
    assert failure_log.needing_attention()[0]["state"] == failure_log.PERMANENT


def test_network_error_counts_as_transient(monkeypatch, spawned):
    n, _ = _notifier(monkeypatch, [httpx.ConnectError("boom " + TOKEN)])
    asyncio.run(n.send("stop-loss hit", "signal"))
    assert len(spawned) == 1


def test_informational_alerts_with_a_kind_are_not_retried_or_recorded(monkeypatch, spawned):
    from swing_trade_ml.services import alert_settings

    monkeypatch.setattr(alert_settings, "gate", lambda kind, text: "send")
    n, calls = _notifier(monkeypatch, [500])
    assert asyncio.run(n.send("daily summary", "daily_summary", kind="daily_summary")) is False
    assert spawned == [] and len(calls) == 1 and failure_log.recent() == []


def test_token_and_message_text_never_reach_the_log_or_the_record(monkeypatch, spawned, tmp_path):
    from structlog.testing import capture_logs

    n, _ = _notifier(monkeypatch, [httpx.ConnectError("boom " + TOKEN), 500, 500])
    with capture_logs() as logs:
        asyncio.run(n.send("my private message text", "signal"))
        _run_retries(spawned, monkeypatch)
    blob = repr(logs) + (tmp_path / ".telegram_failures.json").read_text()
    assert "SECRET-TOKEN-VALUE" not in blob
    assert "my private message text" not in blob


def test_ops_digest_lists_undelivered_alerts(monkeypatch):
    from swing_trade_ml.services import ops_digest

    failure_log.record(failure_log.GAVE_UP, event="signal", status=500, reason="HTTP 500", attempts=3)
    section = ops_digest._telegram_section()
    assert section["undelivered_alerts"] and "error" not in section
    assert any("Telegram" in line for line in ops_digest._telegram_attention(section))
