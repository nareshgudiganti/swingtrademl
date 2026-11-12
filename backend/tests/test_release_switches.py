"""Release switches: all default off, guards refuse when off, owner-only view. No DB."""

from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from swing_trade_ml.api.deps import Principal, get_principal
from swing_trade_ml.api.v1.endpoints.release_switches import admin
from swing_trade_ml.core import release_switches as rs
from swing_trade_ml.core.config import Settings, settings

KEYS = ["open_signup", "customer_screens", "model_promotion", "real_orders"]


def test_registry_has_exactly_the_four_switches():
    assert [s.key for s in rs.SWITCHES] == KEYS


def test_every_switch_defaults_off_in_the_settings_class():
    for s in rs.SWITCHES:
        assert Settings.model_fields[s.setting].default is False, s.key


@pytest.mark.parametrize("key", KEYS)
def test_guard_refuses_when_off_and_allows_when_on(key, monkeypatch):
    sw = rs._BY_KEY[key]
    guard = rs.require_release(key)
    monkeypatch.setattr(settings, sw.setting, False)
    with pytest.raises(HTTPException) as e:
        guard()
    assert e.value.status_code == 404
    monkeypatch.setattr(settings, sw.setting, True)
    assert guard() is None


def test_unknown_key_is_rejected_at_definition_time():
    with pytest.raises(KeyError):
        rs.require_release("nope")


class _U:
    def __init__(self, role):
        self.role = role
        self.username = "x"


def _app():
    app = FastAPI()
    app.include_router(admin, prefix="/api/v1")
    return app


def _client(principal):
    app = _app()

    async def _p():
        return principal

    app.dependency_overrides[get_principal] = _p
    return TestClient(app)


def test_endpoint_works_for_owner_and_lists_states(monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_CUSTOMER_SCREENS", True)
    r = _client(Principal(user=_U("owner"))).get("/api/v1/admin/release-switches")
    assert r.status_code == 200
    got = {s["key"]: s["enabled"] for s in r.json()["switches"]}
    assert list(got) == KEYS and got["customer_screens"] is True


def test_endpoint_works_for_api_key():
    r = _client(Principal(user=None, via_api_key=True)).get("/api/v1/admin/release-switches")
    assert r.status_code == 200


@pytest.mark.parametrize("role", ["member", "tester"])
def test_endpoint_refused_for_non_owner(role):
    assert _client(Principal(user=_U(role))).get("/api/v1/admin/release-switches").status_code == 403


def test_endpoint_refused_for_anonymous():
    # No principal override and no DB: the real dependency refuses before touching a database.
    r = TestClient(_app()).get("/api/v1/admin/release-switches")
    assert r.status_code in (401, 403)


def test_require_release_is_not_attached_to_any_existing_route():
    from swing_trade_ml.main import app

    for route in app.routes:
        dependant = getattr(route, "dependant", None)
        if dependant is None:
            continue
        stack = list(dependant.dependencies)
        while stack:
            d = stack.pop()
            assert getattr(d.call, "__qualname__", "").split(".")[0] != "require_release", route.path
            stack.extend(d.dependencies)
