"""Per-IP request limits on sign-in and public endpoints (tracker qa7)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from swing_trade_ml.api import rate_limit
from swing_trade_ml.core.config import settings


class FakeRedis:
    """Just enough of redis-py for the limiter: pipeline().incr().expire().execute()."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    def pipeline(self, transaction: bool = True) -> FakeRedis._Pipe:
        return FakeRedis._Pipe(self)

    class _Pipe:
        def __init__(self, owner: FakeRedis) -> None:
            self.owner = owner
            self.ops: list[tuple[str, str, int]] = []

        def incr(self, key: str) -> None:
            self.ops.append(("incr", key, 0))

        def expire(self, key: str, ttl: int) -> None:
            self.ops.append(("expire", key, ttl))

        def execute(self) -> list[object]:
            out: list[object] = []
            for op, key, ttl in self.ops:
                if op == "incr":
                    self.owner.counts[key] = self.owner.counts.get(key, 0) + 1
                    out.append(self.owner.counts[key])
                else:
                    self.owner.ttls[key] = ttl
                    out.append(True)
            return out


class DownRedis:
    def __init__(self) -> None:
        self.calls = 0

    def pipeline(self, transaction: bool = True) -> object:
        self.calls += 1
        raise ConnectionError("redis is down")


@pytest.fixture()
def limits_on(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_AUTH_PER_MINUTE", 3)
    monkeypatch.setattr(settings, "RATE_LIMIT_PUBLIC_PER_MINUTE", 5)
    # Pin the clock mid-window so a slow test never straddles a minute boundary.
    monkeypatch.setattr(rate_limit, "_now", lambda: 1_800_000_030.0)
    fake = FakeRedis()
    rate_limit.set_redis_client(fake)
    yield fake
    rate_limit.set_redis_client(None)


def _client(ip: str = "203.0.113.7") -> TestClient:
    from swing_trade_ml.main import app

    return TestClient(app, client=(ip, 50000))


@pytest.fixture()
def db_override(db_session):
    from swing_trade_ml.db.session import get_db
    from swing_trade_ml.main import app

    app.dependency_overrides[get_db] = lambda: db_session
    yield
    app.dependency_overrides.pop(get_db, None)


def test_public_under_limit_ok_then_429_with_retry_after(limits_on):
    c = _client()
    for _ in range(5):
        assert c.get("/api/v1/auth/options").status_code == 200
    r = c.get("/api/v1/auth/options")
    assert r.status_code == 429
    assert r.headers["Retry-After"] == "30"
    assert "Too many attempts" in r.json()["detail"]
    # The counter expires on its own.
    assert all(ttl == 61 for ttl in limits_on.ttls.values())


def test_login_limited_per_ip_before_lockout(limits_on, db_override):
    c = _client()
    body = {"username": "nobody-here", "password": "wrong-password-1"}
    for _ in range(3):
        assert c.post("/api/v1/auth/login", json=body).status_code == 401
    r = c.post("/api/v1/auth/login", json=body)
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_auth_endpoints_share_one_counter(limits_on, db_override):
    c = _client()
    body = {"username": "nobody-here", "password": "wrong-password-1"}
    c.post("/api/v1/auth/login", json=body)
    c.post("/api/v1/auth/google/exchange", json={"code": "x" * 20})
    c.get("/api/v1/auth/google/login", follow_redirects=False)
    assert c.get("/api/v1/auth/kite/callback", params={"request_token": "t"}).status_code == 429


def test_public_and_auth_counted_separately(limits_on, db_override):
    c = _client()
    for _ in range(5):
        assert c.get("/api/v1/auth/options").status_code == 200
    assert c.get("/api/v1/auth/options").status_code == 429
    assert c.post("/api/v1/auth/login", json={"username": "a", "password": "b"}).status_code != 429


def test_separate_ips_counted_separately(limits_on):
    a, b = _client("203.0.113.1"), _client("203.0.113.2")
    for _ in range(5):
        assert a.get("/api/v1/auth/options").status_code == 200
    assert a.get("/api/v1/auth/options").status_code == 429
    assert b.get("/api/v1/auth/options").status_code == 200


def test_forwarded_clients_behind_our_proxy_counted_separately(limits_on):
    proxy = _client("172.18.0.1")  # Docker bridge gateway, as nginx -> api looks in prod

    def get(visitor: str) -> int:
        return proxy.get("/api/v1/auth/options", headers={"X-Forwarded-For": visitor}).status_code

    for _ in range(5):
        assert get("198.51.100.1") == 200
    assert get("198.51.100.1") == 429
    assert get("198.51.100.2") == 200


def test_redis_down_fails_open(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_PUBLIC_PER_MINUTE", 1)
    down = DownRedis()
    rate_limit.set_redis_client(down)
    try:
        c = _client()
        for _ in range(5):
            assert c.get("/api/v1/auth/options").status_code == 200
        # After one failure Redis is left alone for a while (no timeout per request).
        assert down.calls == 1
    finally:
        rate_limit.set_redis_client(None)


def test_health_is_never_limited(limits_on):
    """Uptime and the after-deploy check call /health; a 429 there would read as an outage."""
    c = _client()
    for _ in range(20):
        assert c.get("/api/v1/health").status_code == 200
    assert limits_on.counts == {}


def test_disabled_never_touches_redis(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
    down = DownRedis()
    rate_limit.set_redis_client(down)
    try:
        assert _client().get("/api/v1/auth/options").status_code == 200
        assert down.calls == 0
    finally:
        rate_limit.set_redis_client(None)


def _req(peer: str, headers: dict[str, str] | None = None) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "client": (peer, 1234), "headers": raw})


@pytest.mark.parametrize(
    ("peer", "headers", "expected"),
    [
        # Direct from the internet: headers are the caller's own words, ignored.
        ("203.0.113.9", {"X-Forwarded-For": "1.2.3.4"}, "203.0.113.9"),
        ("203.0.113.9", {"X-Real-IP": "1.2.3.4"}, "203.0.113.9"),
        # Via our proxy: right-most entry nginx appended wins over a forged left part.
        ("172.18.0.1", {"X-Forwarded-For": "1.2.3.4, 198.51.100.5"}, "198.51.100.5"),
        # Our own hops on the right are skipped.
        ("127.0.0.1", {"X-Forwarded-For": "198.51.100.5, 172.18.0.1"}, "198.51.100.5"),
        ("127.0.0.1", {"X-Real-IP": "198.51.100.6"}, "198.51.100.6"),
        ("127.0.0.1", {}, "127.0.0.1"),
    ],
)
def test_client_ip(peer, headers, expected):
    assert rate_limit.client_ip(_req(peer, headers)) == expected
