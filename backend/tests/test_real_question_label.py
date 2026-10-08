"""The real trading question: +8% before -4% within 15 trading days.

Synthetic candles only, no database. Complements test_features.py (win, loss,
same-bar, after-horizon) with the horizon edge, no-look-ahead, default-profile
and opt-in calibration checks.
"""

from __future__ import annotations

import inspect

import numpy as np
import pandas as pd

from swing_trade_ml.core.config import settings
from swing_trade_ml.ml.calibrated_model import CalibratedEstimator, reliability_table
from swing_trade_ml.ml.features import build_label
from swing_trade_ml.ml.train import fit_and_score, train_model

FLAT = (100.0, 100.5, 99.5)


def _frame(bars):
    return pd.DataFrame(
        {
            "ts": pd.date_range("2024-01-01", periods=len(bars), freq="D", tz="UTC"),
            "open": [b[0] for b in bars],
            "high": [b[1] for b in bars],
            "low": [b[2] for b in bars],
            "close": [b[0] for b in bars],
            "volume": [1e5] * len(bars),
        }
    )


def test_real_rules_are_the_default_profile():
    assert (settings.ML_PREDICTION_HORIZON_DAYS, settings.ML_TARGET_RETURN_PCT,
            settings.ML_STOP_RETURN_PCT) == (15, 0.08, 0.04)
    params = inspect.signature(build_label).parameters
    assert (params["horizon_days"].default, params["target_return"].default,
            params["stop_return"].default) == (15, 0.08, 0.04)
    # Calibration is opt-in everywhere.
    assert inspect.signature(train_model).parameters["calibrate"].default is False
    assert inspect.signature(fit_and_score).parameters["calibrate"].default is False


def test_default_call_equals_explicit_real_rules():
    bars = [FLAT] * 3 + [(100.0, 109.0, 99.0)] + [FLAT] * 20
    a = build_label(_frame(bars))
    b = build_label(_frame(bars), 15, 0.08, 0.04)
    pd.testing.assert_frame_equal(a, b)


def test_touch_on_the_last_bar_of_the_window_counts_but_one_later_does_not():
    on_edge = [FLAT] * 15 + [(100.0, 109.0, 99.0)] + [FLAT] * 15
    late = [FLAT] * 16 + [(100.0, 109.0, 99.0)] + [FLAT] * 15
    assert build_label(_frame(on_edge)).iloc[0]["target"] == 1  # bar +15
    assert build_label(_frame(late)).iloc[0]["target"] == 0  # bar +16


def test_timeout_without_touching_either_barrier_is_a_loss_label():
    drift = [(100.0 + i * 0.1, 101.0 + i * 0.1, 99.5 + i * 0.1) for i in range(40)]
    labelled = build_label(_frame(drift))
    assert (labelled["target"] == 0).all()
    assert len(labelled) == 40 - 15


def test_stop_then_target_on_a_later_day_is_a_loss():
    bars = [FLAT, (100.0, 100.0, 95.0), (100.0, 115.0, 100.0)] + [FLAT] * 20
    assert build_label(_frame(bars)).iloc[0]["target"] == 0


def test_same_day_target_and_stop_is_a_stop():
    bars = [FLAT, (100.0, 110.0, 90.0)] + [FLAT] * 20
    assert build_label(_frame(bars)).iloc[0]["target"] == 0


def test_label_of_a_bar_ignores_everything_before_it_and_only_sees_next_15():
    base = [FLAT] * 5 + [(100.0, 109.0, 99.0)] + [FLAT] * 30
    changed_past = [(50.0, 51.0, 49.0)] * 3 + base[3:]
    changed_far_future = base[:25] + [(100.0, 300.0, 1.0)] * 10
    row = 4  # target touched at bar +2
    lab = build_label(_frame(base))
    assert build_label(_frame(changed_past)).iloc[row]["target"] == lab.iloc[row]["target"] == 1
    # Mutating bars beyond row+15 cannot move the label of an earlier row.
    assert build_label(_frame(changed_far_future)).iloc[row]["target"] == 1
    assert build_label(_frame(changed_far_future)).iloc[0]["target"] == lab.iloc[0]["target"]


def _toy(n=3000, seed=0):
    rng = np.random.default_rng(seed)
    from swing_trade_ml.ml.features import FEATURE_COLUMNS

    x = rng.normal(size=(n, len(FEATURE_COLUMNS)))
    p = 1 / (1 + np.exp(-(x[:, 0] * 1.5 - 1.2)))
    y = (rng.random(n) < p).astype(int)
    df = pd.DataFrame(x, columns=FEATURE_COLUMNS)
    df["target"] = y
    df["ts"] = pd.date_range("2022-01-01", periods=n, freq="h", tz="UTC")
    df["label_end_ts"] = df["ts"] + pd.Timedelta(hours=5)
    return df


def test_calibrated_fit_reports_reliability_and_serves_like_an_estimator():
    df = _toy()
    train, test = df.iloc[:2200], df.iloc[2200:]
    est, scaler, m = fit_and_score(train, test, "logistic_regression", calibrate=True)
    assert isinstance(est, CalibratedEstimator)
    assert m["calibration"]["method"] == "isotonic"
    assert sum(r["n"] for r in m["reliability"]) == len(test)
    x = test.drop(columns=["target", "ts", "label_end_ts"]).to_numpy()
    proba = est.predict_proba(scaler.transform(x))
    assert proba.shape == (len(test), 2)
    assert ((proba >= 0) & (proba <= 1)).all()


def test_uncalibrated_path_is_not_wrapped():
    df = _toy()
    est, _, m = fit_and_score(df.iloc[:2200], df.iloc[2200:], "logistic_regression")
    assert not isinstance(est, CalibratedEstimator)
    assert "calibration" not in m


def test_reliability_table_bands():
    y = np.array([1, 0, 1, 1])
    p = np.array([0.72, 0.75, 0.1, 0.95])
    rows = {r["band"]: r for r in reliability_table(y, p)}
    assert rows["0.70-0.80"]["n"] == 2 and rows["0.70-0.80"]["hit_rate"] == 0.5
    assert rows["0.80-1.00"]["n"] == 1
