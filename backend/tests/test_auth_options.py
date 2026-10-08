"""The login page asks, before anyone is signed in, whether sign-up is open."""

from __future__ import annotations

from swing_trade_ml.core.config import settings


def test_auth_options_is_public_and_reports_signup(client, monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_SIGNUP", False)
    resp = client.get("/api/v1/auth/options")
    assert resp.status_code == 200
    assert resp.json() == {"signup_allowed": False}

    monkeypatch.setattr(settings, "ALLOW_SIGNUP", True)
    assert client.get("/api/v1/auth/options").json() == {"signup_allowed": True}


def test_signup_refused_when_closed(client, monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_SIGNUP", False)
    resp = client.post("/api/v1/auth/signup", json={"username": "newperson", "password": "longenough1"})
    assert resp.status_code == 403
