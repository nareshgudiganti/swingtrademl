"""Selection lab (design rev 3, section 4.2): the data-quality gate for the wider training set."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from swing_trade_ml.brain import selection_lab as sl

D0 = date(2023, 1, 2)


def mk(n=400, skip=(), vol=1000.0):
    """n weekday-spaced bars; `skip` = bar positions left out (missing sessions)."""
    days = []
    d = D0
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    rows = [
        {"day": x, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": vol}
        for i, x in enumerate(days)
        if i not in set(skip)
    ]
    return pd.DataFrame(rows), days


def test_a_bar_with_high_below_low_or_nonpositive_close_or_zero_volume_is_bad():
    df, days = mk(30)
    df.loc[3, ["high", "low"]] = [98.0, 99.0]
    df.loc[5, "close"] = 0.0
    df.loc[7, "volume"] = 0.0
    assert sl.bad_bar_days(df) == {days[3], days[5], days[7]}


def test_a_bad_bar_removes_its_own_row_and_every_label_whose_window_contains_it():
    df, days = mk(60)
    df.loc[30, "volume"] = 0.0
    out = sl.excluded_decision_days(df, {})
    # decision i is hurt when the bad bar j=30 is in bars i+1..i+15, or is the row itself
    assert out["bad_bar"] == {days[i] for i in range(15, 31)}
    assert days[14] not in out["bad_bar"] and days[31] not in out["bad_bar"]


def test_a_gap_over_twenty_percent_is_flagged_but_not_removed_by_default():
    df, days = mk(60)
    df.loc[30:, ["open", "high", "low", "close"]] = [70.0, 71.0, 69.0, 70.0]
    flags = sl.overnight_flags(df)
    assert [(f.day, round(f.move, 2)) for f in flags] == [(days[30], -0.30)]
    out = sl.excluded_decision_days(df, {})
    assert out["verified_error"] == set() and out["unresolved"] == set()


def test_a_move_of_exactly_twenty_percent_is_not_flagged():
    df, _days = mk(40)
    df.loc[20:, ["open", "high", "low", "close"]] = [80.0, 81.0, 79.0, 80.0]
    assert sl.overnight_flags(df) == []


def test_every_flag_must_be_classified_before_a_run():
    df, days = mk(60)
    df.loc[30:, ["open", "high", "low", "close"]] = [70.0, 71.0, 69.0, 70.0]
    flags = sl.overnight_flags(df)
    assert sl.unclassified("XYZ", flags, {}) == [("XYZ", days[30])]
    assert sl.unclassified("XYZ", flags, {("XYZ", days[30]): "real_gap"}) == []
    with pytest.raises(ValueError, match="not one of"):
        sl.unclassified("XYZ", flags, {("XYZ", days[30]): "maybe"})


def test_a_real_gap_is_always_kept_with_its_losses():
    df, days = mk(400)
    df.loc[300:, ["open", "high", "low", "close"]] = [70.0, 71.0, 69.0, 70.0]
    rec = {("XYZ", days[300]): "real_gap"}
    out = sl.excluded_decision_days(df, rec, "XYZ")
    assert out["verified_error"] == set() and out["unresolved"] == set()
    kept, report = sl.apply_gate(_frame("XYZ", days), {"XYZ": df}, rec)
    assert len(kept) == len(_frame("XYZ", days)) and report["by_reason"]["real_gap_kept"] == 1


def test_a_verified_error_removes_spanning_labels_and_the_next_252_sessions_only():
    df, days = mk(600)
    df.loc[300:, ["open", "high", "low", "close"]] = [70.0, 71.0, 69.0, 70.0]
    rec = {("XYZ", days[300]): "verified_error"}
    out = sl.excluded_decision_days(df, rec, "XYZ")
    assert out["verified_error"] == {days[i] for i in range(285, 300 + 252)}
    assert days[284] not in out["verified_error"] and days[552] not in out["verified_error"]


def test_an_unresolved_anomaly_stays_in_the_main_result_and_leaves_in_the_sensitivity_one():
    df, days = mk(600)
    df.loc[300:, ["open", "high", "low", "close"]] = [70.0, 71.0, 69.0, 70.0]
    rec = {("XYZ", days[300]): "unresolved"}
    bars = {"XYZ": df}
    frame = _frame("XYZ", days)
    main, rep_main = sl.apply_gate(frame, bars, rec)
    sens, rep_sens = sl.apply_gate(frame, bars, rec, drop_unresolved=True)
    assert len(main) == len(frame) and len(sens) < len(main)
    assert rep_main["by_reason"]["unresolved_kept"] == 1 and rep_sens["by_reason"]["unresolved"] > 0
    removed = set(frame["day"]) - set(sens["day"])
    assert removed == {days[i] for i in range(285, 300 + 252)}


def test_a_stock_year_with_more_than_ten_missing_sessions_is_left_out_and_listed():
    df, days = mk(400, skip=range(100, 112))  # 12 missing sessions inside one calendar year
    calendar = days
    bad = sl.sparse_years(df, calendar)
    assert bad == {days[100].year}
    ok_df, _ = mk(400, skip=range(100, 110))  # exactly 10 missing is allowed
    assert sl.sparse_years(ok_df, calendar) == set()


def test_sessions_before_a_stock_listed_are_not_counted_as_missing():
    df, days = mk(400)
    df = df[df["day"] >= days[200]].reset_index(drop=True)
    assert sl.sparse_years(df, days) == set()


def test_apply_gate_reports_every_reason_with_counts_and_lists_dropped_stock_years():
    df, days = mk(400, skip=range(100, 112))
    kept, report = sl.apply_gate(_frame("XYZ", list(df["day"])), {"XYZ": df}, {}, calendar=days)
    assert report["stock_years_left_out"] == [("XYZ", days[100].year)]
    assert report["rows_in"] > report["rows_out"] == len(kept)
    assert set(report["by_reason"]) >= {"bad_bar", "verified_error", "unresolved", "sparse_year"}


def _frame(sym, days):
    return pd.DataFrame({"symbol": sym, "day": list(days)})
