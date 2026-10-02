"""M05 memory: past cases (outcome, key, when it was known) and recall."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from swing_trade_ml.brain.modules.m05_memory.cases import barrier_outcomes, build_cases, state_keys
from swing_trade_ml.brain.modules.m05_memory.recall import recall


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


# --- recall ------------------------------------------------------------------------------------

KEY = {"market": "correction", "stock": "down", "trend": "falling", "vol": "normal"}
AS_OF = date(2026, 9, 1)


def _cases(n, outcome="target", known=AS_OF - timedelta(days=1), **key):
    k = {**KEY, **key}
    ret = {"target": 0.08, "stop": -0.04, "timeout": 0.01}[outcome]
    return pd.DataFrame(
        {
            "symbol": "X",
            "day": [known - timedelta(days=20)] * n,
            **{part: [v] * n for part, v in k.items()},
            "outcome": [outcome] * n,
            "exit_return": [ret] * n,
            "days": [9] * n,
            "outcome_day": [known] * n,
            "path_day": [known] * n,
            "path": [[0.005 * (d + 1) for d in range(15)]] * n,
        }
    )


def test_the_hit_rate_band_and_days_of_exact_matches():
    cases = pd.concat([_cases(12, "target"), _cases(22, "stop"), _cases(6, "timeout")])
    r = recall(cases, "ABC", KEY, AS_OF)
    assert r.n_similar == 40 and r.hit_rate == pytest.approx(0.3) and r.widened == ()
    assert r.median_return == pytest.approx(-0.04) and (r.p25, r.p75) == (
        pytest.approx(-0.04),
        pytest.approx(0.08),
    )
    assert r.median_days == 9
    assert r.typical_path[0] == (1, pytest.approx(0.005), pytest.approx(0.005), pytest.approx(0.005))


def test_cases_not_known_by_as_of_are_excluded():
    cases = pd.concat([_cases(40, "stop"), _cases(40, "target", known=AS_OF + timedelta(days=3))])
    r = recall(cases, "ABC", KEY, AS_OF)
    assert r.n_similar == 40 and r.hit_rate == 0.0


def test_widening_drops_volatility_then_market_and_says_so():
    other_vol = _cases(25, "target", vol="high")
    exact = _cases(10, "stop")
    r = recall(pd.concat([exact, other_vol]), "ABC", KEY, AS_OF)
    assert r.widened == ("volatility",) and r.n_similar == 35
    other_market = _cases(30, "target", vol="high", market="up-trend")
    r2 = recall(pd.concat([_cases(5, "stop"), other_market]), "ABC", KEY, AS_OF)
    assert r2.widened == ("volatility", "market") and r2.n_similar == 35


def test_too_few_cases_even_widened_is_reported_as_is():
    r = recall(_cases(7, "target"), "ABC", KEY, AS_OF)
    assert r.n_similar == 7 and r.widened == ("volatility", "market", "trend")


def test_no_cases_at_all_is_an_empty_recall():
    r = recall(_cases(0), "ABC", KEY, AS_OF)
    assert r.n_similar == 0 and r.hit_rate is None


def test_recall_also_reports_the_honest_figures():
    """46 unseen months: memory's distance from the average came true only
    about a quarter of the time, so the honest figure keeps a quarter of it."""
    similar = pd.concat([_cases(12, "target"), _cases(22, "stop"), _cases(6, "timeout")])
    others = _cases(160, "timeout", stock="up", trend="flat")  # everything else, for the base rate
    r = recall(pd.concat([similar, others]), "ABC", KEY, AS_OF)
    base_hit = 12 / 200
    assert r.hit_rate == pytest.approx(0.3)
    assert r.honest_hit_rate == pytest.approx(base_hit + 0.25 * (0.3 - base_hit))
    mean_similar = (12 * 0.08 - 22 * 0.04 + 6 * 0.01) / 40
    base_mean = (12 * 0.08 - 22 * 0.04 + 166 * 0.01) / 200
    assert r.mean_return == pytest.approx(mean_similar)
    assert r.honest_mean_return == pytest.approx(base_mean + 0.25 * (mean_similar - base_mean))
