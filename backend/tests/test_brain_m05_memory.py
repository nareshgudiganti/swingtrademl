"""M05 memory: past cases (outcome, key, when it was known) and recall."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from swing_trade_ml.brain.modules.m05_memory.cases import barrier_outcomes, build_cases, state_keys


def _bars(close, spread=0.01, start="2024-01-01") -> pd.DataFrame:
    close = np.asarray(close, dtype=float)
    return pd.DataFrame(
        {
            "day": pd.bdate_range(start, periods=len(close)).date,
            "open": close,
            "high": close * (1 + spread),
            "low": close * (1 - spread),
            "close": close,
            "volume": 100_000.0,
        }
    )


def _rate(n, r):
    return 100 * (1 + r) ** np.arange(n)


def test_a_steady_rise_reaches_the_target_on_day_seven():
    out = barrier_outcomes(_bars(_rate(40, 0.01)))
    first = out.iloc[0]
    assert first["outcome"] == "target" and first["days"] == 7 and first["exit_return"] == pytest.approx(0.08)
    assert first["outcome_day"] == _bars(_rate(40, 0.01))["day"].iloc[7]
    assert len(first["path"]) == 15 and first["path"][0] == pytest.approx(0.01)


def test_a_steady_fall_hits_the_stop_first():
    first = barrier_outcomes(_bars(_rate(40, -0.01))).iloc[0]
    assert first["outcome"] == "stop" and first["days"] == 4 and first["exit_return"] == pytest.approx(-0.04)


def test_a_day_touching_both_barriers_counts_as_a_stop():
    bars = _bars(np.full(40, 100.0))
    bars.loc[3, "high"], bars.loc[3, "low"] = 109.0, 95.0
    assert barrier_outcomes(bars).iloc[0]["outcome"] == "stop"


def test_nothing_touched_is_a_timeout_with_the_day_15_return():
    first = barrier_outcomes(_bars(np.full(40, 100.0))).iloc[0]
    assert first["outcome"] == "timeout" and first["days"] == 15 and first["exit_return"] == 0.0
    assert first["outcome_day"] == first["path_day"]


def test_the_last_15_days_have_no_case():
    assert len(barrier_outcomes(_bars(_rate(40, 0.01)))) == 25


def test_state_keys_name_trend_volatility_and_the_stock_label():
    bars = _bars(_rate(260, 0.003))
    market = pd.Series("up-trend", index=bars["day"])
    keys = state_keys(bars, market)
    last = keys.iloc[-1]
    assert last["market"] == "up-trend" and last["stock"] == "up"
    assert last["trend"] == "rising" and last["vol"] == "normal"  # +6% in 20 days; 2% daily range
    assert keys["stock"].iloc[:199].isna().all()  # no 200-day average yet


def test_cases_join_keys_and_outcomes_and_skip_unwarmed_days():
    bars = _bars(_rate(260, 0.003))
    cases = build_cases("ABC", bars, pd.Series("up-trend", index=bars["day"]))
    assert set(cases["symbol"]) == {"ABC"} and len(cases) == 260 - 199 - 15
    assert {
        "day",
        "market",
        "stock",
        "trend",
        "vol",
        "outcome",
        "exit_return",
        "days",
        "outcome_day",
        "path_day",
        "path",
    } <= set(cases.columns)
