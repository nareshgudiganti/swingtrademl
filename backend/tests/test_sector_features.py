"""Sector inputs B1-5..B1-8: known answers, no look-ahead, gaps, rank, and training/serving parity."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from swing_trade_ml.ml import sector_features as sf

DATES = pd.bdate_range("2024-01-01", periods=60)
UNI = ["S_A", "S_B", "S_C", "S_D", "S_E", "S_F"]


def _series(values, dates=DATES):
    return pd.Series(np.asarray(values, dtype=float), index=dates)


def _geo(rate, start=100.0, n=len(DATES)):
    return _series(start * (1.0 + rate) ** np.arange(n))


def _world():
    nifty = _geo(0.001)
    # six sectors, growth rates strictly increasing with name
    sectors = {u: _geo(0.001 * (i + 1), 100.0 + i) for i, u in enumerate(UNI)}
    stock = _geo(0.004)
    return stock, nifty, sectors


def _build(stock, nifty, sectors, idx="S_C", **kw):
    return sf.build_sector_features(stock, nifty, sectors, idx, rank_universe=UNI, **kw)


# --- known answers ---
def test_known_answers_each_input():
    stock, nifty, sectors = _world()
    f = _build(stock, nifty, sectors, "S_C")
    t = DATES[30]
    sec = sectors["S_C"]
    exp10 = (sec[t] / sec[DATES[20]] - 1) - (nifty[t] / nifty[DATES[20]] - 1)
    exp20 = (sec[t] / sec[DATES[10]] - 1) - (nifty[t] / nifty[DATES[10]] - 1)
    exp_sv = (stock[t] / stock[DATES[20]] - 1) - (sec[t] / sec[DATES[20]] - 1)
    assert f.loc[t, sf.SECTOR_RET_10D] == pytest.approx(exp10)
    assert f.loc[t, sf.SECTOR_RET_20D] == pytest.approx(exp20)
    assert f.loc[t, sf.STOCK_VS_SECTOR_10D] == pytest.approx(exp_sv)
    # S_C is the 3rd weakest of 6 -> rank 2/5 = 0.4
    assert f.loc[t, sf.SECTOR_RANK_10D] == pytest.approx(0.4)


def test_warmup_is_missing_then_present():
    stock, nifty, sectors = _world()
    f = _build(stock, nifty, sectors)
    assert f[sf.SECTOR_RET_20D].iloc[: sf.LONG_WINDOW].isna().all()
    assert f[sf.SECTOR_RET_20D].iloc[sf.LONG_WINDOW :].notna().all()
    assert f[sf.SECTOR_RET_10D].iloc[: sf.SHORT_WINDOW].isna().all()
    assert f[sf.SECTOR_RET_10D].iloc[sf.SHORT_WINDOW :].notna().all()


# --- rank ---
def test_rank_strongest_weakest_and_range():
    stock, nifty, sectors = _world()
    t = DATES[40]
    assert _build(stock, nifty, sectors, "S_F").loc[t, sf.SECTOR_RANK_10D] == pytest.approx(1.0)
    assert _build(stock, nifty, sectors, "S_A").loc[t, sf.SECTOR_RANK_10D] == pytest.approx(0.0)


def test_rank_is_per_day_not_full_sample():
    """Rank on day t must not change when later days change dramatically."""
    stock, nifty, sectors = _world()
    base = _build(stock, nifty, sectors, "S_C")
    t = DATES[35]
    sectors2 = {k: v.copy() for k, v in sectors.items()}
    sectors2["S_A"].iloc[40:] *= 50.0  # S_A explodes after t
    again = _build(stock, nifty, sectors2, "S_C")
    assert again.loc[t, sf.SECTOR_RANK_10D] == base.loc[t, sf.SECTOR_RANK_10D]


def test_rank_missing_when_fewer_than_min_sectors():
    stock, nifty, sectors = _world()
    few = {k: sectors[k] for k in UNI[: sf.MIN_RANK_SECTORS - 1]}
    f = sf.build_sector_features(stock, nifty, few, "S_A", rank_universe=list(few))
    assert f[sf.SECTOR_RANK_10D].isna().all()
    assert f[sf.SECTOR_RET_10D].iloc[20:].notna().all()


def test_rank_ties_use_average():
    stock, nifty, sectors = _world()
    sectors["S_B"] = sectors["S_A"].copy()  # identical series
    f = _build(stock, nifty, sectors, "S_A")
    # A and B tie for weakest -> average rank 1.5 -> (1.5-1)/5 = 0.1
    assert f.loc[DATES[40], sf.SECTOR_RANK_10D] == pytest.approx(0.1)


# --- missing days ---
def test_one_missing_index_day_is_carried_once_two_stay_missing():
    stock, nifty, sectors = _world()
    sec = sectors["S_C"].copy()
    f1 = _build(stock, nifty, {**sectors, "S_C": sec.drop(DATES[30])})
    assert f1[sf.SECTOR_RET_10D].notna().loc[DATES[30]]  # filled from day 29 (one session stale)
    f2 = _build(stock, nifty, {**sectors, "S_C": sec.drop([DATES[30], DATES[31]])})
    assert np.isnan(f2.loc[DATES[31], sf.SECTOR_RET_10D])
    assert not (f2[sf.SECTOR_RET_10D].dropna() == 0).any()  # never 0
    # the window that starts at the missing day 31 (t = 41) is missing too
    assert np.isnan(f2.loc[DATES[41], sf.SECTOR_RET_10D])


def test_missing_stock_day_gives_missing_stock_vs_sector_only():
    stock, nifty, sectors = _world()
    f = _build(stock.drop([DATES[30], DATES[31]]), nifty, sectors)
    assert np.isnan(f.loc[DATES[31], sf.STOCK_VS_SECTOR_10D])
    assert not np.isnan(f.loc[DATES[31], sf.SECTOR_RET_10D])


def test_non_positive_or_nan_close_is_missing_not_zero():
    stock, nifty, sectors = _world()
    sec = sectors["S_C"].copy()
    sec.iloc[30] = 0.0
    sec.iloc[31] = np.nan
    f = _build(stock, nifty, {**sectors, "S_C": sec})
    assert np.isnan(f.loc[DATES[31], sf.SECTOR_RET_10D])


# --- no sector ---
def test_no_sector_index_leaves_all_four_missing():
    stock, nifty, sectors = _world()
    assert _build(stock, nifty, sectors, None).isna().all().all()
    assert _build(stock, nifty, sectors, "NOT_AN_INDEX").isna().all().all()


def test_resolve_sector_index_unverified_needs_opt_in():
    assert sf.resolve_sector_index("HDFCBANK") == "NIFTY BANK"
    assert sf.resolve_sector_index("ASIANPAINT") is None
    assert sf.resolve_sector_index("ASIANPAINT", include_unverified=True) == "NIFTY CONSR DURBL"
    assert sf.resolve_sector_index("NO_SUCH_STOCK", include_unverified=True) is None


def test_stock_vs_sector_is_not_forced_to_zero_under_official_rule():
    """Official index rule: stock minus the INDEX (which holds many other stocks), not minus itself."""
    stock, nifty, sectors = _world()
    f = _build(stock, nifty, sectors, "S_C")
    assert (f[sf.STOCK_VS_SECTOR_10D].dropna().abs() > 1e-6).all()


# --- point in time / leakage ---
def test_future_changes_never_alter_past_features():
    stock, nifty, sectors = _world()
    base = _build(stock, nifty, sectors)
    t = DATES[35]
    s2 = {k: v.copy() for k, v in sectors.items()}
    for v in s2.values():
        v.iloc[36:] = v.iloc[36:] * 3.7 + 11
    stock2, nifty2 = stock.copy(), nifty.copy()
    stock2.iloc[36:] *= 0.1
    nifty2.iloc[36:] *= 9.0
    changed = _build(stock2, nifty2, s2)
    pd.testing.assert_frame_equal(base.loc[:t], changed.loc[:t])


def test_asof_ignores_everything_after_the_decision_day():
    stock, nifty, sectors = _world()
    t = DATES[35]
    a = sf.sector_features_asof(stock, nifty, sectors, "S_C", t, rank_universe=UNI)
    s2 = {k: v.copy() for k, v in sectors.items()}
    for v in s2.values():
        v.iloc[36:] = np.nan
    b = sf.sector_features_asof(stock.iloc[:36], nifty.iloc[:36], s2, "S_C", t, rank_universe=UNI)
    pd.testing.assert_series_equal(a, b, check_names=False)


def test_asof_non_session_is_all_missing():
    stock, nifty, sectors = _world()
    sat = pd.Timestamp("2024-01-06")  # a Saturday
    r = sf.sector_features_asof(stock, nifty, sectors, "S_C", sat, rank_universe=UNI)
    assert r.isna().all()


# --- training / serving parity ---
def test_parity_batch_vs_single_day_every_date_toy_history_with_holes():
    stock, nifty, sectors = _world()
    sectors = {**sectors, "S_C": sectors["S_C"].drop([DATES[25], DATES[44], DATES[45]])}
    stock = stock.drop(DATES[33])
    batch = _build(stock, nifty, sectors, "S_C")
    for t in batch.index:
        one = sf.sector_features_asof(stock, nifty, sectors, "S_C", t, rank_universe=UNI)
        pd.testing.assert_series_equal(batch.loc[t], one, check_names=False, check_exact=True)


def test_close_series_from_candles_uses_ist_date():
    ts = pd.to_datetime(["2024-01-01 18:30:00+00:00", "2024-01-02 18:30:00+00:00"])
    s = sf.close_series_from_candles(pd.DataFrame({"ts": ts, "close": [10.0, 11.0]}))
    assert list(s.index) == [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")]


# --- real local data (read-only SELECT; skipped when the database does not answer within 15 s) ---------------
def _real_inputs():
    from swing_trade_ml.ml import sector_features_loader as ld

    try:
        conn = ld.connect_readonly(timeout=15)
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"local database not answering: {e}")
    with conn:
        nifty, sectors = ld.load_index_closes(conn)
        stocks = {s: ld.load_stock_close(conn, s) for s in ("HDFCBANK", "TCS", "SUNPHARMA")}
    return nifty, sectors, stocks


def test_parity_on_real_local_data_three_stocks():
    nifty, sectors, stocks = _real_inputs()
    for sym, stock in stocks.items():
        idx = sf.resolve_sector_index(sym)
        assert idx is not None and not stock.empty
        batch = sf.build_sector_features(stock, nifty, sectors, idx)
        valid = batch.dropna().index
        assert len(valid) > 500
        picks = list(valid[::7]) + list(valid[-30:])
        for t in picks:
            one = sf.sector_features_asof(stock, nifty, sectors, idx, t)
            pd.testing.assert_series_equal(batch.loc[t], one, check_names=False, check_exact=True)
