# backend/tests/test_brain_bad_market.py
from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd

from swing_trade_ml.brain import bad_market as bm
from swing_trade_ml.brain.portfolio_sim import Pick
from swing_trade_ml.brain.replay_scoring import StrictOutcome

D0 = date(2024, 1, 1)


def _series(closes):
    return pd.Series([float(c) for c in closes], index=[D0 + timedelta(days=i) for i in range(len(closes))])


def _o(status, net):
    return StrictOutcome(status, net, 5, False, False, D0)


def test_worst_falls_are_the_deepest_and_never_overlap():
    closes = (
        [100.0] * 30
        + [100 - i for i in range(10)]
        + [91.0] * 30
        + [91 - 2 * i for i in range(10)]
        + [73.0] * 30
    )
    got = bm.worst_falls(_series(closes), n=2, bars=10, min_history=0)
    assert len(got) == 2
    assert got[0].fall < got[1].fall < 0  # worst first
    a, b = sorted(got, key=lambda w: w.peak)
    assert a.trough < b.peak  # spans do not overlap
    assert abs(b.fall - (73 / 91 - 1)) < 1e-9


def test_falls_without_enough_history_are_not_chosen():
    closes = [100 - i for i in range(15)] + [85.0] * 40
    got = bm.worst_falls(_series(closes), n=1, bars=10, min_history=30)
    assert got and all(w.peak >= D0 + timedelta(days=20) for w in got)  # the early fall is skipped


def test_longest_fall_is_measured_peak_to_lowest_close_before_a_new_high():
    closes = [100, 99, 98, 101, 100, 99, 97, 96, 95, 96, 97, 102, 101]
    w = bm.longest_fall(_series(closes), min_history=0)
    assert (w.peak, w.trough, w.bars) == (D0 + timedelta(days=3), D0 + timedelta(days=8), 5)
    assert abs(w.fall - (95 / 101 - 1)) < 1e-9


def test_a_fall_still_running_at_the_end_counts():
    w = bm.longest_fall(_series([100, 101, 99, 98, 97]), min_history=0)
    assert (w.peak, w.trough) == (D0 + timedelta(days=1), D0 + timedelta(days=4))


def test_banner_timing_reports_the_first_careful_day_and_share_of_the_fall():
    nifty = _series([100, 98, 95, 90, 80])
    w = bm.Window("x", D0, D0 + timedelta(days=4), -0.2, 4)
    modes = {
        D0 + timedelta(days=i): m
        for i, m in enumerate(["NORMAL", "NORMAL", "DEFENSIVE", "NO_NEW_TRADES", "DEFENSIVE"])
    }
    b = bm.banner_timing(modes, w, nifty)
    assert b["mode_at_peak"] == "NORMAL"
    assert b["first_careful"]["days_after_peak"] == 2
    assert abs(b["first_careful"]["share_of_fall_by_then"] - 0.25) < 1e-9  # -5% of a -20% fall
    assert b["first_no_new_trades"]["day"] == (D0 + timedelta(days=3)).isoformat()
    assert (b["careful_days"], b["falling_days"]) == (3, 5)


def test_a_banner_that_never_turns_careful_says_never():
    nifty = _series([100, 90])
    w = bm.Window("x", D0, D0 + timedelta(days=1), -0.1, 1)
    b = bm.banner_timing({D0: "NORMAL", D0 + timedelta(days=1): "NORMAL"}, w, nifty)
    assert b["first_careful"] is None and b["careful_days"] == 0
    assert "never" in bm.plain_report(
        {
            "protocol": bm.PROTOCOL_ID,
            "stocks": 1,
            "data_to": "2024-01-02",
            "windows": [
                {
                    "window": {
                        "kind": "x",
                        "peak": "2024-01-01",
                        "trough": "2024-01-02",
                        "fall": -0.1,
                        "bars": 1,
                    },
                    "banner": b,
                    "account": {
                        "with_banner": {"max_drawdown": 0.05, "total_return": -0.02, "trades": 3},
                        "always_normal": {"max_drawdown": 0.05, "total_return": -0.02, "trades": 3},
                    },
                    "careful_day_ideas": bm.careful_day_ideas([], {}, {}),
                }
            ],
        }
    )


def test_careful_day_ideas_count_stops_avoided_and_targets_missed():
    d1, d2 = D0, D0 + timedelta(days=1)
    picks = [Pick(d1, "A", 0.9), Pick(d1, "B", 0.8), Pick(d2, "C", 0.7)]
    modes = {d1: "DEFENSIVE", d2: "NORMAL"}
    outcomes = {("A", d1): _o("stop", -0.045), ("B", d1): _o("target", 0.07), ("C", d2): _o("stop", -0.045)}
    c = bm.careful_day_ideas(picks, modes, outcomes)
    assert (c["ideas"], c["finished"], c["hit_stop"], c["hit_target"]) == (2, 2, 1, 1)
    assert abs(c["avg_net"] - 0.0125) < 1e-12


def test_replayed_modes_only_see_data_up_to_each_day(monkeypatch):
    seen = []

    def fake_judge(inputs):
        seen.append(len(inputs.index_close))
        return SimpleNamespace(mode=SimpleNamespace(value="NORMAL"))

    monkeypatch.setattr(bm, "judge", fake_judge)
    idx = _series(range(100, 110))
    days = list(idx.index)[3:6]
    modes = bm.replay_modes(idx, idx, idx, days)
    assert seen == [4, 5, 6] and set(modes) == set(days)
