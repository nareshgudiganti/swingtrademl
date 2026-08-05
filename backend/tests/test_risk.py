"""Position sizing tests — the arithmetic that bounds every loss."""

from __future__ import annotations

import pytest

from swing_trade_ml.core.config import settings
from swing_trade_ml.services.risk import calculate_quantity


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
