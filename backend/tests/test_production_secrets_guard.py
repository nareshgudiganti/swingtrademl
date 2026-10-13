"""In production the app must refuse to start with a placeholder API key or JWT secret, and warn about
short ones. Local and test runs are never affected."""

from __future__ import annotations

import warnings

import pytest

from swing_trade_ml.core.config import Settings

STRONG = "x" * 40


def _make(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


@pytest.mark.parametrize("field", ["API_KEY", "JWT_SECRET_KEY"])
def test_production_refuses_the_placeholder(field):
    kw = {"ENVIRONMENT": "production", "API_KEY": STRONG, "JWT_SECRET_KEY": STRONG, field: "change-me"}
    with pytest.raises(ValueError, match=field):
        _make(**kw)


def test_production_with_strong_secrets_starts():
    s = _make(ENVIRONMENT="production", API_KEY=STRONG, JWT_SECRET_KEY=STRONG)
    assert s.ENVIRONMENT == "production"


def test_production_warns_about_a_short_secret_but_starts():
    with pytest.warns(UserWarning, match="shorter than 32"):
        s = _make(ENVIRONMENT="production", API_KEY="s" * 20, JWT_SECRET_KEY=STRONG)
    assert s.API_KEY == "s" * 20


@pytest.mark.parametrize("env", ["local", "staging"])
def test_other_environments_keep_the_defaults(env):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        s = _make(ENVIRONMENT=env, API_KEY="change-me", JWT_SECRET_KEY="change-me")
    assert s.API_KEY == "change-me"
