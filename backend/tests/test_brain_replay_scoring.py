# backend/tests/test_brain_replay_scoring.py
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from swing_trade_ml.brain.replay_scoring import after_day, locked_score, strict_for, strict_score

START = date(2026, 9, 28)


def bars(rows):
    return pd.DataFrame(
        [
            {"day": START + timedelta(days=i), "open": o, "high": h, "low": lo, "close": c}
            for i, (o, h, lo, c) in enumerate(rows)
        ]
    )


FLAT = (100.0, 100.5, 99.5, 100.0)


def test_empty_bars_are_open():
    assert strict_score(bars([])).status == "open"


def test_fewer_than_fifteen_quiet_bars_are_open_not_scored():
    out = strict_score(bars([FLAT] * 5))
    assert out.status == "open" and out.net_return is None


def test_fifteen_quiet_bars_time_out_slightly_negative_after_costs():
    out = strict_score(bars([FLAT] * 15))
    assert out.status == "timeout" and out.days == 15
    assert -0.02 < out.net_return < 0.0  # flat price minus costs and slippage


def test_target_after_half_out_is_between_five_and_eight_percent():
    out = strict_score(bars([(100, 101, 99, 100)] * 2 + [(100, 109, 100, 108)]))
    assert out.status == "target" and out.half_out and not out.gap
    assert 0.05 < out.net_return < 0.08


def test_stop_is_about_minus_four_percent_after_costs():
    out = strict_score(bars([(100, 101, 99, 100), (100, 100, 95, 96)]))
    assert out.status == "stop" and not out.gap
    assert -0.05 < out.net_return < -0.04


def test_gap_through_the_stop_fills_at_the_open_and_loses_more():
    out = strict_score(bars([(100, 101, 99, 100), (90, 91, 89, 90)]))
    assert out.status == "stop" and out.gap
    assert out.net_return < -0.09


def test_a_bar_touching_both_target_and_stop_is_the_stop():
    out = strict_score(bars([(100, 109, 95, 100)]))
    assert out.status == "stop"


def test_half_sold_then_stopped_is_about_break_even():
    out = strict_score(bars([(100, 101, 99, 100), (100, 106, 99, 105), (105, 105, 90, 92)]))
    assert out.status == "stop" and out.half_out
    assert -0.01 < out.net_return < 0.01


def test_gap_up_through_the_target_fills_at_the_open_and_gains_more():
    out = strict_score(bars([(100, 101, 99, 100), (110, 112, 109, 111)]))
    assert out.status == "target" and out.gap
    assert out.net_return > 0.08


def test_after_day_keeps_only_later_bars():
    df = bars([FLAT] * 5)
    later = after_day(df, START + timedelta(days=1))
    assert list(later["day"]) == [START + timedelta(days=i) for i in (2, 3, 4)]


def test_locked_score_enters_at_the_decision_days_close():
    # decision day = START (close 100); the next bar's high is 108.5 -> +8% target
    rows = [(100, 100, 100, 100), (100, 108.5, 99.5, 108)]
    out = locked_score(bars(rows), START)
    assert out is not None and out.outcome == "target" and out.ret == 0.08


def test_locked_score_is_none_without_a_bar_on_or_before_the_decision_day():
    assert locked_score(bars([FLAT] * 3), START - timedelta(days=5)) is None


def test_strict_for_uses_the_bar_after_the_decision_day_as_entry():
    df = bars([FLAT] * 17)
    assert strict_for(df, START).status == "timeout"
