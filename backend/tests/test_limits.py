"""The capital ladder — services/limits.py.

Pure-logic tests: limits_for() takes a portfolio value and (optionally) a
strategy, and returns a Limits object. No database needed.
"""

from __future__ import annotations

import math

import pytest

from swing_trade_ml.db.models.trading import Strategy
from swing_trade_ml.services.limits import limits_for

RUNGS = [
    (10_000, {"max_positions": 2, "max_position_pct": 0.50, "sector_rule": "one_per_sector",
              "scale_out_enabled": False, "allowed_cap_tiers": {"large"}, "cash_floor_pct": 0.0,
              "max_share_price_inr": 2_500.0}),
    (100_000, {"max_positions": 4, "max_position_pct": 0.25, "sector_rule": "pct_cap",
               "sector_cap_pct": 0.25, "scale_out_enabled": True,
               "allowed_cap_tiers": {"large", "midcap"}, "cash_floor_pct": 0.05}),
    (1_000_000, {"max_positions": 8, "max_position_pct": 0.10, "sector_cap_pct": 0.25,
                 "max_adv_pct": 0.02, "allowed_cap_tiers": {"large", "midcap", "smallcap"},
                 "small_cap_budget_pct": 0.20, "cash_floor_pct": 0.10}),
    (2_500_000, {"max_positions": 12, "max_position_pct": 0.08, "max_adv_pct": 0.02,
                 "small_cap_budget_pct": 0.20}),
    (5_000_000, {"max_positions": 16, "max_position_pct": 0.06, "max_adv_pct": 0.015,
                 "small_cap_budget_pct": 0.12}),
    (10_000_000, {"max_positions": 22, "max_position_pct": 0.045, "max_adv_pct": 0.01,
                  "small_cap_budget_pct": 0.08}),
]


@pytest.mark.parametrize("portfolio_value,expected", RUNGS)
def test_every_published_rung_matches_exactly(portfolio_value, expected):
    """These numbers are the owner's decision, not an implementation detail —
    a change here is a change to how much risk the bot is allowed to take."""
    limits = limits_for(portfolio_value)
    for field, value in expected.items():
        actual = getattr(limits, field)
        if isinstance(value, float):
            assert actual == pytest.approx(value), field
        elif isinstance(value, set):
            assert set(actual) == value, field
        else:
            assert actual == value, field


def test_ten_thousand_caps_the_share_price():
    """A ₹1,000 max position (10% of ₹10,000) cannot buy a ₹3,000 share even
    once — the account-level share-price cap exists for exactly this."""
    limits = limits_for(10_000)
    assert limits.max_share_price_inr == 2_500.0


def test_one_lakh_and_above_has_no_share_price_cap():
    assert limits_for(100_000).max_share_price_inr is None
    assert limits_for(1_000_000).max_share_price_inr is None


def test_below_ten_lakh_has_no_liquidity_ceiling():
    """The rule should not exist yet, not exist-and-be-infinite — a position
    check must treat this rung as "unconstrained", not "divide by a huge cap"."""
    assert limits_for(100_000).max_adv_pct is None


def test_below_one_lakh_scale_out_is_off():
    assert limits_for(10_000).scale_out_enabled is False


def test_between_rungs_interpolates_monotonically_on_position_count():
    """Position count should rise smoothly from rung to rung, not jump."""
    values = [limits_for(v).max_positions for v in (10_000, 30_000, 60_000, 100_000, 400_000, 1_000_000)]
    assert values == sorted(values)


def test_between_rungs_single_stock_cap_falls_monotonically():
    values = [limits_for(v).max_position_pct for v in (10_000, 30_000, 100_000, 500_000, 1_000_000)]
    assert values == sorted(values, reverse=True)


def test_a_continuous_field_absent_at_the_lower_rung_switches_on_at_the_upper_one():
    """The liquidity ceiling does not exist below ₹10L. Halfway between ₹1L
    and ₹10L it must still be absent — a rule should switch on when the
    account has actually reached the size it was designed for."""
    halfway = math.sqrt(100_000 * 1_000_000)  # ~316,000: log-midpoint
    assert limits_for(halfway).max_adv_pct is None


def test_discrete_fields_take_the_lower_rung_between_two_rungs():
    """Sector rule is one_per_sector below ₹1L and a percentage from ₹1L —
    a value strictly between the rungs should not have graduated early."""
    just_under = 99_000
    assert limits_for(just_under).sector_rule == "one_per_sector"


def test_below_the_lowest_rung_clamps_to_it():
    limits = limits_for(1_000)
    assert limits.max_positions == limits_for(10_000).max_positions
    assert limits.max_position_pct == pytest.approx(limits_for(10_000).max_position_pct)


def test_above_the_highest_rung_clamps_to_it():
    limits = limits_for(50_00_00_000)  # ₹500 crore
    assert limits.max_positions == limits_for(10_000_000).max_positions
    assert limits.max_position_pct == pytest.approx(limits_for(10_000_000).max_position_pct)


def test_cash_floor_is_zero_at_ten_thousand_and_one_lakh_at_ten_lakh():
    """The owner's decision, stated as a rupee amount: ₹1,00,000 never
    deployed at ₹10L. Expressed as a percentage so it scales, this must
    still land on exactly that rupee figure at the rung it was set for."""
    assert limits_for(10_000).cash_floor_pct == 0.0
    ten_lakh = limits_for(1_000_000)
    assert ten_lakh.cash_floor_pct * 1_000_000 == pytest.approx(100_000.0)


def test_cash_floor_does_not_keep_rising_past_ten_lakh():
    """The market-conditions ceiling already holds back far more than 10% in
    anything but a strong market — the cash floor staying flat above ₹10L is
    deliberate, not a missing rung."""
    assert limits_for(1_000_000).cash_floor_pct == pytest.approx(limits_for(10_000_000).cash_floor_pct)


def test_a_strategy_max_positions_override_wins_over_the_ladder():
    strat = Strategy(name="capped", strategy_type="ml_swing", mode="paper", max_positions=3)
    limits = limits_for(1_000_000, strat)
    assert limits.max_positions == 3


def test_a_strategy_capital_allocation_override_wins_over_the_ladder():
    strat = Strategy(name="tight", strategy_type="ml_swing", mode="paper", capital_allocation=0.02)
    limits = limits_for(1_000_000, strat)
    assert limits.max_position_pct == pytest.approx(0.02)


def test_a_strategy_with_no_override_gets_the_plain_ladder_value():
    strat = Strategy(name="plain", strategy_type="ml_swing", mode="paper")
    assert limits_for(1_000_000, strat).max_positions == limits_for(1_000_000).max_positions
