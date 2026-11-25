"""#239 gap G10: the stock page's plan percentages come from the Brain's decision policy.

Pure tests (no database). Production overrides the v1 ml_swing settings (for example a
+2% target), so the plan must not move when those settings change. Expected numbers are
the Brain's own policy (+8% target, -4% stop, half out at +5%, 15 sessions), the same
object that sets each stored target and stop.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from swing_trade_ml.brain import replay_scoring
from swing_trade_ml.brain.modules.m08_decide.policy import DEFAULT_POLICY
from swing_trade_ml.core.config import settings
from swing_trade_ml.services import beginner_views, trading_rules

SRC = Path(__file__).resolve().parents[1] / "src" / "swing_trade_ml"
V1_PLAN_SETTINGS = ("ML_FIRST_TARGET_PCT", "ML_TARGET_RETURN_PCT", "ML_STOP_RETURN_PCT")


def test_the_brain_policy_is_the_locked_rule():
    assert DEFAULT_POLICY.target_pct == pytest.approx(0.08)
    assert DEFAULT_POLICY.stop_pct == pytest.approx(0.04)
    assert DEFAULT_POLICY.first_target_pct == pytest.approx(0.05)
    assert DEFAULT_POLICY.horizon_days == 15


def test_trading_rules_serve_the_brain_policy_not_the_v1_settings(monkeypatch):
    for name in V1_PLAN_SETTINGS:
        monkeypatch.setattr(settings, name, 0.99)  # an absurd override must not reach the plan
    plan = trading_rules.trading_rules(as_of=date(2026, 11, 25), include_research=False)["brain_plan"]
    assert plan == {
        "target_pct": DEFAULT_POLICY.target_pct,
        "stop_pct": DEFAULT_POLICY.stop_pct,
        "half_out_pct": DEFAULT_POLICY.first_target_pct,
        "max_sessions": DEFAULT_POLICY.horizon_days,
    }


def test_replay_scoring_constants_are_aliases_of_the_policy_not_copies():
    assert DEFAULT_POLICY.target_pct == replay_scoring.TARGET
    assert DEFAULT_POLICY.stop_pct == replay_scoring.STOP
    assert DEFAULT_POLICY.first_target_pct == replay_scoring.HALF_OUT
    assert DEFAULT_POLICY.horizon_days == replay_scoring.HORIZON_BARS


def test_money_at_stake_does_not_move_when_v1_settings_are_overridden(monkeypatch):
    args = (1000.0, 960.0, 1080.0, 40)  # entry, stop, target, qty
    before = beginner_views.money_at_stake(*args)
    for name in V1_PLAN_SETTINGS:
        monkeypatch.setattr(settings, name, 0.02)
    after = beginner_views.money_at_stake(*args)
    assert before == after
    assert before["available"] is True


PLAN_MODULES = [
    "services/beginner_views.py",
    "services/trading_rules.py",
    "brain/replay_scoring.py",
]


@pytest.mark.parametrize("module", PLAN_MODULES)
def test_no_v1_plan_setting_is_read_in_the_plan_modules(module):
    text = (SRC / module).read_text(encoding="utf-8")
    for name in V1_PLAN_SETTINGS:
        assert f"settings.{name}" not in text, f"{module} still reads settings.{name}"
