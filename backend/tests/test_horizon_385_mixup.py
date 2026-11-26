# ruff: noqa: E501 (long lines in test code)
"""#385 pinned: a 5-day model's score is stamped with the Brain's default 15-day horizon.

Today the one live run request is built without a horizon (brain/service.py), so it carries the contract default
of 15 (brain/contracts.py), while the score comes from whichever model is active, whatever horizon it was trained
for. This test states the wanted behaviour and is a STRICT xfail: it fails today, and when someone fixes the
cause it turns into an error that says to remove the marker. No database, no clock.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import swing_trade_ml.brain.contracts as contracts
import swing_trade_ml.brain.service as service

LIVE_CALL_ARGS = {"run_id", "kind", "as_of", "universe", "book", "live"}


def _live_run_requests() -> list[ast.Call]:
    tree = ast.parse(Path(service.__file__).read_text(encoding="utf8"))
    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "RunRequest":
            names = {k.arg for k in node.keywords}
            if "universe" in names and names >= LIVE_CALL_ARGS:
                calls.append(node)
    return calls


def test_the_contract_default_horizon_is_fifteen():
    """The fact the mix-up rests on (not an xfail): a request that names no horizon says 15."""
    assert contracts.RunRequest.__dataclass_fields__["horizon_days"].default == 15


def test_both_run_requests_are_found():
    # the failure record's empty request and the real one; the pin below must be looking at them
    assert len(_live_run_requests()) == 2


@pytest.mark.xfail(
    strict=True,
    reason="#385: the live run request never names the scoring model's horizon, so a 5-day score is stamped 15",
)
def test_a_live_run_request_carries_the_scoring_models_horizon():
    for call in _live_run_requests():
        assert "horizon_days" in {k.arg for k in call.keywords}
