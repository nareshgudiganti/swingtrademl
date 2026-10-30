# ruff: noqa: E501, N812 (long test sentences, short P / F aliases as in the other h05 tests)
"""h05: the lane's training-basis inputs are checked against the feature code AS IT WAS, not only against scaler statistics.

`fixtures/features_before_fcaef35.py.txt` is `ml/features.py` exactly as committed in the parent of fcaef35
(2026-10-05), the last version that used the old obv_slope formula (git blob d2f723d1b0ba...). It needs only
numpy and pandas. The test runs that old code and today's code on the same candles and requires:
  * every input except obv_slope is identical (nothing else about the serving path changed for these models);
  * today's code with the old obv_slope formula put back reproduces the old code's obv_slope, so the lane's
    'training basis' inputs ARE the historical inputs;
  * today's own obv_slope is different, so the production-path score really is a different input.
"""

from __future__ import annotations

import hashlib
import types
from pathlib import Path

import numpy as np
import pandas as pd

from swing_trade_ml.brain.lanes import h05_features as F
from swing_trade_ml.ml.features import FEATURE_COLUMNS, build_features

SNAPSHOT = Path(__file__).parent / "fixtures" / "features_before_fcaef35.py.txt"
SNAPSHOT_SHA256 = "d39f91019d267884f1a80f3ba0db0560e869d0ac3fedbf068a09d3aeb2ac3655"
GIT_BLOB = "d2f723d1b0bafe548f83d0b0c4715ef02dd2f4a2"  # git rev-parse fcaef35~1:backend/src/swing_trade_ml/ml/features.py


def _historical():
    raw = SNAPSHOT.read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(raw).hexdigest() == SNAPSHOT_SHA256, "the historical snapshot was edited"
    module = types.ModuleType("features_before_fcaef35")
    exec(compile(raw.decode("utf-8"), str(SNAPSHOT), "exec"), module.__dict__)
    return module


def _ohlcv(seed: int, n: int = 520, start: str = "2024-01-01") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.014, n)))
    open_ = close * (1 + rng.normal(0, 0.004, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.006, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.006, n)))
    return pd.DataFrame(
        {
            "ts": pd.bdate_range(start, periods=n, tz="UTC"),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.integers(50_000, 900_000, n).astype(float),
        }
    )


def _context():
    index_df, sector_df = _ohlcv(101), _ohlcv(202)
    vix = _ohlcv(303)[["ts", "close"]].assign(close=lambda d: 12 + d["close"] / 20)
    ts = index_df["ts"]
    breadth = pd.DataFrame(
        {
            "ts": ts,
            "breadth_pct_above_sma50": np.linspace(30, 70, len(ts)),
            "breadth_advance_pct": np.linspace(40, 60, len(ts)),
        }
    )
    return index_df, sector_df, vix, breadth


def test_the_snapshot_is_the_committed_historical_file():
    assert hashlib.sha1(b"blob " + str(SNAPSHOT.stat().st_size).encode() + b"\0" + SNAPSHOT.read_bytes()).hexdigest() == GIT_BLOB


def test_lane_inputs_equal_the_historical_feature_code_except_where_the_formula_changed():
    old = _historical()
    stock = _ohlcv(7)
    ctx = _context()
    then = old.build_features(stock, *ctx)
    now = build_features(stock, *ctx).copy()

    shared = [c for c in FEATURE_COLUMNS if c in old.FEATURE_COLUMNS and c != "obv_slope"]
    assert len(shared) >= 37
    for col in shared:
        pd.testing.assert_series_equal(then[col], now[col], check_names=False, obj=col)

    # today's own obv_slope is a different input
    both = pd.concat([then["obv_slope"], now["obv_slope"]], axis=1).dropna()
    assert len(both) > 100
    assert not np.allclose(both.iloc[:, 0], both.iloc[:, 1])

    # the lane's training-basis formula reproduces the historical one on the same candles
    lane = F.old_obv_slope(stock["close"].astype(float), stock["volume"].astype(float))
    pd.testing.assert_series_equal(then["obv_slope"], lane, check_names=False)


def test_a_saved_scaler_sees_the_same_inputs_from_the_historical_code_and_the_lane():
    """Same candles, same model: the score from the historical code and from the lane's inputs is identical."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    old = _historical()
    stock = _ohlcv(11)
    ctx = _context()
    names = [c for c in FEATURE_COLUMNS if c in old.FEATURE_COLUMNS][:37]
    then = old.build_features(stock, *ctx)[names].dropna()
    now = build_features(stock, *ctx).copy()
    now["obv_slope"] = F.old_obv_slope(stock["close"].astype(float), stock["volume"].astype(float)).to_numpy()
    now = now[names].loc[then.index]

    scaler = StandardScaler().fit(then.to_numpy(float))
    y = (np.arange(len(then)) % 3 == 0).astype(int)
    model = LogisticRegression(max_iter=300).fit(scaler.transform(then.to_numpy(float)), y)
    a = model.predict_proba(scaler.transform(then.to_numpy(float)))[:, 1]
    b = model.predict_proba(scaler.transform(now.to_numpy(float)))[:, 1]
    assert np.array_equal(a, b)
