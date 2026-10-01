"""M06's offline trainer on synthetic data: the unseen-window split, monthly
walk-forward without peeking ahead, calibration buckets, and honest adoption."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from swing_trade_ml.brain.modules.m06_reason.trainer import (
    META_INPUTS,
    Combiner,
    calibration_buckets,
    evaluate,
    monthly_folds,
    unseen_rows,
)


def _frame(n_months: int = 10, per_month: int = 400, signal: float = 1.0, seed: int = 3) -> pd.DataFrame:
    """Synthetic stock-days where the barrier score carries real information,
    and breadth adds a little more."""
    rng = np.random.default_rng(seed)
    n = n_months * per_month
    days = pd.bdate_range("2025-11-03", periods=n_months * 21)
    day = rng.choice(days, n)
    p_barrier = rng.uniform(0.05, 0.45, n)
    breadth = rng.uniform(0.1, 0.9, n)
    logit = -1.7 + signal * 4 * (p_barrier - 0.2) + 0.8 * (breadth - 0.5)
    y = rng.uniform(0, 1, n) < 1 / (1 + np.exp(-logit))
    frame = pd.DataFrame(
        {
            "day": pd.to_datetime(day),
            "symbol": rng.choice(["A", "B", "C"], n),
            "p_barrier": p_barrier,
            "p_swing": np.clip(p_barrier + rng.normal(0, 0.1, n), 0.01, 0.99),
            "nifty_trend_regime": rng.choice([-1.0, 1.0], n),
            "breadth_pct_above_sma50": breadth,
            "vix_percentile_rank": rng.uniform(0, 1, n),
            "relative_strength_20d": rng.normal(0, 0.05, n),
            "high_52w_dist": rng.uniform(-0.4, 0, n),
            "sector_trend_regime": rng.choice([-1.0, 1.0], n),
            "target": y.astype(int),
        }
    )
    return frame.sort_values("day").reset_index(drop=True)


# --- the unseen window -----------------------------------------------------------


def test_rows_inside_the_training_window_or_its_purge_are_dropped():
    days = pd.bdate_range("2025-09-01", "2025-12-31")
    frame = pd.DataFrame({"day": days, "target": 0})
    kept = unseen_rows(frame, train_end=pd.Timestamp("2025-10-08"), purge_days=15)
    assert kept["day"].min() > pd.Timestamp("2025-10-08") + pd.tseries.offsets.BDay(14)
    assert len(kept) == len(frame[frame["day"] > pd.Timestamp("2025-10-08") + pd.tseries.offsets.BDay(15)])


# --- walk-forward ---------------------------------------------------------------


def test_folds_never_train_on_or_after_the_test_month():
    frame = _frame()
    folds = monthly_folds(frame, min_train_months=3)
    assert len(folds) == 7
    for train_idx, test_idx in folds:
        assert frame.loc[train_idx, "day"].max() < frame.loc[test_idx, "day"].min()


def test_too_little_history_gives_no_folds():
    assert monthly_folds(_frame(n_months=3), min_train_months=3) == []


# --- calibration buckets ------------------------------------------------------------


def test_calibration_buckets_compare_promised_with_actual():
    p = np.array([0.15] * 100 + [0.35] * 100)
    y = np.array([1] * 15 + [0] * 85 + [1] * 30 + [0] * 70)
    buckets = calibration_buckets(p, y, edges=(0.0, 0.2, 0.4, 1.0))
    assert buckets[0] == {
        "low": 0.0,
        "high": 0.2,
        "n": 100,
        "mean_p": pytest.approx(0.15),
        "actual": pytest.approx(0.15),
    }
    assert buckets[1]["actual"] == pytest.approx(0.30)


# --- evaluation and adoption -------------------------------------------------------


def test_the_meta_model_is_adopted_when_it_beats_calibration():
    report = evaluate(_frame(signal=1.0))
    assert set(report["candidates"]) == {"raw_barrier", "calibrated_barrier", "meta"}
    assert report["chosen"] == "meta"
    assert report["candidates"]["meta"]["brier"] < report["candidates"]["calibrated_barrier"]["brier"]
    assert report["n_test_rows"] > 0 and report["folds"] == 7


def test_calibration_is_chosen_when_the_meta_model_does_not_help():
    frame = _frame(signal=1.0)
    frame["breadth_pct_above_sma50"] = 0.5  # remove the extra information
    report = evaluate(frame, prefer_simpler_margin=0.002)
    assert report["chosen"] == "calibrated_barrier"
    assert "did not beat" in report["why"]


def test_a_fitted_combiner_gives_probabilities_between_0_and_1():
    frame = _frame()
    combiner = Combiner.fit(frame, kind="meta")
    p = combiner.predict(frame.head(50))
    assert ((p > 0) & (p < 1)).all() and combiner.inputs == list(META_INPUTS)
    cal = Combiner.fit(frame, kind="calibrated_barrier")
    assert ((cal.predict(frame.head(50)) >= 0) & (cal.predict(frame.head(50)) <= 1)).all()
