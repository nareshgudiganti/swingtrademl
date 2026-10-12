"""Horizon grid: the pure parts (scoring at other settings, picking, summarising)."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from swing_trade_ml.brain.horizon_grid import (
    Setting,
    _days_beaten,
    all_stock_outcomes,
    run_grid,
    summarise,
    top_k_by_day,
)
from swing_trade_ml.brain.replay_scoring import StrictOutcome

START = date(2026, 6, 1)


def _bars(rows) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"day": START + timedelta(days=i), "open": o, "high": h, "low": lo, "close": c}
            for i, (o, h, lo, c) in enumerate(rows)
        ]
    )


FLAT = (100.0, 100.5, 99.5, 100.0)
SPIKE = (100.0, 103.0, 99.8, 102.0)


def test_break_even_share_is_stop_over_target_plus_stop():
    assert Setting(15, 0.08, 0.04).breakeven == pytest.approx(1 / 3)
    assert Setting(5, 0.02, 0.04).breakeven == pytest.approx(2 / 3)


def test_the_same_stock_day_scores_differently_at_each_setting():
    df = _bars([FLAT, SPIKE] + [FLAT] * 20)
    day = START  # decided on day 0, enters on day 1
    small = all_stock_outcomes({"A": df}, [day], Setting(5, 0.02, 0.02))[("A", day)]
    big = all_stock_outcomes({"A": df}, [day], Setting(15, 0.08, 0.04))[("A", day)]
    assert small.status == "target" and small.net_return > 0
    assert big.status == "timeout"


def test_a_day_without_enough_future_is_left_open_not_guessed():
    df = _bars([FLAT] * 6)
    out = all_stock_outcomes({"A": df}, [START], Setting(15, 0.08, 0.04))[("A", START)]
    assert out.status == "open" and out.net_return is None


def test_a_day_the_stock_has_no_bar_is_skipped():
    df = _bars([FLAT] * 20)
    assert all_stock_outcomes({"A": df}, [START - timedelta(days=30)], Setting(5, 0.02, 0.02)) == {}


def test_top_k_takes_the_best_scores_each_day_and_ignores_unscored_stocks():
    d = START
    scores = {"A": {d: 0.9}, "B": {d: 0.5}, "C": {d: 0.7}, "D": {}}
    assert top_k_by_day(scores, [d], 2) == {d: ["A", "C"]}


def _o(status, net):
    return StrictOutcome(status, net, 3, False, False, START)


def test_summary_weighs_ideas_and_days_separately_and_skips_open_ideas():
    d1, d2 = START, START + timedelta(days=1)
    by_day = {
        d1: [_o("target", 0.10), _o("stop", -0.04), _o("target", 0.10)],
        d2: [_o("stop", -0.04), _o("open", None)],
    }
    s = summarise(by_day)
    assert s["ideas"] == 4 and s["days"] == 2 and s["hit_rate"] == 0.5
    assert s["avg_net"] == pytest.approx((0.10 - 0.04 + 0.10 - 0.04) / 4)
    assert s["avg_net_by_day"] == pytest.approx(((0.10 - 0.04 + 0.10) / 3 + -0.04) / 2)


def test_summary_of_nothing_is_empty_not_zero():
    assert summarise({})["avg_net"] is None


def test_days_the_model_beat_every_stock_are_counted():
    d1, d2 = START, START + timedelta(days=1)
    outcomes = {
        ("A", d1): _o("target", 0.05),
        ("B", d1): _o("stop", -0.04),
        ("A", d2): _o("stop", -0.04),
        ("B", d2): _o("target", 0.05),
    }
    picks = {d1: ["A"], d2: ["A"]}
    everyone = {d1: ["A", "B"], d2: ["A", "B"]}
    assert _days_beaten(picks, everyone, outcomes) == {"better": 1, "of": 2}


def test_a_window_that_starts_before_the_cutoff_is_refused():
    with pytest.raises(ValueError):
        run_grid(None, cutoff=date(2026, 6, 10), start=date(2026, 6, 10), end=date(2026, 7, 1))
