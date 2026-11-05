"""Point-in-time / no-future-data audit of the EXISTING feature builder (ml/features.build_features), 53 inputs.

Read only: ml/features.py is imported, never edited. Synthetic tests always run; the real-data test is SELECT only
and is skipped when the local database cannot be reached. No model is fitted."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from swing_trade_ml.ml import feature_audit as fa
from swing_trade_ml.ml import sector_research as sr
from swing_trade_ml.ml.features import FEATURE_COLUMNS
from test_sector_research import STOCKS, inputs  # noqa: F401


def _days(inputs_, sym, n=14):
    d = sr._ist_date(inputs_.raw[sym]["ts"])
    return list(d.iloc[260 : len(d) - 10 : max(1, (len(d) - 280) // n)])


@pytest.mark.parametrize("sym", ["TCS", "HDFCBANK", "SUNPHARMA", "ASIANPAINT"])
def test_every_input_at_day_t_is_unchanged_when_later_data_is_removed(inputs, sym):  # noqa: F811
    res = fa.pit_check(inputs, sym, _days(inputs, sym))
    bad = {c: v for c, v in res.items() if v["mismatches"]}
    assert not bad, bad
    assert all(v["checked"] >= 10 for v in res.values())


@pytest.mark.parametrize("sym", ["TCS", "ASIANPAINT"])
def test_every_input_on_or_before_T_is_unchanged_when_all_later_data_is_wrecked(inputs, sym):  # noqa: F811
    d = sr._ist_date(inputs.raw[sym]["ts"])
    T = d.iloc[400]
    bad = {c: n for c, n in fa.mutation_check(inputs, sym, T).items() if n}
    assert not bad, bad
    # sanity: the mutation is real (inputs AFTER T do change), so the zero above is not vacuous
    wrecked = fa.mutation_check(inputs, sym, d.iloc[100])
    assert sum(wrecked.values()) == 0  # earlier cut also clean


def test_the_pit_check_detects_a_deliberately_leaking_builder(inputs, monkeypatch):  # noqa: F811
    """The test must be able to fail: a builder that looks one bar ahead is caught."""
    real = sr._existing_features

    def leaky(raw, inp, sym):
        out = real(raw, inp, sym)
        out["rsi_14"] = out["rsi_14"].shift(-1)  # tomorrow's value at today's row
        return out

    monkeypatch.setattr(sr, "_existing_features", leaky)
    res = fa.pit_check(inputs, "TCS", _days(inputs, "TCS"))
    assert res["rsi_14"]["mismatches"] > 0 and res["sma_20_ratio"]["mismatches"] == 0


def test_availability_counts_missing_rows_after_the_warmup(inputs):  # noqa: F811
    tab, per_stock = fa.availability(inputs, ["TCS", "HDFCBANK"])
    assert list(tab["input"]) == list(FEATURE_COLUMNS) and len(per_stock) == 2
    miss = tab[tab["missing_rows"] > 0]
    # rolling(252).rank over a 20-day volatility needs 271 sessions, so a few rows after the 252-row warm-up lack it
    assert (
        list(miss["input"]) == ["volatility_percentile_rank"] and int(miss["missing_rows"].iloc[0]) == 2 * 19
    )
    assert tab["rows_after_warmup"].iloc[0] > 0


def test_a_late_starting_vix_shows_up_as_missing_vix_rank(inputs):  # noqa: F811
    late = sr.ResearchInputs(
        raw=inputs.raw,
        index_df=inputs.index_df,
        index_frames=inputs.index_frames,
        vix_df=inputs.vix_df.iloc[200:].reset_index(drop=True),
        breadth_df=inputs.breadth_df,
    )
    tab, _ = fa.availability(late, ["TCS"])
    row = tab.set_index("input").loc["vix_percentile_rank"]
    assert row["missing_rows"] > 150 and row["first_valid_any_stock"] > "2024-12-01"


def test_overlap_reports_pearson_spearman_and_r2():
    rng = np.random.default_rng(0)
    n = 3000
    base = {c: rng.normal(size=n) for c in sr.FEATURE_COLUMNS}
    m = pd.DataFrame(base)
    m["sector_ret_10d_vs_nifty"] = m["sector_relative_strength_5d"] * 0.9 + rng.normal(0, 0.1, n)
    m["sector_rank_10d"] = rng.normal(size=n)
    m["stock_vs_sector_10d"] = rng.normal(size=n)
    o = fa.overlap(m)
    assert o["strongest_partner"]["sector_ret_10d_vs_nifty"][0][0] == "sector_relative_strength_5d"
    assert o["r2_on_sector_and_relative_inputs"]["sector_ret_10d_vs_nifty"] > 0.8
    assert o["r2_on_all_53"]["sector_rank_10d"] < 0.05
    assert set(o["r2_on_all_53"]) == set(sr.SECTOR_COLUMNS) and len(o["r2_on_all_53"]) == 3
    assert "sector_ret_20d_vs_nifty_minus_existing_difference" not in o  # the input was dropped (C_56)
    # the diagnostic is still available when someone passes the dropped column in
    m2 = m.assign(sector_ret_20d_vs_nifty=m["relative_strength_20d"] - m["sector_relative_strength_20d"])
    assert fa.overlap(m2)["sector_ret_20d_vs_nifty_minus_existing_difference"]["max_abs"] == 0.0


# ---- real local data, SELECT only
def test_existing_builder_is_point_in_time_on_real_local_data():
    pytest.importorskip("psycopg")
    syms = ["TCS", "RELIANCE", "MARUTI"]
    try:
        inp = sr.load_inputs_readonly(syms)
    except Exception as e:
        pytest.skip(f"local database not available: {type(e).__name__}")
    for sym in syms:
        d = sr._ist_date(inp.raw[sym]["ts"])
        if len(d) < 600:
            pytest.skip("local candles missing")
        res = fa.pit_check(inp, sym, list(d.iloc[300 : len(d) - 5 : 120]))
        bad = {c: v for c, v in res.items() if v["mismatches"]}
        assert not bad, (sym, bad)
