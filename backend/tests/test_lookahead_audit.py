"""ps10 look-ahead audit (2026-10-20): the two gaps the existing truncation tests did not cover.

`test_features.test_features_do_not_use_future_data` cuts the stock AND every context series at the same
bar. In real use the market, sector, VIX and breadth series are often LONGER than one stock's (a stock
with a missing bar, a late listing, a replay day). These tests prove that newer context rows never change
a stock's past features, and that market breadth on a day uses no later day. The full audit is
docs/brain/evidence/lookahead-audit-2026-10-20.md.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from swing_trade_ml.ml.features import (
    FEATURE_COLUMNS,
    _index_context_frame,
    _vix_context_frame,
    build_features,
)
from swing_trade_ml.ml.market_context import compute_breadth
from test_features import _synthetic_ohlcv

CUT = 350  # the stock stops here; the context series run on to bar 400


def _context():
    stock = _synthetic_ohlcv(seed=42)
    index, sector, vix = (_synthetic_ohlcv(seed=s) for s in (7, 13, 21))
    rng = np.random.default_rng(99)
    breadth = pd.DataFrame(
        {
            "ts": stock["ts"],
            "breadth_pct_above_sma50": rng.uniform(0, 1, len(stock)),
            "breadth_advance_pct": rng.uniform(0, 1, len(stock)),
        }
    )
    return stock, index, sector, vix, breadth


GAP_DAYS = (320, 330, 340)  # days the stock traded but the market series have no row


def _without(frame: pd.DataFrame, rows) -> pd.DataFrame:
    return frame.drop(index=list(rows)).reset_index(drop=True)


def test_a_market_gap_is_filled_from_the_day_before_never_the_day_after():
    """The stock has a bar on GAP_DAYS; the index, sector, VIX and breadth series do not. That day's
    context must come from the latest earlier market day. A join that looked forward would take the
    next day's value (a leak that a plain truncation test cannot see when every series shares one
    calendar; checked 2026-10-20 by flipping the join to "forward")."""
    stock, index, sector, vix, breadth = _context()
    index, sector, vix, breadth = (_without(f, GAP_DAYS) for f in (index, sector, vix, breadth))
    out = build_features(stock.iloc[:CUT], index, sector, vix, breadth).set_index("ts")

    nifty = _index_context_frame(index, "nifty").set_index("ts")
    sect = _index_context_frame(sector, "sector").set_index("ts")
    vixc = _vix_context_frame(vix).set_index("ts")
    br = breadth.set_index("ts")
    for day in GAP_DAYS:
        ts = stock["ts"].iloc[day]
        before = stock["ts"].iloc[day - 1]  # the latest market day before the gap
        assert ts not in nifty.index and before in nifty.index
        for col, ctx in (
            ("nifty_volatility_20", nifty),
            ("sector_volatility_20", sect),
            ("vix_change_5d", vixc),
            ("breadth_pct_above_sma50", br),
        ):
            assert out.at[ts, col] == ctx.at[before, col], (day, col)


def test_newer_market_rows_never_change_a_stocks_past_features():
    stock, index, sector, vix, breadth = _context()
    cut = stock.iloc[:CUT]
    with_future = build_features(cut, index, sector, vix, breadth)
    with_cut = build_features(cut, index.iloc[:CUT], sector.iloc[:CUT], vix.iloc[:CUT], breadth.iloc[:CUT])
    pd.testing.assert_frame_equal(
        with_future[FEATURE_COLUMNS].iloc[300:],
        with_cut[FEATURE_COLUMNS].iloc[300:],
        atol=1e-9,
        check_dtype=False,
    )


def test_breadth_on_a_day_uses_no_later_day():
    rng = np.random.default_rng(5)
    days = pd.date_range("2024-01-01", periods=200, freq="B", tz="UTC")
    wide = pd.DataFrame(
        100 * np.exp(np.cumsum(rng.normal(0, 0.02, (len(days), 6)), axis=0)),
        index=days,
        columns=[f"S{i}" for i in range(6)],
    )
    wide.iloc[120:130, 2] = np.nan  # a stock with missing bars must not pull later values in either
    full = compute_breadth(wide)
    cut = compute_breadth(wide.iloc[:150])
    pd.testing.assert_frame_equal(full.iloc[:150].reset_index(drop=True), cut.reset_index(drop=True))


def test_the_calibration_step_trains_its_base_model_only_on_results_known_before_its_cut():
    """fit_and_score(calibrate=True) learns the base model on the earlier 75% of training dates and the
    calibration map on the rest. A base-model row whose 15-day result ends after that cut would let the
    calibration slice's outcomes leak into the base model; those rows must be left out."""
    from swing_trade_ml.ml.train import fit_and_score
    from test_real_question_label import _toy

    df = _toy()
    df["label_end_ts"] = df["ts"] + pd.Timedelta(hours=40)  # each result is known 40 rows later
    train, test = df.iloc[:2200], df.iloc[2200:]
    _, _, m = fit_and_score(train, test, "logistic_regression", calibrate=True)

    dates = train["ts"].drop_duplicates().sort_values().to_numpy()
    cut = dates[int(len(dates) * 0.75)]
    clean = int(((train["ts"] < cut) & (train["label_end_ts"] < cut)).sum())
    assert m["calibration"]["base_rows"] == clean
    assert clean < int((train["ts"] < cut).sum())  # some rows really were overlapping and left out
