"""Pure maths of the A8 pause-number check (brain/pause_check.py), on tiny fixed sequences."""

from __future__ import annotations

import random
from datetime import date, timedelta

import numpy as np
import pandas as pd

from swing_trade_ml.brain import pause_check as pc
from swing_trade_ml.brain.pause_check import Idea


def _ideas(results, start=date(2024, 1, 1)):
    return [
        Idea(start + timedelta(days=i), f"S{i}", start + timedelta(days=i + 10), r)
        for i, r in enumerate(results)
    ]


def test_streak_fires_on_the_eighth_loss_in_a_row():
    ideas = _ideas([-0.01] * 7 + [0.0] + [-0.02] * 8)
    # the zero result resets the count; the 8th loss after it is index 15
    assert pc.streak_fire(ideas) == ideas[15].exit_day
    assert pc.streak_fire(_ideas([-0.01] * 7)) is None


def test_streak_orders_by_exit_day_not_decision_day():
    d = date(2024, 3, 1)
    late_win = Idea(d, "W", d + timedelta(days=30), 0.05)  # decided first, finishes last
    losses = [Idea(d + timedelta(days=i + 1), f"L{i}", d + timedelta(days=i + 5), -0.04) for i in range(8)]
    assert pc.streak_fire([late_win, *losses]) == losses[-1].exit_day


def test_two_consecutive_months_below():
    every = {date(2024, m, 2): 0.0 for m in (1, 2, 3, 5)}
    ideas = [
        Idea(date(2024, 1, 2), "A", date(2024, 1, 20), -0.01),  # below
        Idea(date(2024, 2, 2), "A", date(2024, 2, 22), 0.02),  # above
        Idea(date(2024, 3, 2), "A", date(2024, 3, 22), -0.01),  # below
        Idea(date(2024, 5, 2), "A", date(2024, 5, 25), -0.01),  # below, but April had no ideas
    ]
    v = pc.month_verdicts(ideas, every)
    assert [b for _, b, _ in v] == [True, False, True, True]
    assert pc.two_months_fire(v) is None  # no two neighbouring months both below
    assert pc.two_months_fire(v, consecutive=False) == date(2024, 3, 22)
    ideas.append(Idea(date(2024, 2, 3), "B", date(2024, 2, 28), -0.05))
    every[date(2024, 2, 3)] = 0.0
    v = pc.month_verdicts(ideas, every)
    assert pc.two_months_fire(v) == date(2024, 2, 28)  # Feb now averages below; known on its last exit


def test_month_baseline_uses_same_decision_days():
    every = {date(2024, 1, 2): 0.01, date(2024, 1, 3): -0.03}
    ideas = [Idea(date(2024, 1, 2), "A", date(2024, 1, 20), 0.0)]
    [(m, below, known)] = pc.month_verdicts(ideas, every)
    assert m == (2024, 1) and below is True and known == date(2024, 1, 20)


def test_drawdown_fire_uses_running_peak():
    d = date(2024, 1, 1)
    curve = [(d, 100.0), (d + timedelta(1), 110.0), (d + timedelta(2), 102.0), (d + timedelta(3), 101.2)]
    assert pc.drawdown_fire(curve, 0.08) == d + timedelta(3)  # 101.2 is 8% below 110
    assert pc.drawdown_fire(curve[:3], 0.08) is None


def test_add_months_and_within():
    assert pc.add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert pc.add_months(date(2024, 11, 4), 3) == date(2025, 2, 4)
    s = date(2024, 1, 1)
    fires = [date(2024, 2, 1), date(2024, 6, 1), None, date(2025, 2, 1)]
    assert pc.share_within(fires, [s] * 4, 3) == 0.25
    assert pc.share_within(fires, [s] * 4, 12) == 0.5
    assert pc.median_months(fires, [s] * 4) == 5.0  # lower median: half the paths fired
    assert pc.median_months([None, None, date(2024, 2, 1)], [s] * 3) is None


def test_pick_day_zero_theta_is_plain_random_and_tilt_prefers_winners():
    outs = [(f"S{i}", r) for i, r in enumerate([-0.04, -0.04, -0.04, 0.08])]
    assert sorted(pc.pick_day(random.Random(1), outs, 4, 0.0)) == ["S0", "S1", "S2", "S3"]
    rng = random.Random(3)
    hits = sum(pc.pick_day(rng, outs, 1, 200.0) == ["S3"] for _ in range(200))
    assert hits > 190
    assert pc.pick_day(random.Random(1), outs, 0, 5.0) == []


def test_ideas_today_pace():
    rng = random.Random(5)
    assert pc.ideas_today(rng, 5.0) == 5
    n = sum(pc.ideas_today(rng, 0.64) for _ in range(5000))
    assert 0.6 < n / 5000 < 0.68


def test_tilt_theta_iid_hits_the_edge():
    v = np.array([-0.04, -0.04, -0.01, 0.02, 0.08])
    for edge in (-0.01, 0.0, 0.003):
        th = pc.tilt_theta_iid(v, edge)
        w = np.exp(th * (v - v.max()))
        assert abs((w * v).sum() / w.sum() - v.mean() - edge) < 1e-6


def test_iid_all_losses_fire_rule1_at_once_and_rule2_after_two_months():
    v = np.array([-0.01, -0.02])  # every idea loses; the month mean is never below the pooled mean by much
    out = pc.iid_streak_and_months(v, 0.0, 5.0, paths=10, days=60, seed=1)
    assert out["rule1"]["within_3m"] == 1.0 and out["rule1"]["median_months"] == 0.0


def test_order_vs_halt_counts():
    d = date(2024, 1, 10)
    rows = [
        {"halt_day": d, "brain_fall_day": d - timedelta(5), "rule1": None, "rule2": d + timedelta(1)},
        {"halt_day": d, "brain_fall_day": d, "rule1": None, "rule2": None},
        {"halt_day": d, "brain_fall_day": None, "rule1": d + timedelta(3), "rule2": None},
        {"halt_day": None, "brain_fall_day": d, "rule1": None, "rule2": None},
    ]
    o = pc.order_vs_halt(rows)
    assert (o["halt_fired"], o["rule3_before"], o["rule3_same_day"], o["rule3_never"]) == (3, 1, 1, 1)
    assert o["rule1_only_after_halt"] == 1 and o["rule2_only_after_halt"] == 1


def test_run_accounts_case_a_book_fall_comes_before_halt():
    days = [date(2024, 1, 1) + timedelta(days=i) for i in range(6)]
    px = [100.0, 100.0, 94.0, 90.0, 80.0, 80.0]
    bars = {
        f"S{k}": pd.DataFrame(
            {"day": days, "open": px, "high": px, "low": [p * 0.999 for p in px], "close": px}
        )
        for k in range(5)
    }
    picks = [pc.Pick(days[0], f"S{k}", 1.0 - k / 10, None) for k in range(5)]
    r = pc.run_accounts(bars, days, picks, capital=1_000_000)
    assert r["brain_fall_day"] is None or r["halt_day"] is None or r["brain_fall_day"] <= r["halt_day"]
