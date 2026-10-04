"""Owner decision 2026-10-01: while BRAIN_ENABLED is false, production must look
exactly like today — no Brain API, and the app is told the brain is off."""

from __future__ import annotations

import pytest

from swing_trade_ml.core.config import settings

HEADERS = {"X-API-Key": "test-api-key"}


@pytest.fixture()
def brain_off(monkeypatch):
    monkeypatch.setattr(settings, "BRAIN_ENABLED", False)


def test_brain_api_is_not_found_while_the_brain_is_off(client, brain_off):
    for path in ("/api/v1/brain/modules", "/api/v1/brain/health", "/api/v1/brain/runs/latest"):
        assert client.get(path, headers=HEADERS).status_code == 404
    assert client.post("/api/v1/brain/runs", json={"kind": "nightly"}, headers=HEADERS).status_code == 404


def test_brain_api_works_when_the_brain_is_on(client):
    assert client.get("/api/v1/brain/modules", headers=HEADERS).status_code == 200


def test_status_tells_the_app_whether_the_brain_is_on(client, brain_off):
    assert client.get("/api/v1/status", headers=HEADERS).json()["brain_enabled"] is False
