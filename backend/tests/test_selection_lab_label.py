"""Selection lab (design rev 3, section 4.1): the 15-day "beats the day's median" label."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from swing_trade_ml.brain import selection_lab as sl


def ref(n=20):
    """A reference group whose 15-day returns are 0.00 .. 0.19 (stock R00 .. R19)."""
    return {f"R{i:02d}": i / 100 for i in range(n)}


def test_the_cut_off_is_the_70th_percentile_of_excess_in_the_reference_group_only():
    r = ref()
    labels, cut = sl.excess_labels(r, list(r))
    median = sorted(r.values())[len(r) // 2 - 1] / 2 + sorted(r.values())[len(r) // 2] / 2
    excess = {s: v - median for s, v in r.items()}
    assert cut == pytest.approx(pd.Series(list(excess.values())).quantile(0.70, interpolation="linear"))
    assert sum(labels[s] for s in r) == 6  # 0.70 cut-off on 20 evenly spaced values: the top 6


def test_a_value_exactly_on_the_cut_off_is_labelled_one():
    r = {f"R{i}": float(i) for i in range(11)}  # 0..10: the 70th percentile is exactly 7.0
    labels, cut = sl.excess_labels(r, list(r))
    top = max(s for s in r if r[s] - 5.0 == pytest.approx(cut))
    assert labels[top] == 1
    assert labels["R6"] == 0 and labels["R7"] == 1


def test_tied_values_get_the_same_label():
    r = {f"R{i}": 0.0 for i in range(8)} | {"R8": 0.05, "R9": 0.05, "R10": 0.10}
    labels, _ = sl.excess_labels(r, list(r))
    assert labels["R8"] == labels["R9"]
    # the cut-off here equals the tied zeros, so by the rule ("at or above") they all get 1: ties never split
    assert labels["R0"] == labels["R7"] == 1


def test_extra_stocks_are_labelled_by_the_same_rule_and_never_move_the_cut_off():
    r = ref()
    base_labels, base_cut = sl.excess_labels(r, list(r))
    extras = {"X1": 0.50, "X2": -0.40, "X3": 0.0}
    labels, cut = sl.excess_labels(r | extras, list(r))
    assert cut == base_cut
    assert labels["X1"] == 1 and labels["X2"] == 0
    assert all(labels[s] == base_labels[s] for s in r)


def test_adding_or_removing_an_extra_stock_changes_nothing_for_the_others():
    r = ref()
    a, cut_a = sl.excess_labels(r | {"X": 0.3}, list(r))
    b, cut_b = sl.excess_labels(r, list(r))
    assert cut_a == cut_b and {s: a[s] for s in r} == b


def test_too_few_reference_stocks_means_no_labels_that_day():
    assert sl.excess_labels(ref(9), list(ref(9))) is None
    assert sl.excess_labels(ref(10), list(ref(10))) is not None


def test_a_reference_stock_without_a_return_is_left_out_and_counted():
    r = ref(12) | {"BAD": float("nan")}
    labels, _ = sl.excess_labels(r, [*ref(12), "BAD"])
    assert "BAD" not in labels and len(labels) == 12


def test_the_share_of_ones_in_the_reference_group_is_about_thirty_percent():
    r = ref(100)
    labels, _ = sl.excess_labels(r, list(r))
    assert 29 <= sum(labels.values()) <= 31


def bars(n=30, px=100.0, step=1.0):
    d0 = date(2024, 1, 1)
    return pd.DataFrame(
        [
            {"day": d0 + timedelta(days=i), "open": px + step * i, "close": px + step * i + 0.5}
            for i in range(n)
        ]
    )


def test_the_forward_return_is_open_of_day_one_to_close_of_day_fifteen():
    df = bars()
    decision = df.iloc[2]["day"]  # day 1 = the next bar (index 3), day 15 = index 17
    r = sl.forward_return(df, decision)
    assert r == pytest.approx(df.iloc[17]["close"] / df.iloc[3]["open"] - 1)


def test_the_forward_return_is_missing_when_the_window_is_incomplete():
    df = bars(n=10)
    assert sl.forward_return(df, df.iloc[2]["day"]) is None
    assert sl.forward_return(df, df.iloc[-1]["day"]) is None


def test_the_forward_return_is_missing_when_a_price_is_bad():
    df = bars()
    df.loc[3, "open"] = 0.0
    assert sl.forward_return(df, df.iloc[2]["day"]) is None


# ---------------------------------------------------------------- reference group and labelled frame

IST = "Asia/Kolkata"


def make_bars(n=260, drift=0.0, vol=2_000_000.0, px=100.0):
    d0 = date(2023, 1, 2)
    rows = []
    p = px
    for i in range(n):
        o = p
        p = p * (1 + drift)
        rows.append({"day": d0 + timedelta(days=i), "open": o, "close": p, "volume": vol})
    return pd.DataFrame(rows)


def test_median_turnover_is_close_times_volume_over_twenty_sessions_up_to_the_day():
    df = make_bars(vol=1_000_000.0, px=100.0, drift=0.0)
    assert sl.median_turnover(df, df.iloc[100]["day"]) == pytest.approx(100.0 * 1_000_000.0)
    assert sl.median_turnover(df, df.iloc[5]["day"]) is None  # fewer than 20 sessions of history


def test_the_reference_group_needs_history_and_turnover_of_five_crore():
    bars = {"OK": make_bars(), "THIN": make_bars(vol=1_000.0), "SHORT": make_bars(n=150)}
    day = bars["OK"].iloc[230]["day"]
    assert sl.reference_for_day(day, list(bars), bars) == ["OK"]


def frame_for(bars, symbols, days):
    rows = []
    for s in symbols:
        for d in days:
            ts = pd.Timestamp(d, tz=IST).tz_convert("UTC")
            rows.append({"symbol": s, "ts": ts})
    return pd.DataFrame(rows)


def test_label_frame_labels_every_stock_with_the_reference_cut_off_and_reports_what_it_dropped():
    ref_syms = [f"R{i:02d}" for i in range(12)]
    bars = {s: make_bars(drift=0.0005 * (i + 1)) for i, s in enumerate(ref_syms)}
    bars["EXTRA"] = make_bars(drift=0.01)
    day = bars["R00"].iloc[230]["day"]
    late = bars["R00"].iloc[-1]["day"]  # no 15 bars after it: no return, no label
    frame = frame_for(bars, [*ref_syms, "EXTRA"], [day, late])
    out, report = sl.label_frame(frame, bars, ref_syms)
    got = {(r.symbol, r.day): r.target for r in out.itertuples()}
    assert got[("EXTRA", day)] == 1 and got[("R00", day)] == 0 and got[("R11", day)] == 1
    assert ("R00", late) not in got and report["rows_without_return"] == 13
    assert report["days_labelled"] == 1 and report["days_without_labels"] == 0


def test_label_frame_uses_the_ist_date_of_the_stamp():
    ref_syms = [f"R{i:02d}" for i in range(10)]
    bars = {s: make_bars(drift=0.0005 * (i + 1)) for i, s in enumerate(ref_syms)}
    day = bars["R00"].iloc[230]["day"]
    out, _ = sl.label_frame(frame_for(bars, ref_syms, [day]), bars, ref_syms)
    assert set(out["day"]) == {day}  # an 18:30 UTC stamp is that IST day, not the previous one


def test_the_share_of_ones_is_reported_separately_for_reference_and_extra_stocks_per_year():
    ref_syms = [f"R{i:02d}" for i in range(12)]
    bars = {s: make_bars(drift=0.0005 * (i + 1)) for i, s in enumerate(ref_syms)}
    bars["EXTRA"] = make_bars(drift=0.01)
    days = [bars["R00"].iloc[i]["day"] for i in (220, 225, 230)]
    _, report = sl.label_frame(frame_for(bars, [*ref_syms, "EXTRA"], days), bars, ref_syms)
    y = report["share_of_ones_by_year"]["2023"]
    assert y["extra"] == 1.0 and 0.2 <= y["reference"] <= 0.5


def test_a_day_with_too_few_reference_stocks_is_dropped_and_counted():
    ref_syms = [f"R{i:02d}" for i in range(9)]  # one short of the minimum
    bars = {s: make_bars(drift=0.0005 * (i + 1)) for i, s in enumerate(ref_syms)}
    bars["EXTRA"] = make_bars(drift=0.01)
    day = bars["R00"].iloc[230]["day"]
    out, report = sl.label_frame(frame_for(bars, [*ref_syms, "EXTRA"], [day]), bars, ref_syms)
    assert out.empty and report["days_without_labels"] == 1 and report["days_labelled"] == 0
