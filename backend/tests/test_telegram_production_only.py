"""Telegram messages come from production only.

A laptop with the real bot token in its .env must stay silent; production (ENVIRONMENT=production)
sends as before. `TELEGRAM_SEND_OUTSIDE_PRODUCTION` is the one deliberate way to test locally.
"""

from __future__ import annotations

import pytest

from swing_trade_ml.core.config import settings
from swing_trade_ml.notifications.telegram import TelegramNotifier


@pytest.fixture
def configured(monkeypatch):
    """Telegram fully set up, as in the owner's real .env."""
    monkeypatch.setattr(settings, "TELEGRAM_ENABLED", True)
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "12345")
    monkeypatch.setattr(settings, "TELEGRAM_SEND_OUTSIDE_PRODUCTION", False)
    return TelegramNotifier()


@pytest.mark.parametrize("env", ["local", "staging"])
def test_silent_outside_production(configured, monkeypatch, env):
    monkeypatch.setattr(settings, "ENVIRONMENT", env)
    assert configured.enabled is False
    assert configured._should_send("daily_summary") is False
    assert configured.deliver_sync("held digest") is False


def test_sends_in_production(configured, monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    assert configured.enabled is True
    assert configured._should_send("daily_summary") is True


def test_deliberate_local_test_switch(configured, monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "local")
    monkeypatch.setattr(settings, "TELEGRAM_SEND_OUTSIDE_PRODUCTION", True)
    assert configured.enabled is True


def test_production_still_needs_the_token(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "TELEGRAM_ENABLED", True)
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "12345")
    assert TelegramNotifier().enabled is False


async def test_local_daily_summary_posts_nothing(configured, monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "local")
    posted: list[str] = []

    async def fake_post(self, text):
        posted.append(text)
        return True

    monkeypatch.setattr(TelegramNotifier, "_post", fake_post)
    sent = await configured.notify_daily_summary({"total_value": 1.0}, kind=None)
    assert sent is False
    assert posted == []
