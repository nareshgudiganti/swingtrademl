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
