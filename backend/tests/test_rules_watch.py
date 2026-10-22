"""The risk-rules alarm (tracker rs2): the settings, strategies, brain policy and capital ladder the app
really trades with must match the rules the owner agreed, or the daily check fails and messages."""

from __future__ import annotations

from dataclasses import replace

import pytest

from swing_trade_ml.brain.modules.m08_decide import policy as m08_policy
from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.trading import Strategy
from swing_trade_ml.services import limits, rules_watch


@pytest.fixture(autouse=True)
def _agreed_settings(monkeypatch):
    """Start every test from the agreed values: a local .env can carry its own (one sets a 20% halt)."""
    monkeypatch.setattr(settings, "MAX_PORTFOLIO_DRAWDOWN_PCT", 0.15)
    monkeypatch.setattr(settings, "TRADING_MODE", "paper")
    monkeypatch.setattr(settings, "ALLOW_LIVE_TRADING", False)


def _strategy(db, name, stype, **kw):
    s = Strategy(name=name, strategy_type=stype, is_active=True, mode="paper", **kw)
    db.add(s)
    db.flush()
    return s


def test_agreed_rules_pass(db_session):
    _strategy(db_session, "rw_ml", "ml_swing", params={"model_name": "x"})
    c = rules_watch.check(db_session)
    assert c["ok"], c["detail"]


def test_a_changed_setting_fails(db_session, monkeypatch):
    monkeypatch.setattr(settings, "MAX_PORTFOLIO_DRAWDOWN_PCT", 0.20)
    monkeypatch.setattr(settings, "ML_STOP_RETURN_PCT", 0.05)
    c = rules_watch.check(db_session)
    assert not c["ok"] and c["level"] == "fail"
    assert "drawdown halt is 20%, agreed 15%" in c["detail"] and "stop is 5%, agreed 4%" in c["detail"]


def test_live_mode_fails(db_session, monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_LIVE_TRADING", True)
    assert "live trading is allowed" in rules_watch.check(db_session)["detail"]


def test_a_strategy_override_fails(db_session):
    _strategy(db_session, "rw_short", "ml_swing", params={"time_stop_days": 15, "scale_out_at_pct": 0})
    detail = rules_watch.check(db_session)["detail"]
    assert "rw_short uses half-out at off, time stop 15 days" in detail


def test_a_strategy_with_its_own_levels_fails(db_session):
    _strategy(db_session, "rw_sma", "sma_crossover", stop_loss_pct=0.05, take_profit_pct=0.15)
    assert "rw_sma uses stop 5%, target 15%" in rules_watch.check(db_session)["detail"]


def test_inactive_strategies_are_ignored(db_session):
    s = _strategy(db_session, "rw_off", "sma_crossover", stop_loss_pct=0.05)
    s.is_active = False
    db_session.flush()
    assert "rw_off" not in rules_watch.check(db_session)["detail"]


def test_brain_policy_and_ladder_are_checked(db_session, monkeypatch):
    monkeypatch.setattr(m08_policy, "DEFAULT_POLICY", replace(m08_policy.DEFAULT_POLICY, stop_pct=0.03))
    rungs = list(limits.RUNGS)
    rungs[1] = replace(rungs[1], sector_cap_pct=0.40)
    monkeypatch.setattr(limits, "RUNGS", tuple(rungs))
    detail = rules_watch.check(db_session)["detail"]
    assert "brain stop is 3%, agreed 4%" in detail and "₹100,000 rung is 40%" in detail


def test_it_is_part_of_the_daily_check(db_session, tmp_path):
    from swing_trade_ml.services import brain_weekly_health as weekly

    names = [c["name"] for c in weekly.compute_checks(db_session, backup_dir=str(tmp_path))["checks"]]
    assert "Risk rules" in names


def _five_day_v1(monkeypatch):
    monkeypatch.setattr(settings, "ML_PREDICTION_HORIZON_DAYS", 5)
    monkeypatch.setattr(settings, "ML_TARGET_RETURN_PCT", 0.02)
    monkeypatch.setattr(settings, "ML_STOP_RETURN_PCT", 0.04)


def test_the_v1_bot_on_the_agreed_5_day_horizon_passes(db_session, monkeypatch):
    """Owner 2026-10-20: +2% in 5 days is a second agreed horizon for the v1 bot, not a broken rule."""
    _five_day_v1(monkeypatch)
    _strategy(db_session, "rw_ml5", "ml_swing", params={"model_name": "x"})
    _strategy(db_session, "rw_adv5", "real_trading", stop_loss_pct=0.04, take_profit_pct=0.02)
    c = rules_watch.check(db_session)
    assert c["ok"], c["detail"]
    assert "v1 bot on 5 days at +2% / -4%" in c["detail"]


def test_a_target_from_the_other_horizon_still_fails(db_session, monkeypatch):
    _five_day_v1(monkeypatch)
    monkeypatch.setattr(settings, "ML_TARGET_RETURN_PCT", 0.08)  # 5 days but the 15-day target
    detail = rules_watch.check(db_session)["detail"]
    assert "target is 8%, agreed 2% for 5 days" in detail


def test_an_unagreed_horizon_fails(db_session, monkeypatch):
    monkeypatch.setattr(settings, "ML_PREDICTION_HORIZON_DAYS", 10)
    assert "model horizon is 10 days, agreed 5 or 15" in rules_watch.check(db_session)["detail"]


def test_the_brain_must_stay_on_15_days(db_session, monkeypatch):
    _five_day_v1(monkeypatch)
    monkeypatch.setattr(m08_policy, "DEFAULT_POLICY", replace(m08_policy.DEFAULT_POLICY, horizon_days=5))
    assert "brain horizon is 5 days, agreed 15" in rules_watch.check(db_session)["detail"]


def test_the_accepted_benchmark_is_shown_but_does_not_fail(db_session):
    """Owner 2026-10-22: sma_crossover_benchmark keeps its own -5% / +15% levels as a comparison strategy."""
    _strategy(
        db_session, "sma_crossover_benchmark", "sma_crossover", stop_loss_pct=0.05, take_profit_pct=0.15
    )
    c = rules_watch.check(db_session)
    assert c["ok"] and c["level"] == "ok", c["detail"]
    assert (
        "Accepted benchmark: sma_crossover_benchmark uses its own rules (stop 5%, target 15%); "
        "it is not used to judge the brain" in c["detail"]
    )


def test_the_exception_covers_only_its_levels_and_only_that_strategy(db_session):
    _strategy(
        db_session,
        "sma_crossover_benchmark",
        "sma_crossover",
        stop_loss_pct=0.05,
        take_profit_pct=0.15,
        params={"time_stop_days": 15},
    )
    _strategy(db_session, "rw_other_sma", "sma_crossover", stop_loss_pct=0.05, take_profit_pct=0.15)
    c = rules_watch.check(db_session)
    assert not c["ok"]
    assert "sma_crossover_benchmark uses time stop 15 days" in c["detail"]  # other differences still fail
    assert "rw_other_sma uses stop 5%, target 15%" in c["detail"]  # another strategy gets no exception
