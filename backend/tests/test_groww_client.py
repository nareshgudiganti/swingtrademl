"""Groww client: read-only, token + holdings only, token never logged."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import httpx
import pyotp
import pytest

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.market_session import IST
from swing_trade_ml.services.groww import client

FAKE_TOKEN = "FAKE-ACCESS-TOKEN-abc123"
SECRET = pyotp.random_base32()


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key] = value
        self.ttls[key] = ex

    def setex(self, key, ttl, value):
        self.store[key] = value
        self.ttls[key] = ttl


@pytest.fixture
def fake_redis(monkeypatch):
    r = FakeRedis()
    monkeypatch.setattr(client, "_get_redis", lambda: r)
    monkeypatch.setattr(settings, "GROWW_TOTP_TOKEN", "api-key-xyz")
    monkeypatch.setattr(settings, "GROWW_TOTP_SECRET", SECRET)
    return r


def _install(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(client, "_transport", lambda: transport)


def test_only_allowed_paths_requested(monkeypatch, fake_redis):
    seen = []

    def handler(request):
        seen.append(request.url.path)
        if request.url.path == "/v1/token/api/access":
            return httpx.Response(200, json={"token": FAKE_TOKEN})
        return httpx.Response(200, json={"status": "SUCCESS", "payload": {"holdings": [{"isin": "X"}]}})

    _install(monkeypatch, handler)
    assert client.fetch_holdings() == [{"isin": "X"}]
    assert seen and set(seen) <= client.ALLOWED_PATHS


def test_module_has_no_order_surface():
    assert [
        n for n in dir(client) if any(w in n.lower() for w in ("order", "place", "cancel", "modify"))
    ] == []


def test_401_mints_once_then_raises_auth_error(monkeypatch, fake_redis):
    calls = {"token": 0, "holdings": 0}

    def handler(request):
        if request.url.path == "/v1/token/api/access":
            calls["token"] += 1
            return httpx.Response(200, json={"token": FAKE_TOKEN})
        calls["holdings"] += 1
        return httpx.Response(401, json={"status": "FAILURE"})

    _install(monkeypatch, handler)
    with pytest.raises(client.GrowwAuthError):
        client.fetch_holdings()
    assert calls == {"token": 2, "holdings": 2}


def test_token_cached_until_6am_ist(monkeypatch, fake_redis):
    n = {"token": 0}

    def handler(request):
        n["token"] += 1
        return httpx.Response(200, json={"token": FAKE_TOKEN})

    _install(monkeypatch, handler)
    assert client.get_access_token() == FAKE_TOKEN
    assert client.get_access_token() == FAKE_TOKEN
    assert n["token"] == 1
    now = datetime.now(IST)
    target = now.replace(hour=6, minute=0, second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    expected = (target - now).total_seconds()
    assert abs(fake_redis.ttls["groww:access_token"] - expected) < 5


def test_logs_never_contain_token(monkeypatch, fake_redis, caplog):
    def handler(request):
        if request.url.path == "/v1/token/api/access":
            return httpx.Response(200, json={"token": FAKE_TOKEN})
        return httpx.Response(200, json={"status": "SUCCESS", "payload": {"holdings": []}})

    _install(monkeypatch, handler)
    with caplog.at_level(logging.DEBUG):
        client.fetch_holdings()
    assert FAKE_TOKEN not in caplog.text
    assert "api-key-xyz" not in caplog.text
