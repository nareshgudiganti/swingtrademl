"""Feature engineering tests.

The lookahead test is the important one — a leak there silently invalidates
every backtest and paper result the system will ever produce.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from swing_trade_ml.ml.features import (
    FEATURE_COLUMNS,
    build_features,
    build_label,
    latest_feature_row,
    rsi,
)


def _synthetic_ohlcv(seed: int, n: int = 400) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.cumprod(1 + rng.normal(0.0005, 0.015, n))
    return pd.DataFrame(
        {
            "ts": pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC"),
            "open": close * (1 + rng.normal(0, 0.003, n)),
            "high": close * (1 + np.abs(rng.normal(0.005, 0.004, n))),
            "low": close * (1 - np.abs(rng.normal(0.005, 0.004, n))),
            "close": close,
            "volume": rng.integers(100_000, 1_000_000, n).astype(float),
        }
    )


@pytest.fixture
def ohlcv() -> pd.DataFrame:
    """400 bars of a synthetic uptrend with noise — enough to warm every window."""
    return _synthetic_ohlcv(seed=42)


@pytest.fixture
def index_ohlcv() -> pd.DataFrame:
    """A second, independent synthetic series standing in for the benchmark
    index — same date range as `ohlcv`, different seed."""
    return _synthetic_ohlcv(seed=7)


@pytest.fixture
def sector_ohlcv() -> pd.DataFrame:
    """A third independent synthetic series standing in for a stock's own
    sector index — same date range, its own seed."""
    return _synthetic_ohlcv(seed=13)


@pytest.fixture
def vix_ohlcv() -> pd.DataFrame:
    """A fourth independent synthetic series standing in for INDIA VIX."""
    return _synthetic_ohlcv(seed=21)


@pytest.fixture
def breadth_df(ohlcv) -> pd.DataFrame:
    """A synthetic market-breadth series over the same date range as `ohlcv`
    — only `ts` needs to align with the stock frame; the two fraction columns
    are otherwise independent of any single stock's own price."""
    rng = np.random.default_rng(99)
    n = len(ohlcv)
    return pd.DataFrame(
        {
            "ts": ohlcv["ts"],
            "breadth_pct_above_sma50": rng.uniform(0, 1, n),
            "breadth_advance_pct": rng.uniform(0, 1, n),
        }
    )


def test_all_declared_features_are_produced(ohlcv, index_ohlcv, sector_ohlcv, vix_ohlcv, breadth_df):
    result = build_features(ohlcv, index_ohlcv, sector_ohlcv, vix_ohlcv, breadth_df)
    missing = set(FEATURE_COLUMNS) - set(result.columns)
    assert not missing, f"build_features did not produce: {sorted(missing)}"


def test_build_features_requires_context_frames(ohlcv):
    """The fail-loud contract: a forgotten context frame must error
    immediately at the call, not degrade into silently-NaN market-context
    columns."""
    with pytest.raises(TypeError):
        build_features(ohlcv)


def test_features_warm_up_and_then_have_no_nans(ohlcv, index_ohlcv, sector_ohlcv, vix_ohlcv, breadth_df):
    result = build_features(ohlcv, index_ohlcv, sector_ohlcv, vix_ohlcv, breadth_df)
    # The 252-period 52-week high is the longest window; everything after it
    # should be fully populated.
    tail = result.iloc[300:][FEATURE_COLUMNS]
    assert not tail.isna().to_numpy().any(), "NaNs remain after the warm-up period"


def test_features_do_not_use_future_data(ohlcv, index_ohlcv, sector_ohlcv, vix_ohlcv, breadth_df):
    """Truncating the series must not change features on the bars that remain.

    If any indicator peeked ahead, the last rows of the truncated frame would
    differ from the same rows computed with the full series.
    """
    full = build_features(ohlcv, index_ohlcv, sector_ohlcv, vix_ohlcv, breadth_df)
    truncated = build_features(
        ohlcv.iloc[:350], index_ohlcv.iloc[:350], sector_ohlcv.iloc[:350],
        vix_ohlcv.iloc[:350], breadth_df.iloc[:350],
    )

    overlap = truncated.iloc[300:350][FEATURE_COLUMNS].reset_index(drop=True)
    reference = full.iloc[300:350][FEATURE_COLUMNS].reset_index(drop=True)

    pd.testing.assert_frame_equal(overlap, reference, atol=1e-9, check_dtype=False)


def test_rsi_is_bounded(ohlcv):
    values = rsi(ohlcv["close"], 14).dropna()
    assert values.between(0, 100).all()


def test_label_is_forward_looking_and_drops_unknown_tail(
    ohlcv, index_ohlcv, sector_ohlcv, vix_ohlcv, breadth_df
):
    horizon = 5
    labelled = build_label(
        build_features(ohlcv, index_ohlcv, sector_ohlcv, vix_ohlcv, breadth_df),
        horizon_days=horizon, target_return=0.02,
    )

    # The final `horizon` rows have no known outcome and must be removed.
    assert len(labelled) == len(ohlcv) - horizon
    assert set(labelled["target"].unique()) <= {0, 1}

    # Spot-check the label against the raw prices it is derived from.
    row = labelled.iloc[100]
    expected_return = ohlcv["close"].iloc[105] / ohlcv["close"].iloc[100] - 1
    assert row["forward_return"] == pytest.approx(expected_return, rel=1e-9)
    assert row["target"] == int(expected_return >= 0.02)


def test_latest_feature_row_returns_none_when_not_warmed_up(
    ohlcv, index_ohlcv, sector_ohlcv, vix_ohlcv, breadth_df
):
    assert (
        latest_feature_row(
            ohlcv.iloc[:50], index_ohlcv.iloc[:50], sector_ohlcv.iloc[:50],
            vix_ohlcv.iloc[:50], breadth_df.iloc[:50],
        )
        is None
    )

    row = latest_feature_row(ohlcv, index_ohlcv, sector_ohlcv, vix_ohlcv, breadth_df)
    assert row is not None
    assert list(row.columns) == FEATURE_COLUMNS
    assert len(row) == 1
