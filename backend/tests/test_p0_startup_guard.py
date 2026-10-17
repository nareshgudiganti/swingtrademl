from __future__ import annotations

import pytest

from swing_trade_ml.core.config import Settings, settings
from swing_trade_ml.core.security import assert_secrets_safe

LONG = "x" * 40


def _cfg(monkeypatch, env, jwt, key):
    monkeypatch.setattr(settings, "ENVIRONMENT", env)
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", jwt)
    monkeypatch.setattr(settings, "API_KEY", key)
    return settings


@pytest.mark.parametrize("bad", ["", "change-me", " change-me "])
def test_refuses_default_secrets_outside_local(monkeypatch, bad):
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        assert_secrets_safe(_cfg(monkeypatch, "production", bad, LONG))


def test_error_never_contains_the_secret_value(monkeypatch):
    with pytest.raises(RuntimeError) as exc:
        assert_secrets_safe(_cfg(monkeypatch, "production", LONG, "change-me"))
    assert LONG not in str(exc.value)


def test_names_api_key_too(monkeypatch):
    with pytest.raises(RuntimeError, match="API_KEY"):
        assert_secrets_safe(_cfg(monkeypatch, "staging", LONG, "change-me"))


def test_local_is_allowed_defaults(monkeypatch):
    assert_secrets_safe(_cfg(monkeypatch, "local", "change-me", "change-me"))


def test_real_secrets_pass_and_short_ones_only_warn(monkeypatch):
    assert_secrets_safe(_cfg(monkeypatch, "production", LONG, LONG))
    assert_secrets_safe(_cfg(monkeypatch, "production", "short-but-real", LONG))


def test_signup_is_closed_by_default():
    assert Settings.model_fields["ALLOW_SIGNUP"].default is False
