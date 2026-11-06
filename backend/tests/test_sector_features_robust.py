"""Sector inputs B1-5..B1-8, second line of defence (2026-11-04).

  1. Full-date training/serving parity (batch path vs as-of path), exact equality.
  2. An independent, deliberately simple, loop-based reference of the four formulas in
     docs/brain/SECTOR-FEATURES-SPEC.md. It imports NOTHING from the builder except constants for names;
     the maths is written again here with plain Python lists, to catch an error shared by the builder.
  3. Point in time: nothing dated after the decision day can change a feature at or before it.
  4. Missing data, one-session carry, stale and late-start indices, rank with fewer than 5 indices.

Real-data tests are read-only SELECTs and skip when the local database does not answer within 15 s.
Run the exhaustive all-stocks parity (about 35 CPU minutes, parallel) with
  python tests/test_sector_features_robust.py --workers 6
"""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from swing_trade_ml.ml import sector_features as sf

REPO = Path(__file__).resolve().parents[2]
SPLIT_FILE = REPO / "docs/brain/evidence/stock_split/stock_split_ev15.json"
NAMES = ("sector_ret_10d_vs_nifty", "sector_ret_20d_vs_nifty", "sector_rank_10d", "stock_vs_sector_10d")


# ============================================================================================================
# 2. INDEPENDENT REFERENCE (plain loops; no helper from the builder)
# ============================================================================================================
def _ref_on_calendar(series: pd.Series, cal: list) -> list:
    """Actual close per calendar day (None when absent / non-positive / NaN), then the one-session carry:
    a missing day takes the value of the PREVIOUS calendar day only if that day had an actual close."""
    d = {}
    for k, v in zip(series.index, series.to_numpy()):
        v = float(v)
        if math.isfinite(v) and v > 0:
            d[pd.Timestamp(k).normalize()] = v
    actual = [d.get(c) for c in cal]
    out = []
    for i, a in enumerate(actual):
        if a is not None:
            out.append(a)
        elif i > 0 and actual[i - 1] is not None:
            out.append(actual[i - 1])
        else:
            out.append(None)
    return out


def _ref_ret(vals: list, i: int, n: int):
    if i < n or vals[i] is None or vals[i - n] is None:
        return None
    return vals[i] / vals[i - n] - 1.0


def reference_features(stock, nifty, sectors, index_name, universe) -> pd.DataFrame:
    """Re-implementation of the spec, section 2 and 3, with loops."""
    members = list(dict.fromkeys(universe))
    used = {u: sectors[u] for u in members if u in sectors}
    if index_name is not None and index_name in sectors:
        used[index_name] = sectors[index_name]
    dates = set(pd.Timestamp(x).normalize() for x in nifty.index)
    for s in used.values():
        dates |= set(pd.Timestamp(x).normalize() for x in s.index)
    cal = sorted(dates)
    nif = _ref_on_calendar(nifty, cal)
    stk = _ref_on_calendar(stock, cal)
    sec = {k: _ref_on_calendar(v, cal) for k, v in used.items()}
    rows = []
    for i in range(len(cal)):
        row = [float("nan")] * 4
        if index_name is not None and index_name in sec:
            s10, s20 = _ref_ret(sec[index_name], i, 10), _ref_ret(sec[index_name], i, 20)
            n10, n20 = _ref_ret(nif, i, 10), _ref_ret(nif, i, 20)
            k10 = _ref_ret(stk, i, 10)
            if s10 is not None and n10 is not None:
                row[0] = s10 - n10
            if s20 is not None and n20 is not None:
                row[1] = s20 - n20
            if s10 is not None and k10 is not None:
                row[3] = k10 - s10
            # rank among the universe indices that have a 10-day return today
            todays = [_ref_ret(sec[u], i, 10) for u in members if u in sec]
            todays = [r for r in todays if r is not None]
            if s10 is not None and len(todays) >= 5:
                below = sum(1 for r in todays if r < s10)
                equal = sum(1 for r in todays if r == s10)
                avg_rank = below + (equal + 1) / 2.0
                row[2] = (avg_rank - 1.0) / (len(todays) - 1.0)
        rows.append(row)
    return pd.DataFrame(rows, index=pd.DatetimeIndex(cal), columns=list(NAMES), dtype="float64")


def _assert_same(a: pd.DataFrame, b: pd.DataFrame, exact: bool = True):
    assert list(a.index) == list(b.index)
    assert list(a.columns) == list(b.columns)
    pd.testing.assert_frame_equal(a, b, check_exact=exact, check_names=False, check_freq=False)


# ---------------------------------------------------------------------------------------------------------
# synthetic worlds
# ---------------------------------------------------------------------------------------------------------
UNI = [f"IDX{i}" for i in range(8)]


def _world(seed: int, n=120, holes=True, late=None, stale=None):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-02", periods=n)

    def walk(start=100.0):
        return pd.Series(start * np.exp(np.cumsum(rng.normal(0.0004, 0.01, n))), index=dates)

    nifty, stock = walk(), walk(50.0)
    sectors = {u: walk() for u in UNI}
    if holes:
        for ser_name in ["nifty", "stock", *UNI]:
            drop = rng.choice(n, size=rng.integers(0, 9), replace=False)
            if rng.random() < 0.5:  # add a deliberate two-day gap
                g = int(rng.integers(5, n - 5))
                drop = np.append(drop, [g, g + 1])
            target = nifty if ser_name == "nifty" else stock if ser_name == "stock" else sectors[ser_name]
            drop_idx = target.index[np.unique(drop)]
            if ser_name == "nifty":
                nifty = nifty.drop(drop_idx)
            elif ser_name == "stock":
                stock = stock.drop(drop_idx)
            else:
                sectors[ser_name] = target.drop(drop_idx)
    if late is not None:
        sectors[UNI[-1]] = sectors[UNI[-1]].iloc[late:]
    if stale is not None:
        sectors[UNI[0]] = sectors[UNI[0]].iloc[:stale]
    return stock, nifty, sectors


@pytest.mark.parametrize("seed", range(25))
def test_builder_equals_independent_reference_on_random_worlds(seed):
    late = 40 if seed % 3 == 0 else None
    stale = 90 if seed % 4 == 0 else None
    stock, nifty, sectors = _world(seed, late=late, stale=stale)
    for idx in (UNI[0], UNI[3], UNI[-1]):
        got = sf.build_sector_features(stock, nifty, sectors, idx, rank_universe=UNI)
        want = reference_features(stock, nifty, sectors, idx, UNI)
        _assert_same(got, want)


def test_reference_agrees_for_no_sector_and_known_tie():
    stock, nifty, sectors = _world(1, holes=False)
    got = sf.build_sector_features(stock, nifty, sectors, None, rank_universe=UNI)
    _assert_same(got, reference_features(stock, nifty, sectors, None, UNI))
    assert got.isna().all().all()
    # ties: two identical index series share the average rank
    sectors["IDX1"] = sectors["IDX0"].copy()
    got = sf.build_sector_features(stock, nifty, sectors, "IDX0", rank_universe=UNI)
    _assert_same(got, reference_features(stock, nifty, sectors, "IDX0", UNI))


# ============================================================================================================
# 3. POINT IN TIME
# ============================================================================================================
def _mutate_after(ser: pd.Series, t: pd.Timestamp, rng) -> pd.Series:
    out = ser.copy()
    later = out.index > t
    out[later] = out[later] * rng.uniform(0.2, 5.0, later.sum())
    return out


@pytest.mark.parametrize("which", ["stock", "nifty", "own_index", "other_index"])
def test_mutating_anything_after_t_never_changes_features_up_to_t(which):
    stock, nifty, sectors = _world(7, n=100, holes=True)
    idx, other = UNI[2], UNI[5]
    rng = np.random.default_rng(3)
    for t in (pd.bdate_range("2023-01-02", periods=100)[k] for k in (25, 40, 63, 80)):
        base = sf.build_sector_features(stock, nifty, sectors, idx, rank_universe=UNI)
        s2, n2, sec2 = stock, nifty, dict(sectors)
        if which == "stock":
            s2 = _mutate_after(stock, t, rng)
        elif which == "nifty":
            n2 = _mutate_after(nifty, t, rng)
        elif which == "own_index":
            sec2[idx] = _mutate_after(sectors[idx], t, rng)
        else:
            sec2[other] = _mutate_after(sectors[other], t, rng)  # the rank uses ALL indices on day t only
        mut = sf.build_sector_features(s2, n2, sec2, idx, rank_universe=UNI)
        # whole batch: every row dated <= t identical (the rank column included)
        pd.testing.assert_frame_equal(base.loc[:t], mut.loc[:t], check_exact=True, check_freq=False)
        # serving path at t is identical too
        a = sf.sector_features_asof(stock, nifty, sectors, idx, t, rank_universe=UNI)
        b = sf.sector_features_asof(s2, n2, sec2, idx, t, rank_universe=UNI)
        pd.testing.assert_series_equal(a, b, check_exact=True)


def test_dropping_or_adding_future_rows_changes_nothing_at_t():
    stock, nifty, sectors = _world(11, n=100, holes=False)
    t = pd.bdate_range("2023-01-02", periods=100)[60]
    full = sf.sector_features_asof(stock, nifty, sectors, UNI[1], t, rank_universe=UNI)
    cut = sf.sector_features_asof(
        stock.loc[:t], nifty.loc[:t], {k: v.loc[:t] for k, v in sectors.items()}, UNI[1], t, rank_universe=UNI
    )
    pd.testing.assert_series_equal(full, cut, check_exact=True)


def test_off_by_one_around_the_decision_day():
    stock, nifty, sectors = _world(5, n=80, holes=False)
    dates = stock.index
    t = dates[50]
    base = sf.sector_features_asof(stock, nifty, sectors, UNI[2], t, rank_universe=UNI)
    # a change on t+1 must NOT move the value at t
    for who in ("stock", "nifty", "idx", "other"):
        s2, n2, sec2 = stock.copy(), nifty.copy(), dict(sectors)
        if who == "stock":
            s2[dates[51]] *= 3
        elif who == "nifty":
            n2[dates[51]] *= 3
        elif who == "idx":
            sec2[UNI[2]] = sectors[UNI[2]].copy()
            sec2[UNI[2]][dates[51]] *= 3
        else:
            sec2[UNI[4]] = sectors[UNI[4]].copy()
            sec2[UNI[4]][dates[51]] *= 3
        got = sf.sector_features_asof(s2, n2, sec2, UNI[2], t, rank_universe=UNI)
        pd.testing.assert_series_equal(base, got, check_exact=True)
    # a change ON t (the close of the decision day itself) MUST move the value at t
    s2 = stock.copy()
    s2[t] *= 1.5
    assert (
        sf.sector_features_asof(s2, nifty, sectors, UNI[2], t, rank_universe=UNI)[NAMES[3]] != base[NAMES[3]]
    )
    n2 = nifty.copy()
    n2[t] *= 1.5
    assert (
        sf.sector_features_asof(stock, n2, sectors, UNI[2], t, rank_universe=UNI)[NAMES[0]] != base[NAMES[0]]
    )
    # a change on t-10 (the start of the 10-session window) MUST move the 10-day figure
    s3 = stock.copy()
    s3[dates[40]] *= 1.5
    assert (
        sf.sector_features_asof(s3, nifty, sectors, UNI[2], t, rank_universe=UNI)[NAMES[3]] != base[NAMES[3]]
    )
    # a change on t-11 must NOT move any 10-day figure
    s4, n4 = stock.copy(), nifty.copy()
    s4[dates[39]] *= 1.5
    n4[dates[39]] *= 1.5
    got = sf.sector_features_asof(s4, n4, sectors, UNI[2], t, rank_universe=UNI)
    for k in (NAMES[0], NAMES[2], NAMES[3]):
        assert got[k] == base[k]
    assert got[NAMES[1]] == base[NAMES[1]]  # the 20-day window starts at t-20


def test_ist_midnight_candle_stamps_land_on_the_right_day_and_are_not_future():
    # IST-midnight daily bars: 2024-01-02 IST is stamped 2024-01-01 18:30 UTC.
    days = pd.bdate_range("2024-01-02", periods=40)
    stamps = [
        pd.Timestamp(d.date().isoformat() + " 00:00", tz="Asia/Kolkata").tz_convert("UTC") for d in days
    ]
    assert (
        stamps[0].hour == 18
        and stamps[0].minute == 30
        and stamps[0].date() == pd.Timestamp("2024-01-01").date()
    )
    close = 100.0 * (1.01 ** np.arange(40))
    ser = sf.close_series_from_candles(pd.DataFrame({"ts": stamps, "close": close}))
    assert list(ser.index) == list(days)  # IST date, not the UTC date of the stamp
    nif = ser.copy()
    secs = {u: ser * (1 + 0.001 * i) ** np.arange(40) for i, u in enumerate(UNI)}
    t = days[25]
    fut = nif.copy()
    # candle of the NEXT IST day (stamped 18:30 UTC on the decision day) is future data at t
    next_stamp = stamps[26]
    assert next_stamp.date() == t.date()  # the UTC date equals t: a naive UTC date would wrongly include it
    fut[days[26]] = 1e6
    a = sf.sector_features_asof(ser, nif, secs, UNI[1], t, rank_universe=UNI)
    b = sf.sector_features_asof(ser, fut, secs, UNI[1], t, rank_universe=UNI)
    pd.testing.assert_series_equal(a, b, check_exact=True)


# ============================================================================================================
# 4. MISSING DATA / FILL / STALE
# ============================================================================================================
def _flat_world(n=60):
    dates = pd.bdate_range("2024-03-01", periods=n)
    mk = lambda r, s=100.0: pd.Series(s * (1 + r) ** np.arange(n), index=dates)  # noqa: E731
    return dates, mk(0.001), mk(0.004), {u: mk(0.0005 * (i + 1), 100 + i) for i, u in enumerate(UNI)}


def test_one_day_gap_is_carried_exactly_once_and_two_days_stay_missing_never_zero():
    dates, nifty, stock, sectors = _flat_world()
    sec = dict(sectors)
    sec[UNI[2]] = sec[UNI[2]].drop([dates[30], dates[40], dates[41]])
    f = sf.build_sector_features(stock, nifty, sec, UNI[2], rank_universe=UNI)
    # day 30: one missing day -> carried (the index return on that day uses yesterday's close)
    assert not np.isnan(f.loc[dates[30], NAMES[0]])
    expect = sec[UNI[2]].reindex(dates).ffill(limit=1)
    assert expect[dates[30]] == sec[UNI[2]][dates[29]]
    # day 40 carried, day 41 stays missing -> own-index features missing on 41, never 0
    assert not np.isnan(f.loc[dates[40], NAMES[0]])
    assert np.isnan(f.loc[dates[41], NAMES[0]])
    assert np.isnan(f.loc[dates[41], NAMES[3]]) and np.isnan(f.loc[dates[41], NAMES[2]])
    assert (f.fillna(1.0).loc[dates[41]] != 0.0).all()
    # ten sessions later the value that was a missing end of a window recovers; a missing START (t-10) too
    assert np.isnan(f.loc[dates[51], NAMES[0]])  # window start (t-10 = day 41) is missing
    assert not np.isnan(f.loc[dates[52], NAMES[0]])


def test_union_calendar_holiday_for_the_stock_only_and_for_nifty_only():
    dates, nifty, stock, sectors = _flat_world()
    s2 = stock.drop([dates[35], dates[36]])  # stock traded nothing for two days: indices did
    f = sf.build_sector_features(s2, nifty, sectors, UNI[1], rank_universe=UNI)
    assert dates[36] in f.index  # the calendar is the union, not the stock's own days
    assert np.isnan(f.loc[dates[36], NAMES[3]])  # stock-vs-sector missing...
    assert not np.isnan(f.loc[dates[36], NAMES[0]])  # ...index-level figures still there
    assert not np.isnan(f.loc[dates[36], NAMES[2]])
    # a stock row dated outside the calendar gets all-missing in the serving path
    odd = pd.Timestamp("2024-03-02")  # Saturday
    r = sf.sector_features_asof(stock, nifty, sectors, UNI[1], odd, rank_universe=UNI)
    assert r.isna().all()
    # NIFTY missing on a day where sector indices traded: day stays on the calendar, carried once
    n2 = nifty.drop([dates[30]])
    f2 = sf.build_sector_features(stock, n2, sectors, UNI[1], rank_universe=UNI)
    assert dates[30] in f2.index and not np.isnan(f2.loc[dates[30], NAMES[0]])


def test_late_starting_index_is_excluded_from_default_rank_and_does_not_shift_the_scale():
    # the real case: NIFTY CHEMICALS exists only from 2025-11-24 and is not in the default rank universe.
    assert "NIFTY CHEMICALS" not in sf.DEFAULT_RANK_UNIVERSE
    dates, nifty, stock, sectors = _flat_world()
    base = sf.build_sector_features(stock, nifty, sectors, UNI[3], rank_universe=UNI)
    chem = pd.Series(100.0 * 1.2 ** np.arange(20), index=dates[40:])  # explodes, starts late
    withchem = sf.build_sector_features(
        stock, nifty, {**sectors, "NIFTY CHEMICALS": chem}, UNI[3], rank_universe=UNI
    )
    _assert_same(base, withchem)
    # and if an index IS in the universe but starts late: before it exists the rank is over the others only
    # (N changes from 7 to 8 on its first valid day), still scaled 0..1 and never 0 for 'missing'
    late = {**sectors, UNI[-1]: sectors[UNI[-1]].iloc[40:]}
    f = sf.build_sector_features(stock, nifty, late, UNI[0], rank_universe=UNI)
    assert f[NAMES[2]].dropna().between(0, 1).all()
    _assert_same(f, reference_features(stock, nifty, late, UNI[0], UNI))
    # the late index itself has no rank until it has a 10-day return
    g = sf.build_sector_features(stock, nifty, late, UNI[-1], rank_universe=UNI)
    assert g[NAMES[2]].iloc[:50].isna().all() and g[NAMES[2]].iloc[50:].notna().all()


def test_stale_index_is_missing_after_one_carried_session_and_leaves_the_rank():
    dates, nifty, stock, sectors = _flat_world()
    stale = {**sectors, UNI[0]: sectors[UNI[0]].iloc[:30]}  # last bar = dates[29]
    f = sf.build_sector_features(stock, nifty, stale, UNI[0], rank_universe=UNI)
    assert not np.isnan(f.loc[dates[30], NAMES[0]])  # carried once (1 session stale): allowed
    assert f.loc[dates[31:], NAMES[0]].isna().all()  # older than the allowed fill: missing
    assert f.loc[dates[31:], NAMES[2]].isna().all()
    # the other indices' rank on a later day is taken over the 7 remaining indices only
    g = sf.build_sector_features(stock, nifty, stale, UNI[4], rank_universe=UNI)
    assert g.loc[dates[50], NAMES[2]] == pytest.approx(
        reference_features(stock, nifty, stale, UNI[4], UNI).loc[dates[50], NAMES[2]]
    )
    assert g.loc[dates[50], NAMES[2]] <= 1.0
    # a custom stricter allowance: zero fill means even the first stale day is missing
    z = sf.build_sector_features(stock, nifty, stale, UNI[0], rank_universe=UNI, max_ffill=0)
    assert np.isnan(z.loc[dates[30], NAMES[0]])


def test_rank_is_missing_with_fewer_than_five_valid_indices_and_present_with_five():
    dates, nifty, stock, sectors = _flat_world()
    four = {u: sectors[u] for u in UNI[:4]}
    f = sf.build_sector_features(stock, nifty, four, UNI[0], rank_universe=UNI)
    assert f[NAMES[2]].isna().all() and f[NAMES[0]].iloc[30:].notna().all()
    five = {u: sectors[u] for u in UNI[:5]}
    g = sf.build_sector_features(stock, nifty, five, UNI[0], rank_universe=UNI)
    assert g[NAMES[2]].iloc[12:].notna().all()
    # a day on which only four indices have a 10-day return: missing that day only
    holes = {u: sectors[u] for u in UNI[:5]}
    holes[UNI[4]] = holes[UNI[4]].drop([dates[45], dates[46]])
    h = sf.build_sector_features(stock, nifty, holes, UNI[0], rank_universe=UNI)
    assert np.isnan(h.loc[dates[46], NAMES[2]])
    assert not np.isnan(h.loc[dates[44], NAMES[2]])


# ============================================================================================================
# REAL LOCAL DATA (read-only SELECT)
# ============================================================================================================
def _used_49() -> list[str]:
    return list(json.loads(SPLIT_FILE.read_text(encoding="utf-8"))["used_49"])


_REAL: dict = {}


def _real():
    if _REAL:
        return _REAL
    from swing_trade_ml.ml import sector_features_loader as ld

    try:
        conn = ld.connect_readonly(timeout=15)
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"local database not answering: {e}")
    with conn:
        nifty, sectors = ld.load_index_closes(conn)
        stocks = {s: ld.load_stock_close(conn, s) for s in _used_49()}
    _REAL.update(nifty=nifty, sectors=sectors, stocks=stocks)
    return _REAL


def _mapped(stocks) -> list[str]:
    return [s for s in stocks if sf.resolve_sector_index(s) is not None and len(stocks[s])]


def test_real_data_all_mapped_stocks_builder_equals_independent_reference_every_date():
    r = _real()
    mapped = _mapped(r["stocks"])
    assert len(mapped) == 47
    n_cmp = n_bad = 0
    for sym in mapped:
        idx = sf.resolve_sector_index(sym)
        got = sf.build_sector_features(r["stocks"][sym], r["nifty"], r["sectors"], idx)
        want = reference_features(r["stocks"][sym], r["nifty"], r["sectors"], idx, sf.DEFAULT_RANK_UNIVERSE)
        assert list(got.index) == list(want.index)
        a, b = got.to_numpy(), want.to_numpy()
        same = (a == b) | (np.isnan(a) & np.isnan(b))
        n_cmp += same.size
        n_bad += int((~same).sum())
    print(f"REFERENCE-vs-BUILDER real data: {n_cmp} (stock,date,feature) comparisons, {n_bad} mismatches")
    assert n_bad == 0


def test_real_data_unmapped_stocks_stay_missing_and_unverified_is_off_by_default():
    r = _real()
    for sym in ("ASIANPAINT", "BHARTIARTL"):
        assert sf.resolve_sector_index(sym) is None
        assert sf.resolve_sector_index(sym, include_unverified=False) is None
        f = sf.build_sector_features(r["stocks"][sym], r["nifty"], r["sectors"], sf.resolve_sector_index(sym))
        assert f.isna().all().all()
    import inspect

    assert inspect.signature(sf.resolve_sector_index).parameters["include_unverified"].default is False


def _compare_all_dates(nifty, sectors, stock, idx):
    """Batch (training) path vs as-of (serving) path on EVERY row of the shared calendar. Exact equality."""
    batch = sf.build_sector_features(stock, nifty, sectors, idx)
    n_cmp = n_bad = n_valid = 0
    first_bad = None
    for t in batch.index:
        one = sf.sector_features_asof(stock, nifty, sectors, idx, t)
        a, b = batch.loc[t].to_numpy(), one.to_numpy()
        same = (a == b) | (np.isnan(a) & np.isnan(b))
        n_cmp += 4
        n_bad += int((~same).sum())
        n_valid += int(not np.isnan(a).any())
        if not same.all() and first_bad is None:
            first_bad = str(t.date())
    return n_cmp, n_bad, n_valid, len(batch), first_bad


@pytest.mark.parametrize("sym", ["APOLLOHOSP", "TCS"])  # NIFTY HEALTHCARE has 12 missing days: the hard case
def test_real_data_full_date_parity_batch_vs_asof_two_stocks(sym):
    r = _real()
    n_cmp, n_bad, n_valid, n_dates, first_bad = _compare_all_dates(
        r["nifty"], r["sectors"], r["stocks"][sym], sf.resolve_sector_index(sym)
    )
    print(
        f"PARITY {sym}: {n_dates} dates, {n_cmp} comparisons, {n_bad} mismatches, {n_valid} fully valid dates"
    )
    assert n_bad == 0, first_bad
    assert n_valid > 900


@pytest.mark.skipif(
    os.environ.get("SECTOR_FULL_PARITY") != "1", reason="exhaustive run; set SECTOR_FULL_PARITY=1"
)
def test_real_data_full_date_parity_every_mapped_stock():
    r = _real()
    tot = bad = 0
    for sym in _mapped(r["stocks"]):
        c, b, *_ = _compare_all_dates(
            r["nifty"], r["sectors"], r["stocks"][sym], sf.resolve_sector_index(sym)
        )
        tot, bad = tot + c, bad + b
    assert bad == 0, (tot, bad)


def test_real_data_rank_cross_section_every_date_for_all_indices_matches_asof():
    """The rank of ALL 15 indices on EVERY date: the as-of path on a sample of dates per index is not enough
    here, so check the cross-section once per date (any index gives all 15 ranks via 15 batch columns)."""
    r = _real()
    cols = {}
    for idx in sf.DEFAULT_RANK_UNIVERSE:
        cols[idx] = sf.build_sector_features(r["stocks"]["TCS"], r["nifty"], r["sectors"], idx)[NAMES[2]]
    ranks = pd.DataFrame(cols)
    want = {}
    for idx in sf.DEFAULT_RANK_UNIVERSE:
        want[idx] = reference_features(
            r["stocks"]["TCS"], r["nifty"], r["sectors"], idx, sf.DEFAULT_RANK_UNIVERSE
        )[NAMES[2]]
    want = pd.DataFrame(want)
    a, b = ranks.to_numpy(), want.to_numpy()
    assert ((a == b) | (np.isnan(a) & np.isnan(b))).all()
    # on each valid day the average of the 15 ranks is exactly 0.5 (ranks are a permutation, ties averaged)
    full = ranks.dropna()
    assert len(full) > 1000
    assert np.allclose(full.mean(axis=1).to_numpy(), 0.5, atol=1e-12)
    assert ((full >= 0) & (full <= 1)).all().all()


# ============================================================================================================
# exhaustive runner: python tests/test_sector_features_robust.py --workers 6
# ============================================================================================================
def _worker(sym: str):
    from swing_trade_ml.ml import sector_features_loader as ld

    with ld.connect_readonly(timeout=15) as conn:
        nifty, sectors = ld.load_index_closes(conn)
        stock = ld.load_stock_close(conn, sym)
    return (sym, *_compare_all_dates(nifty, sectors, stock, sf.resolve_sector_index(sym)))


def main(argv=None) -> int:
    import argparse
    from concurrent.futures import ProcessPoolExecutor

    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)
    from swing_trade_ml.ml import sector_features_loader as ld

    with ld.connect_readonly(timeout=15) as conn:
        syms = [
            s
            for s in _used_49()
            if sf.resolve_sector_index(s) is not None and len(ld.load_stock_close(conn, s))
        ]
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        res = list(ex.map(_worker, syms))
    tot = sum(r[1] for r in res)
    bad = sum(r[2] for r in res)
    valid = sum(r[3] for r in res)
    dates = sum(r[4] for r in res)
    out = {
        "stocks": len(res),
        "stock_dates": dates,
        "comparisons_stock_date_feature": tot,
        "mismatches": bad,
        "fully_valid_stock_dates": valid,
        "per_stock": {r[0]: {"dates": r[4], "mismatches": r[2], "valid_dates": r[3]} for r in res},
        "tolerance": "exact (==, NaN equals NaN)",
    }
    text = json.dumps(out, indent=1)
    print(text)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
