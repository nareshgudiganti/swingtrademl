"""Release switches: all default off, guards refuse when off. No DB."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

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
