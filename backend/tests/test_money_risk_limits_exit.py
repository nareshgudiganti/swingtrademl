"""Risk gate, account-size limits and exit policy: the edge paths (qa8 coverage floor).

The main paths (risk-per-trade sizing, concentration cap, sector cap, drawdown halt, scale-out at +5%)
are covered in test_risk.py, test_limits.py, test_portfolio_risk_layer.py and
test_paper_trade_lifecycle.py. These pin the rest of the refusals and the malformed-input fallbacks,
every one of which must end in a smaller trade or no trade, never a bigger one.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Position, Strategy
from swing_trade_ml.services import deployable, risk
from swing_trade_ml.services.exit_policy import (
    DEFAULT_TIME_STOP_DAYS,
    ExitPolicy,
    exit_confidence_for,
    exit_policy_for,
    exit_policy_for_strategy,
    scale_out_quantity,
)
from swing_trade_ml.services.limits import RUNGS, limits_for

_TOKEN = iter(range(870_000_000, 880_000_000))


# ------------------------------------------------------------- exit policy --


def test_exit_confidence_override_and_malformed_fallback():
    default = exit_confidence_for(None)
    assert exit_confidence_for(Strategy(params={"exit_confidence": "0.4"})) == pytest.approx(0.4)
    assert exit_confidence_for(Strategy(params={"exit_confidence": "abc"})) == default
    assert exit_confidence_for(Strategy(params={"exit_confidence": [1]})) == default


def test_no_strategy_gets_the_traded_policy():
    policy = exit_policy_for_strategy(None)
    assert policy.scale_out_at_pct == settings.ML_FIRST_TARGET_PCT
    assert policy.scale_out_fraction == 0.5 and policy.time_stop_days == DEFAULT_TIME_STOP_DAYS


def test_malformed_knobs_switch_scale_out_off_and_keep_default_time_stop():
    assert exit_policy_for({"scale_out_at_pct": "nope"}).scale_out_enabled is False
    assert exit_policy_for({"scale_out_at_pct": 0}).scale_out_enabled is False
    assert exit_policy_for({"scale_out_fraction": "half"}).scale_out_enabled is False
    assert exit_policy_for({"scale_out_fraction": 1.0}).scale_out_enabled is False
    assert exit_policy_for({"time_stop_days": "soon"}).time_stop_days == DEFAULT_TIME_STOP_DAYS
    assert exit_policy_for({"time_stop_days": -3}).time_stop_days == DEFAULT_TIME_STOP_DAYS
    assert exit_policy_for({"time_stop_days": "12"}).time_stop_days == 12


def test_scale_out_never_sells_everything_or_nothing():
    kw = {"entry_price": 100.0, "price": 106.0, "already_scaled_out": False, "min_position_value": 0.0}
    # A "fraction" of 1 would be a full exit at the wrong level.
    assert scale_out_quantity(ExitPolicy(0.05, 1.0, 30), quantity=10, **kw) == 0
    # Rounds down to zero shares.
    assert scale_out_quantity(ExitPolicy(0.05, 0.4, 30), quantity=2, **kw) == 0
    assert scale_out_quantity(ExitPolicy(0.05, 0.5, 30), quantity=10, **kw) == 5
    # Already scaled out, below target, 1 share, too small a position: all no.
    assert (
        scale_out_quantity(ExitPolicy(0.05, 0.5, 30), quantity=10, **{**kw, "already_scaled_out": True}) == 0
    )
    assert scale_out_quantity(ExitPolicy(0.05, 0.5, 30), quantity=10, **{**kw, "price": 104.0}) == 0
    assert scale_out_quantity(ExitPolicy(0.05, 0.5, 30), quantity=1, **kw) == 0
    assert (
        scale_out_quantity(ExitPolicy(0.05, 0.5, 30), quantity=10, **{**kw, "min_position_value": 10_000})
        == 0
    )


# ------------------------------------------------------------------ limits --


def test_above_the_top_rung_clamps_to_it():
    top = limits_for(RUNGS[-1].value * 5)
    assert top.rung_value == RUNGS[-1].value
    assert top.max_positions == RUNGS[-1].max_positions
    assert top.sector_cap_pct == pytest.approx(0.25)


def test_unreadable_account_value_gets_the_most_restrictive_rung():
    assert limits_for(0).rung_value == RUNGS[0].value
    assert limits_for(-5).sector_rule == "one_per_sector"


# -------------------------------------------------------------- risk sizing --


def test_affordable_quantity_degenerate_inputs():
    assert risk._affordable_quantity(100.0, 0.0) == 0.0
    assert risk._affordable_quantity(100.0, -50.0) == 0.0
    assert risk._affordable_quantity(0.0, 1_000.0) == 0.0


def test_non_positive_risk_per_share_sizes_nothing(monkeypatch):
    monkeypatch.setattr(settings, "DEFAULT_STOP_LOSS_PCT", 0.0)
    qty, note = risk.calculate_quantity(100.0, None, 1_000_000.0, 1_000_000.0)
    assert qty == 0 and "Non-positive" in note


def test_invalid_price_sizes_nothing():
    assert risk.calculate_quantity(0.0, None, 1_000_000.0, 1_000_000.0) == (0, "Invalid price")


# ------------------------------------------------------------ check_entry --


@pytest.fixture
def gate(db_session, monkeypatch):
    """A calm market, no drawdown history, nothing on the avoid list."""
    monkeypatch.setattr(
        deployable,
        "current_deployable",
        lambda db: deployable.DeployableCapital(regime="strong", fraction=1.0, context_available=True),
    )
    monkeypatch.setattr(risk, "drawdown_peak", lambda db, mode: None)
    monkeypatch.setattr(risk.avoid, "avoid_reason", lambda db, symbol, day: None)
    return db_session


def _inst(db, symbol):
    inst = Instrument(instrument_token=next(_TOKEN), tradingsymbol=symbol, exchange="NSE")
    db.add(inst)
    db.flush()
    return inst


def _strat(db, name, **kw):
    s = Strategy(name=name, strategy_type="ml_swing", mode="paper", **kw)
    db.add(s)
    db.flush()
    return s


def _pos(db, strat, inst, qty, price, **kw):
    p = Position(
        strategy_id=strat.id,
        instrument_id=inst.id,
        mode="paper",
        status=kw.pop("status", "OPEN"),
        quantity=qty,
        entry_price=price,
        entry_at=datetime.now(UTC),
        current_price=price,
        **kw,
    )
    db.add(p)
    db.flush()
    return p


def _check(db, inst, price, portfolio, cash, strategy=None, stop=None, **kw):
    return risk.check_entry(db, "paper", inst.id, price, stop, portfolio, cash, strategy, **kw)


def test_already_open_in_this_instrument_is_refused(gate):
    inst, strat = _inst(gate, "QACOVA1"), _strat(gate, "qa8_already_open")
    _pos(gate, strat, inst, 10, 100.0)
    verdict = _check(gate, inst, 100.0, 1_000_000.0, 1_000_000.0, strat)
    assert (verdict.allowed, verdict.rule) == (False, "ALREADY_OPEN")


def test_recent_stop_out_cools_down_and_zero_days_disables_it(gate):
    inst, strat = _inst(gate, "QACOVA2"), _strat(gate, "qa8_cooldown")
    _pos(
        gate, strat, inst, 10, 100.0, status="CLOSED", exit_reason="STOP_LOSS_HIT", exit_at=datetime.now(UTC)
    )
    verdict = _check(gate, inst, 100.0, 1_000_000.0, 1_000_000.0, strat)
    assert (verdict.allowed, verdict.rule) == (False, "COOLDOWN")
    assert risk.stopped_out_recently(gate, "paper", inst.id, strat.id, 0) is False


def test_share_price_cap_on_the_smallest_account(gate):
    inst = _inst(gate, "QACOVA3")
    verdict = _check(gate, inst, 3_000.0, 10_000.0, 10_000.0)
    assert (verdict.allowed, verdict.rule) == (False, "SHARE_PRICE")


def test_mid_caps_are_off_for_a_small_account(gate):
    inst, strat = _inst(gate, "QACOVA4"), _strat(gate, "qa8_midcap", params={"model_name": "m_midcap"})
    verdict = _check(gate, inst, 100.0, 10_000.0, 10_000.0, strat)
    assert (verdict.allowed, verdict.rule) == (False, "CAP_TIER")


def test_small_cap_budget_full_is_refused_and_room_is_a_ceiling(gate):
    small = _strat(gate, "qa8_smallcap", params={"model_name": "m_smallcap"})
    other = _strat(gate, "qa8_smallcap_holder", params={"model_name": "m_smallcap"})
    held = _inst(gate, "QACOVA5")
    target = _inst(gate, "QACOVA6")
    _pos(gate, other, held, 1_900, 100.0)  # ₹1,90,000 of a ₹2,00,000 small-cap budget on ₹10L
    verdict = _check(gate, target, 100.0, 1_000_000.0, 800_000.0, small, stop=96.0)
    assert (verdict.allowed, verdict.rule) == (False, "CAP_TIER")


def test_small_cap_with_room_is_sized_inside_its_budget(gate):
    small = _strat(gate, "qa8_smallcap_ok", params={"model_name": "m_smallcap"})
    target = _inst(gate, "QACOVA7")
    verdict = _check(gate, target, 100.0, 1_000_000.0, 1_000_000.0, small, stop=96.0)
    assert verdict.allowed
    assert verdict.quantity * 100.0 <= 0.20 * 1_000_000.0


def test_position_below_minimum_is_refused(gate):
    inst = _inst(gate, "QACOVA8")
    # Stop 99% away: risk-per-trade allows only ~₹10K, under the ₹40K minimum at ₹10L.
    verdict = _check(gate, inst, 100.0, 1_000_000.0, 1_000_000.0, stop=1.0)
    assert verdict.allowed is False and verdict.rule == "MIN_POSITION"
    assert verdict.amount_inr < limits_for(1_000_000.0).min_position_inr


def test_final_cash_check_refuses_when_cost_exceeds_cash(gate, monkeypatch):
    inst = _inst(gate, "QACOVA9")
    monkeypatch.setattr(risk, "buy_cost", lambda price, qty: 10_000_000.0)
    verdict = _check(gate, inst, 100.0, 1_000_000.0, 1_000_000.0, stop=96.0)
    assert (verdict.allowed, verdict.rule) == (False, "CASH")
