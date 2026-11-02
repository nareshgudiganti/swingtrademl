"""Selection lab (design rev 3, section 6.1 and 6.3): the ranking verdict R1 to R4."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from swing_trade_ml.brain import selection_lab as sl

D0 = date(2024, 1, 1)


def days(n):
    return [D0 + timedelta(days=i) for i in range(n)]


def world(n_days=60, n_syms=15, skill=1.0, seed=1):
    """scores and returns for n_syms stocks over n_days; `skill` = how much the score tracks the return."""
    rng = np.random.default_rng(seed)
    scores, rets = {}, {}
    syms = [f"S{i:02d}" for i in range(n_syms)]
    for s in syms:
        scores[s] = {}
    for d in days(n_days):
        base = rng.normal(size=n_syms)
        noise = rng.normal(size=n_syms)
        for i, s in enumerate(syms):
            scores[s][d] = float(base[i])
            rets[(s, d)] = float(0.02 * (skill * base[i] + (1 - skill) * noise[i]))
    return scores, rets


def test_daily_ic_is_the_rank_correlation_of_score_and_return_each_day():
    scores, rets = world(skill=1.0)
    ic = sl.daily_ic(scores, rets)
    assert len(ic) == 60 and all(v == pytest.approx(1.0) for v in ic.values())
    scores, rets = world(skill=0.0)
    assert abs(np.mean(list(sl.daily_ic(scores, rets).values()))) < 0.15


def test_days_with_fewer_than_ten_scored_stocks_are_left_out_and_counted():
    scores, rets = world(n_syms=9)
    assert sl.daily_ic(scores, rets) == {}
    scores, rets = world(n_syms=10)
    assert len(sl.daily_ic(scores, rets)) == 60


def test_days_where_every_score_or_every_return_is_equal_are_left_out():
    scores, rets = world()
    d = days(1)[0]
    for s in scores:
        scores[s][d] = 1.0
    ic = sl.daily_ic(scores, rets)
    assert d not in ic and len(ic) == 59


def test_block_quantile_uses_runs_of_consecutive_days_and_is_repeatable():
    vals = list(np.random.default_rng(2).normal(0.05, 0.1, size=120))
    a = sl.block_quantile(vals, 0.0125)
    assert a == sl.block_quantile(vals, 0.0125)
    assert a < np.mean(vals) < sl.block_quantile(vals, 0.5) + 0.05
    assert sl.block_quantile(vals[:20], 0.0125) is None  # fewer than two blocks of 15: no honest bound


def test_r1_passes_only_when_the_mean_and_its_lower_bound_are_above_zero():
    scores, rets = world(n_days=120, skill=0.6)
    r1 = sl.r1(sl.daily_ic(scores, rets))
    assert r1["passes"] and r1["mean_ic"] > 0 and r1["lower_bound"] > 0 and r1["days"] == 120
    scores, rets = world(n_days=120, skill=0.0, seed=5)
    r1 = sl.r1(sl.daily_ic(scores, rets))
    assert not r1["passes"]


def test_r1_with_too_few_days_cannot_pass():
    scores, rets = world(n_days=20, skill=1.0)
    r1 = sl.r1(sl.daily_ic(scores, rets))
    assert r1["lower_bound"] is None and not r1["passes"]


def test_top5_excess_is_the_top_five_by_score_minus_the_day_median_with_ties_by_symbol():
    scores, rets = world(n_days=30, skill=1.0)
    out = sl.top5_measures(scores, rets)
    assert out["excess"] > 0 and out["days"] == 30
    assert 0.9 <= out["hit_share"] <= 1.0  # perfect skill: the top 5 sit in the top 30%
    assert out["spread"] > 0
    # exact ties are broken alphabetically
    d = days(1)[0]
    tied = {s: {d: 1.0} for s in [f"S{i:02d}" for i in range(12)]}
    r = {(s, d): float(i) for i, s in enumerate(tied)}
    assert sl.top_k(tied, d, 5) == ["S00", "S01", "S02", "S03", "S04"]
    assert sl.top5_measures(tied, r)["days"] == 1


def test_r2_needs_a_positive_excess_that_beats_momentum():
    assert sl.r2(0.004, 0.001)["passes"]
    assert not sl.r2(0.004, 0.006)["passes"]
    assert not sl.r2(-0.001, -0.005)["passes"]
    assert not sl.r2(None, 0.0)["passes"]


def test_r3_counts_eligible_folds_and_needs_sixty_percent_and_twelve_folds():
    good = [{"days": 20, "ideas": 100, "mean_ic": 0.05}] * 8 + [
        {"days": 20, "ideas": 100, "mean_ic": -0.02}
    ] * 4
    r3 = sl.r3(good)
    assert r3["eligible"] == 12 and r3["positive"] == 8 and r3["passes"]  # 8/12 = 67%
    short = good[:11]
    assert not sl.r3(short)["passes"] and sl.r3(short)["state"] == "insufficient"
    thin = [{"days": 9, "ideas": 100, "mean_ic": 0.1}] * 15 + [{"days": 20, "ideas": 10, "mean_ic": 0.1}] * 5
    assert sl.r3(thin)["eligible"] == 0


def test_r4_better_needs_a_positive_bound_and_not_worse_allows_a_small_negative_one():
    rng = np.random.default_rng(4)
    a = {d: float(0.06 + rng.normal(scale=0.05)) for d in days(150)}
    b = {d: float(0.01 + rng.normal(scale=0.05)) for d in days(150)}
    better = sl.r4(a, b, mode="better")
    assert better["passes"] and better["lower_bound"] > 0 and better["days"] == 150
    same = sl.r4(a, a, mode="not_worse")
    assert same["passes"] and same["lower_bound"] == pytest.approx(0.0)
    assert not sl.r4(a, a, mode="better")["passes"]
    worse = sl.r4(b, a, mode="not_worse")
    assert not worse["passes"]
    with pytest.raises(ValueError):
        sl.r4(a, b, mode="equal")


def test_r4_uses_only_days_both_models_scored():
    a = dict.fromkeys(days(100), 0.05)
    b = dict.fromkeys(days(40), 0.01)
    assert sl.r4(a, b, mode="better")["days"] == 40
