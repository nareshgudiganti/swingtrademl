"""Position sizing tests — the arithmetic that bounds every loss."""

from __future__ import annotations

import pytest

from swing_trade_ml.core.config import settings
from swing_trade_ml.services.risk import calculate_quantity, rank_buy_candidates


def test_size_is_bounded_by_risk_per_trade():
    """With a wide stop, risk-per-trade should be the binding constraint."""
    portfolio, price, stop = 1_000_000.0, 100.0, 90.0  # 10% stop

    quantity, note = calculate_quantity(price, stop, portfolio, available_cash=portfolio)

    # 1% of 1,000,000 = 10,000 risk budget / 10 per share = 1000 shares
    expected = int((portfolio * settings.RISK_PER_TRADE_PCT) / (price - stop))
    assert quantity == expected
    assert "risk-per-trade" in note


def test_tight_stop_is_capped_by_concentration_limit():
    """A very tight stop would otherwise justify an enormous position."""
    portfolio, price, stop = 1_000_000.0, 100.0, 99.5  # 0.5% stop

    quantity, note = calculate_quantity(price, stop, portfolio, available_cash=portfolio)

    max_by_concentration = int((portfolio * settings.MAX_POSITION_PCT) / price)
    assert quantity == max_by_concentration
    assert "concentration" in note


def test_size_never_exceeds_available_cash():
    quantity, note = calculate_quantity(
        price=100.0, stop_loss=95.0, portfolio_value=1_000_000.0, available_cash=5_000.0
    )
    assert quantity * 100.0 <= 5_000.0
    assert "cash" in note


def test_missing_stop_falls_back_to_default_distance():
    """No stop must not mean unbounded sizing."""
    quantity, _ = calculate_quantity(
        price=100.0, stop_loss=None, portfolio_value=1_000_000.0, available_cash=1_000_000.0
    )
    implied_risk_per_share = 100.0 * settings.DEFAULT_STOP_LOSS_PCT
    expected = int((1_000_000.0 * settings.RISK_PER_TRADE_PCT) / implied_risk_per_share)
    assert quantity == min(expected, int((1_000_000.0 * settings.MAX_POSITION_PCT) / 100.0))


# ------------------------------------------------------- fixed_amount mode --
# The small, capital-light live-rollout sizing: a flat rupee spend per
# position instead of risk-per-trade, so per-order fixed costs (Zerodha's DP
# charge on every sell, this app's own cost model) can't dominate a
# precisely-risk-sized position that would otherwise come out too small.


def test_fixed_amount_mode_ignores_stop_distance(monkeypatch):
    """A very tight stop would blow up risk-based sizing into an enormous
    position (see test_tight_stop_is_capped_by_concentration_limit) — fixed
    mode must not care, since it isn't sizing off the stop at all."""
    monkeypatch.setattr(settings, "POSITION_SIZING_MODE", "fixed_amount")
    monkeypatch.setattr(settings, "FIXED_POSITION_AMOUNT_INR", 10_000.0)

    quantity, note = calculate_quantity(
        price=100.0, stop_loss=99.5, portfolio_value=1_000_000.0, available_cash=1_000_000.0
    )
    assert quantity == 100  # 10,000 / 100
    assert "fixed amount" in note


def test_fixed_amount_mode_still_respects_available_cash(monkeypatch):
    """The flat target is a target, not a guarantee — cash is still a hard
    ceiling, same as risk-based mode."""
    monkeypatch.setattr(settings, "POSITION_SIZING_MODE", "fixed_amount")
    monkeypatch.setattr(settings, "FIXED_POSITION_AMOUNT_INR", 10_000.0)

    quantity, note = calculate_quantity(
        price=100.0, stop_loss=95.0, portfolio_value=1_000_000.0, available_cash=500.0
    )
    assert quantity * 100.0 <= 500.0
    assert "cash" in note


def test_fixed_amount_mode_still_respects_concentration_cap(monkeypatch):
    """A fixed amount larger than the concentration ceiling must still be
    capped — the flat target is a floor-raiser, not an override of the
    portfolio-level exposure limit."""
    monkeypatch.setattr(settings, "POSITION_SIZING_MODE", "fixed_amount")
    monkeypatch.setattr(settings, "FIXED_POSITION_AMOUNT_INR", 500_000.0)

    quantity, note = calculate_quantity(
        price=100.0, stop_loss=95.0, portfolio_value=1_000_000.0, available_cash=1_000_000.0
    )
    max_by_concentration = int((1_000_000.0 * settings.MAX_POSITION_PCT) / 100.0)
    assert quantity == max_by_concentration
    assert "concentration" in note


def test_stop_above_price_is_treated_as_invalid():
    """A stop above entry is nonsense for a long; fall back rather than size negative."""
    quantity, _ = calculate_quantity(
        price=100.0, stop_loss=110.0, portfolio_value=1_000_000.0, available_cash=1_000_000.0
    )
    assert quantity > 0


@pytest.mark.parametrize("price", [0.0, -5.0])
def test_invalid_price_yields_zero(price):
    quantity, note = calculate_quantity(price, None, 1_000_000.0, 1_000_000.0)
    assert quantity == 0
    assert "Invalid price" in note


def test_insufficient_capital_yields_zero():
    quantity, note = calculate_quantity(
        price=5_000.0, stop_loss=4_750.0, portfolio_value=10_000.0, available_cash=1_000.0
    )
    assert quantity == 0
    assert "below 1 share" in note


# --------------------------------------------------------- pyramiding sizing --


def test_existing_exposure_shrinks_the_concentration_cap():
    """A second tranche must respect *total* exposure to the name, not just its own."""
    portfolio, price, stop = 1_000_000.0, 100.0, 99.5  # tight stop -> concentration binds

    fresh_qty, _ = calculate_quantity(price, stop, portfolio, available_cash=portfolio)
    already_committed = fresh_qty * price  # pretend the first tranche used the whole cap

    second_qty, note = calculate_quantity(
        price, stop, portfolio, available_cash=portfolio, existing_exposure=already_committed
    )

    assert second_qty < fresh_qty
    assert "concentration" in note


def test_exposure_at_the_cap_leaves_no_room_for_another_tranche():
    portfolio, price, stop = 1_000_000.0, 100.0, 99.5
    max_by_concentration = (portfolio * settings.MAX_POSITION_PCT) / price
    at_the_cap = max_by_concentration * price  # exactly the rupee cap, already spent

    quantity, note = calculate_quantity(
        price, stop, portfolio, available_cash=portfolio, existing_exposure=at_the_cap
    )
    assert quantity == 0
    assert "below 1 share" in note


def test_existing_exposure_never_produces_a_negative_cap():
    """Exposure larger than the cap (e.g. price moved) must floor at zero, not go negative."""
    portfolio, price, stop = 1_000_000.0, 100.0, 99.5
    absurdly_large_exposure = portfolio * 10

    quantity, _ = calculate_quantity(
        price, stop, portfolio, available_cash=portfolio, existing_exposure=absurdly_large_exposure
    )
    assert quantity == 0


# ------------------------------------------------------ cross-sectional ranking --


def test_rank_buy_candidates_orders_strongest_first():
    ranked = rank_buy_candidates([(1, 0.55), (2, 0.71), (3, 0.63)])
    assert [inst_id for inst_id, _ in ranked] == [2, 3, 1]


def test_rank_buy_candidates_empty_list():
    assert rank_buy_candidates([]) == []


def test_rank_buy_candidates_single_candidate():
    assert rank_buy_candidates([(1, 0.6)]) == [(1, 0.6)]


def test_rank_buy_candidates_ties_keep_original_order():
    """A stable sort: two candidates at the same confidence must not shuffle
    on every scan — whichever was evaluated first among equals stays first."""
    ranked = rank_buy_candidates([(1, 0.6), (2, 0.6), (3, 0.6)])
    assert [inst_id for inst_id, _ in ranked] == [1, 2, 3]


def test_rank_buy_candidates_all_same_confidence_preserves_count():
    ranked = rank_buy_candidates([(1, 0.5), (2, 0.5)])
    assert len(ranked) == 2
    assert {inst_id for inst_id, _ in ranked} == {1, 2}
