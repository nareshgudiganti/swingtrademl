"""M14 portfolio brain: correlation, concentration, ordering, what-if."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from swing_trade_ml.brain.modules.m14_portfolio.correlation import close_pairs, concentration, correlations


def _dated(values, start="2026-01-01") -> pd.Series:
    return pd.Series(np.asarray(values, dtype=float), index=pd.bdate_range(start, periods=len(values)).date)


def _walk(seed, n=120):
    rng = np.random.default_rng(seed)
    return 100 * np.cumprod(1 + rng.normal(0, 0.01, n))


def test_twins_correlate_and_strangers_do_not():
    a = _walk(1)
    closes = {"A": _dated(a), "TWIN": _dated(a * 1.5), "OTHER": _dated(_walk(2))}
    corr = correlations(closes)
    assert corr.loc["A", "TWIN"] == pytest.approx(1.0)
    assert abs(corr.loc["A", "OTHER"]) < 0.3
    assert close_pairs(corr) == [("A", "TWIN", pytest.approx(1.0))]


def test_only_the_last_60_days_count():
    a, b = _walk(3, 200), _walk(4, 200)
    b[-61:] = a[-61:] * (b[-62] / a[-62])  # identical moves for the last 60 days only
    corr = correlations({"A": _dated(a), "B": _dated(b)})
    assert corr.loc["A", "B"] == pytest.approx(1.0)


def test_too_little_overlap_claims_nothing():
    corr = correlations({"A": _dated(_walk(5)), "NEW": _dated(_walk(5)[:30], start="2026-05-01")})
    assert np.isnan(corr.loc["A", "NEW"])
    assert close_pairs(corr) == []


def test_concentration_names_the_largest_position_and_sector():
    values = {"HDFCBANK": 40_000.0, "ICICIBANK": 30_000.0, "TCS": 10_000.0}
    c = concentration(values, portfolio_value=200_000.0)
    assert c["largest_position"] == ("HDFCBANK", pytest.approx(0.20))
    assert c["top_sector"] == ("BANK", pytest.approx(0.35))
