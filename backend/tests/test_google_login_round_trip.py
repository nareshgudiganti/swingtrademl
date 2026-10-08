"""Google sign-in, end to end with Google itself faked: the callback must send
the browser back to the app with a token, and that token must work."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import httpx

from swing_trade_ml.api.v1.endpoints import auth as auth_endpoint
from swing_trade_ml.core.config import settings

OWNER_EMAIL = "owner@example.com"


class _Reply:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def _fake_google(monkeypatch, email: str = OWNER_EMAIL) -> None:
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "id")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setattr(settings, "GOOGLE_ALLOWED_EMAILS", OWNER_EMAIL)
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Reply({"access_token": "g-token"}))
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **k: _Reply({"sub": "g-123", "email": email, "email_verified": True}),
    )


def _callback(client) -> tuple[str, str]:
    state = auth_endpoint._issue_state()
    resp = client.get(f"/api/v1/auth/google/callback?code=c&state={state}", follow_redirects=False)
    assert resp.status_code in (302, 307), resp.text
    location = resp.headers["location"]
    token = parse_qs(urlparse(location).query)["token"][0]
    return location, token


def test_google_callback_redirects_to_the_configured_app_with_a_working_token(client, monkeypatch):
    _fake_google(monkeypatch)
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://swingtrademl.com")

    location, token = _callback(client)

    assert location.startswith("https://swingtrademl.com/?token=")
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200, me.text
    assert me.json()["email"] == OWNER_EMAIL
    plan = client.get("/api/v1/me/plan", headers={"Authorization": f"Bearer {token}"})
    assert plan.status_code == 200, plan.text


def test_without_frontend_url_the_browser_goes_back_to_the_site_that_handled_the_callback(client, monkeypatch):
    """The production trap: GOOGLE_REDIRECT_URL is set to the real site but
    FRONTEND_URL is left at its localhost default, so the token was sent to
    http://localhost:5173 and the app on the real site never saw it."""
    _fake_google(monkeypatch)
    monkeypatch.setattr(settings, "FRONTEND_URL", "http://localhost:5173")
    monkeypatch.setattr(
        settings, "GOOGLE_REDIRECT_URL", "https://swingtrademl.com/api/v1/auth/google/callback"
    )

    location, _ = _callback(client)

    assert location.startswith("https://swingtrademl.com/?token=")


def test_an_explicit_frontend_url_always_wins(client, monkeypatch):
    _fake_google(monkeypatch)
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://app.example.org/")
    monkeypatch.setattr(
        settings, "GOOGLE_REDIRECT_URL", "https://swingtrademl.com/api/v1/auth/google/callback"
    )

    location, _ = _callback(client)

    assert location.startswith("https://app.example.org/?token=")


def test_local_development_still_goes_to_localhost(client, monkeypatch):
    _fake_google(monkeypatch)
    monkeypatch.setattr(settings, "FRONTEND_URL", "http://localhost:5173")
    monkeypatch.setattr(
        settings, "GOOGLE_REDIRECT_URL", "http://localhost:8000/api/v1/auth/google/callback"
    )

    location, _ = _callback(client)

    assert location.startswith("http://localhost:5173/?token=")
