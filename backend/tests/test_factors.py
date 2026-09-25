"""Factor scoring — cross-sectional percentile ranks over one day's universe."""

from __future__ import annotations

import pandas as pd
import pytest

from swing_trade_ml.services.factors import (
    AVAILABLE_FACTORS,
    STUBBED_FACTORS,
    composite_score,
    factor_scores,
    percentile_rank,
)


def test_percentile_rank_spreads_over_0_to_100():
    ranked = percentile_rank(pd.Series([1.0, 2.0, 3.0, 4.0]))
    assert ranked.min() == pytest.approx(25.0)
    assert ranked.max() == pytest.approx(100.0)


def test_single_stock_universe_scores_without_error():
    """A one-row universe must produce a valid score, not a division error."""
    ranked = percentile_rank(pd.Series([42.0]))
    assert ranked.tolist() == [100.0]


def test_all_identical_values_rank_equal_and_are_not_nan():
    ranked = percentile_rank(pd.Series([5.0, 5.0, 5.0]))
    assert ranked.notna().all()
    assert ranked.nunique() == 1


def test_low_volatility_inverts_so_calm_stocks_rank_higher():
    frame = pd.DataFrame(
        {
            "volatility_20": [0.10, 0.50],
            "atr_14_pct": [0.01, 0.05],
            "volatility_percentile_rank": [0.10, 0.90],
        },
        index=["CALM", "WILD"],
    )
    scores = factor_scores(frame)
    assert scores.loc["CALM", "low_volatility"] > scores.loc["WILD", "low_volatility"]


def test_trend_rewards_the_stronger_uptrend():
    frame = pd.DataFrame(
        {
            "sma_50_ratio": [1.10, 0.90], "sma_200_ratio": [1.20, 0.85],
            "sma_50_200_cross": [1, 0], "adx_14": [35.0, 12.0],
            "trend_strength": [0.8, 0.1], "relative_strength_20d": [0.05, -0.04],
            "return_20d": [0.08, -0.06], "return_120d": [0.30, -0.10],
            "return_250d": [0.50, -0.20],
        },
        index=["STRONG", "WEAK"],
    )
    scores = factor_scores(frame)
    assert scores.loc["STRONG", "trend"] > scores.loc["WEAK", "trend"]


def test_composite_renormalises_weights_of_enabled_factors_only():
    """Disabling a factor redistributes its weight rather than shrinking
    every score toward zero."""
    scores = pd.DataFrame({"trend": [80.0, 40.0]}, index=["A", "B"])
    composite = composite_score(scores, {"trend": 70, "low_volatility": 30})
    assert composite.tolist() == pytest.approx([80.0, 40.0])


def test_composite_blends_two_factors_by_weight():
    scores = pd.DataFrame(
        {"trend": [100.0, 0.0], "low_volatility": [0.0, 100.0]}, index=["A", "B"]
    )
    composite = composite_score(scores, {"trend": 75, "low_volatility": 25})
    assert composite["A"] == pytest.approx(75.0)
    assert composite["B"] == pytest.approx(25.0)


def test_zero_total_weight_raises_rather_than_dividing_by_zero():
    scores = pd.DataFrame({"trend": [50.0]}, index=["A"])
    with pytest.raises(ValueError, match="at least one factor"):
        composite_score(scores, {"trend": 0})


def test_value_and_quality_are_stubbed_not_available():
    assert AVAILABLE_FACTORS == frozenset({"trend", "low_volatility"})
    assert set(STUBBED_FACTORS) == {"value", "quality", "size"}
    for reason in STUBBED_FACTORS.values():
        assert reason


def test_missing_input_column_is_skipped_not_fatal():
    """A frame without return_250d still scores trend on its other inputs."""
    frame = pd.DataFrame(
        {"sma_50_ratio": [1.1, 0.9], "adx_14": [30.0, 10.0]}, index=["A", "B"]
    )
    scores = factor_scores(frame)
    assert scores.loc["A", "trend"] > scores.loc["B", "trend"]
