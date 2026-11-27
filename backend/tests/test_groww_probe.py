"""The Groww renewal probe counts only a refused token as proof of expiry (Codex R-Q41-e4b8a192 P3)."""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

_PROBE = Path(__file__).resolve().parents[1] / "scripts" / "groww_probe.py"
_spec = spec_from_file_location("groww_probe", _PROBE)
probe = module_from_spec(_spec)
_spec.loader.exec_module(probe)


class AuthenticationError(Exception):
    pass


def _with(attr: str, value) -> Exception:
    exc = Exception()
    setattr(exc, attr, value)
    return exc


@pytest.mark.parametrize(
    "exc",
    [AuthenticationError(), _with("status_code", 401), _with("code", 403), _with("status", "401")],
)
def test_a_refused_token_is_a_rejection(exc):
    assert probe.is_auth_rejection(exc)


@pytest.mark.parametrize("exc", [TimeoutError(), ConnectionError(), ValueError(), _with("status_code", 500)])
def test_a_timeout_or_other_error_proves_nothing(exc):
    assert not probe.is_auth_rejection(exc)
