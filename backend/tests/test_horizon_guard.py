"""The refusal rule that stops a mixed decision (#385). Pure."""

from __future__ import annotations

import pytest

from swing_trade_ml.brain.horizons import NO_DECISION_TEXT, check_score_for_horizon, horizon_refusal


@pytest.mark.parametrize("h", [5, 10, 15])
def test_a_model_of_the_same_horizon_decides(h):
    assert horizon_refusal("m v1", h, h) is None
    assert check_score_for_horizon("m v1", h, h).ok


@pytest.mark.parametrize("model,asked", [(5, 15), (15, 5), (10, 5), (5, 10), (10, 15), (15, 10)])
def test_a_score_of_another_horizon_gives_no_decision_never_a_mixed_one(model, asked):
    out = check_score_for_horizon("m v1", model, asked)
    assert not out.ok
    assert out.reason.startswith(NO_DECISION_TEXT)
    assert f"{model} sessions" in out.reason and f"{asked}-session" in out.reason


def test_an_unknown_model_horizon_never_decides():
    out = check_score_for_horizon("m v1", None, 5)
    assert not out.ok and "no recorded forecast horizon" in out.reason
