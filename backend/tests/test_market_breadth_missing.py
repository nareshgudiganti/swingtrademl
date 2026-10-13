"""Breadth must ignore stocks that have no value that day (late listing, warm-up,
missing bar) instead of counting them as 'below the average' or 'declined'."""

from __future__ import annotations

import numpy as np
import pandas as pd

from swing_trade_ml.ml.market_context import compute_breadth


def _wide() -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=120, freq="B")
    rng = np.random.default_rng(0)
    up = lambda: pd.Series(100 + np.cumsum(np.abs(rng.normal(0.5, 0.2, 120))), index=idx)  # noqa: E731
    a, b = up(), up()
    c = b.copy()
    c.iloc[:70] = np.nan  # listed late
    return pd.DataFrame({"A": a, "B": b, "C": c})


def test_late_listed_stock_is_not_counted_as_below_average():
    out = compute_breadth(_wide()).set_index("ts")
    day = _wide().index[60]  # C has no bar yet; A and B are always rising
    assert out.loc[day, "breadth_pct_above_sma50"] == 1.0
    assert out.loc[day, "breadth_advance_pct"] == 1.0


def test_stock_with_a_bar_is_counted_once_it_exists():
    wide = _wide()
    wide.loc[wide.index[100], "C"] = wide["C"].iloc[99] * 0.5  # C falls hard on day 100
    out = compute_breadth(wide).set_index("ts")
    assert abs(out.loc[wide.index[100], "breadth_advance_pct"] - 2 / 3) < 1e-9


def test_day_with_no_usable_stock_is_missing_not_zero():
    out = compute_breadth(_wide()).set_index("ts")
    assert np.isnan(out.iloc[10]["breadth_pct_above_sma50"])  # nobody has 50 bars yet
