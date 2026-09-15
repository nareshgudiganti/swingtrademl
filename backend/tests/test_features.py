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
            # Wide enough that an 8%/4% barrier can genuinely be touched
            # intrabar. At the old +/-0.5% these tests could not tell a
            # working barrier label from a broken one.
            "high": close * (1 + np.abs(rng.normal(0.02, 0.012, n))),
            "low": close * (1 - np.abs(rng.normal(0.02, 0.012, n))),
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


def _barrier_frame(bars: list[tuple[float, float, float]]) -> pd.DataFrame:
    """A hand-built OHLC frame: one (close, high, low) per bar.

    Deterministic by construction — the barrier rules below are about which
    side is touched first, and that cannot be asserted against random data.
    """
    return pd.DataFrame(
        {
            "ts": pd.date_range("2024-01-01", periods=len(bars), freq="D", tz="UTC"),
            "open": [b[0] for b in bars],
            "high": [b[1] for b in bars],
            "low": [b[2] for b in bars],
            "close": [b[0] for b in bars],
            "volume": [100_000.0] * len(bars),
        }
    )


# Every case starts at close 100, so the barriers sit at 108 and 96.
FLAT = (100.0, 100.5, 99.5)


def test_label_is_a_win_when_the_target_is_touched_first():
    labelled = build_label(
        _barrier_frame([FLAT, (100.0, 109.0, 99.0), (100.0, 100.0, 90.0), FLAT]),
        horizon_days=3, target_return=0.08, stop_return=0.04,
    )
    assert labelled["target"].iloc[0] == 1


def test_label_is_a_loss_when_the_stop_is_touched_first():
    """The failure the old close-only label could not see: price falls through
    the stop, then recovers past the target inside the same window."""
    labelled = build_label(
        _barrier_frame([FLAT, (100.0, 100.0, 95.0), (100.0, 109.0, 100.0), FLAT]),
        horizon_days=3, target_return=0.08, stop_return=0.04,
    )
    assert labelled["target"].iloc[0] == 0


def test_a_same_bar_touch_of_both_barriers_scores_as_a_stop():
    """A daily bar cannot say which side was hit first, so the pessimistic
    reading wins — matching evaluate_pending_signals."""
    labelled = build_label(
        _barrier_frame([FLAT, (100.0, 109.0, 95.0), FLAT, FLAT]),
        horizon_days=3, target_return=0.08, stop_return=0.04,
    )
    assert labelled["target"].iloc[0] == 0


def test_a_touch_after_the_horizon_does_not_count():
    labelled = build_label(
        _barrier_frame([FLAT, FLAT, FLAT, FLAT, (100.0, 120.0, 99.0)]),
        horizon_days=3, target_return=0.08, stop_return=0.04,
    )
    assert labelled["target"].iloc[0] == 0


def test_label_drops_the_unresolved_tail(
    ohlcv, index_ohlcv, sector_ohlcv, vix_ohlcv, breadth_df
):
    horizon = 15
    labelled = build_label(
        build_features(ohlcv, index_ohlcv, sector_ohlcv, vix_ohlcv, breadth_df),
        horizon_days=horizon, target_return=0.08, stop_return=0.04,
    )

    # The final `horizon` rows have no knowable outcome and must be removed —
    # including any that resolved early, since keeping only those would bias
    # the tail toward fast movers.
    assert len(labelled) == len(ohlcv) - horizon
    assert set(labelled["target"].unique()) == {0, 1}, "fixture must produce both classes"


def test_forward_return_is_not_the_target(
    ohlcv, index_ohlcv, sector_ohlcv, vix_ohlcv, breadth_df
):
    """`forward_return` is carried for diagnostics and is close-to-close at the
    horizon. It is NOT what `target` measures, and the two must be free to
    disagree — that disagreement is the entire reason for the barrier label."""
    horizon = 15
    labelled = build_label(
        build_features(ohlcv, index_ohlcv, sector_ohlcv, vix_ohlcv, breadth_df),
        horizon_days=horizon, target_return=0.08, stop_return=0.04,
    )

    row = labelled.iloc[100]
    expected = ohlcv["close"].iloc[115] / ohlcv["close"].iloc[100] - 1
    assert row["forward_return"] == pytest.approx(expected, rel=1e-9)

    naive = (labelled["forward_return"] >= 0.08).astype(int)
    assert (naive != labelled["target"]).any(), (
        "a barrier label that always agrees with the close-only label is not "
        "applying the lower barrier"
    )


def test_zero_horizon_is_rejected():
    with pytest.raises(ValueError):
        build_label(_barrier_frame([FLAT, FLAT]), horizon_days=0)


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
