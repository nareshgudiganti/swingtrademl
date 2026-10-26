"""How much of the account the market regime allows to be invested.

Owner-approved 2026-10-26: the stressed band went from 10% to 20%.
"""

from __future__ import annotations

from swing_trade_ml.services.deployable import BANDS, UNKNOWN_FRACTION, classify_deployable


def test_stressed_market_allows_twenty_percent():
    result = classify_deployable("bearish", volatility_level="elevated", breadth_above_sma50=0.25)
    assert result.regime == "stressed"
    assert result.fraction == 0.20


def test_bands_still_get_more_cautious_as_the_market_gets_worse():
    ordered = [BANDS[k] for k in ("stressed", "weak", "normal", "strong", "very_strong")]
    assert ordered == sorted(ordered)
    assert len(set(ordered)) == len(ordered)


def test_unreadable_trend_stays_on_the_weak_band():
    assert classify_deployable("unknown").fraction == UNKNOWN_FRACTION == BANDS["weak"]
