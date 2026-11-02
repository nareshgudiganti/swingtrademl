"""Selection lab: the ranking evaluation over folds, by market condition. Ranking only."""

from __future__ import annotations

import math
from datetime import date, timedelta

import pandas as pd
import pytest

from swing_trade_ml.brain import selection_lab as sl

D0 = date(2023, 1, 2)


def make_bars(n=800, drift=0.0, amp=0.12, phase=0.0):
    rows, prev = [], 100.0
    for i in range(n):
        wave = 1 + amp * math.sin(2 * math.pi * i / 60 + phase)
        p = 100.0 * wave * (1 + drift) ** i
        rows.append({"day": D0 + timedelta(days=i), "open": prev, "close": p, "volume": 5_000_000.0})
        prev = p
    return pd.DataFrame(rows)


def universe(n=15):
    return {f"S{i:02d}": make_bars(phase=2 * math.pi * i / n) for i in range(n)}


def foresight(bars):
    """Scores equal to the true 15-day return: a model with perfect skill (better than momentum)."""

    def scores(fold):
        out = {}
        for s, df in bars.items():
            per = {}
            for d in df["day"]:
                if fold.start <= d <= fold.end:
                    r = sl.forward_return(df, d)
                    if r is not None:
                        per[d] = r
            out[s] = per
        return out

    return scores


def guess(bars):
    """A score that does not depend on the future at all."""
    return lambda fold: {
        s: {d: float(hash((s, d)) % 1000) for d in df["day"] if fold.start <= d <= fold.end}
        for s, df in bars.items()
    }


def test_make_folds_matches_the_other_protocols_windows():
    folds = sl.make_folds(date(2023, 7, 1), date(2023, 9, 22))
    assert [(f.start, f.end) for f in folds] == [
        (date(2023, 7, 1), date(2023, 7, 28)),
        (date(2023, 7, 29), date(2023, 8, 25)),
        (date(2023, 8, 26), date(2023, 9, 22)),
    ]
    assert all(f.cutoff == f.start - timedelta(days=1) for f in folds)


def test_the_market_label_follows_the_average_move_of_the_window():
    up = {"A": make_bars(drift=0.01, amp=0), "B": make_bars(drift=0.01, amp=0)}
    down = {"A": make_bars(drift=-0.01, amp=0)}
    flat = {"A": make_bars(drift=0.0, amp=0)}
    s, e = date(2023, 3, 1), date(2023, 3, 28)
    assert sl.market_label(up, s, e) == "rising"
    assert sl.market_label(down, s, e) == "falling"
    assert sl.market_label(flat, s, e) == "sideways"
    assert sl.market_label({}, s, e) == "unknown"


def test_momentum_is_the_trailing_twenty_bar_gain_known_at_the_close():
    bars = {"A": make_bars(drift=0.01)}
    d = bars["A"].iloc[100]["day"]
    m = sl.momentum_scores(bars, [d])["A"][d]
    assert m == pytest.approx(bars["A"].iloc[100]["close"] / bars["A"].iloc[80]["close"] - 1)
    assert d not in sl.momentum_scores(bars, [bars["A"].iloc[5]["day"]])["A"]


def test_a_model_with_perfect_foresight_passes_the_ranking_rules_and_says_it_is_ranking_only():
    bars = universe()
    folds = sl.make_folds(date(2023, 10, 1), date(2024, 9, 30))
    res = sl.evaluate_ranking(bars, folds, foresight(bars), list(bars))
    assert res["r1"]["passes"] and res["r1"]["mean_ic"] > 0.9
    assert res["r2"]["passes"] and res["r3"]["passes"]
    assert res["ranking_verdict"] == "pass"
    assert res["qualifies_for_winner"] is False  # the money verdict is not evaluated
    assert res["money"].startswith("not evaluated")
    assert "Ranking and trading are different questions" in res["statement"]


def test_a_model_that_knows_nothing_does_not_pass():
    bars = universe()
    folds = sl.make_folds(date(2023, 10, 1), date(2024, 9, 30))
    res = sl.evaluate_ranking(bars, folds, guess(bars), list(bars))
    assert not res["r1"]["passes"] and res["ranking_verdict"] in ("fail", "insufficient")


def test_results_are_split_by_market_condition_and_the_folds_are_listed():
    bars = universe()
    folds = sl.make_folds(date(2023, 10, 1), date(2024, 9, 30))
    res = sl.evaluate_ranking(bars, folds, foresight(bars), list(bars))
    assert res["folds"] and {"start", "end", "regime", "days", "mean_ic"} <= set(res["folds"][0])
    by = res["by_market_condition"]
    assert by and sum(v["days"] for v in by.values()) == res["r1"]["days"]
    assert all(v["mean_ic"] is not None for v in by.values())


def test_each_fold_scores_only_what_the_models_cutoff_allows():
    bars = universe()
    folds = sl.make_folds(date(2023, 10, 1), date(2024, 1, 31))
    seen = []

    def spy(fold):
        seen.append((fold.cutoff, fold.start))
        return foresight(bars)(fold)

    sl.evaluate_ranking(bars, folds, spy, list(bars))
    assert all(c == s - timedelta(days=1) for c, s in seen) and len(seen) == len(folds)


def test_r4_is_added_when_a_comparison_model_is_given():
    bars = universe()
    folds = sl.make_folds(date(2023, 10, 1), date(2024, 9, 30))
    base = sl.evaluate_ranking(bars, folds, guess(bars), list(bars))
    better = sl.evaluate_ranking(
        bars, folds, foresight(bars), list(bars), comparison_ic=base["ic_by_day"], r4_mode="better"
    )
    assert better["r4"]["passes"]
    assert "r4" not in base


def test_stocks_with_too_little_history_are_not_scored():
    bars = universe()
    bars["NEW"] = (
        make_bars(n=800).iloc[600:].reset_index(drop=True)
    )  # listed late: under 220 bars at fold time
    folds = sl.make_folds(date(2024, 8, 1), date(2024, 9, 30))
    res = sl.evaluate_ranking(bars, folds, foresight(bars), list(bars))
    assert res["r1"]["days"] > 0 and res["stocks_scored_max"] <= 15


def test_the_lab_contains_no_money_management():
    import ast
    import inspect

    src = inspect.getsource(sl)
    tree = ast.parse(src)
    imported = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    banned_modules = (
        "portfolio_sim",
        "replay_scoring",
        "costs",
        "risk",
        "execution",
        "brokers",
        "strategies",
    )
    assert not [m for m in imported if any(b in m for b in banned_modules)], imported
    # the code itself (names, not explanatory text) carries no sizing, cost, account or net-profit idea
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    names |= {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    for word in ("capital", "position_inr", "slippage", "brokerage", "drawdown", "sector_cap", "net_return"):
        assert not [n for n in names if word in n.lower()], word


# ---------------------------------------------------------------- cap groups, benchmark, limited sample


def test_cap_groups_report_each_group_against_its_own_median_and_its_own_average():
    bars = universe(20)
    large, mid = list(bars)[:6], list(bars)[6:]  # 6 and 14 stocks
    folds = sl.make_folds(date(2024, 5, 1), date(2024, 9, 30))
    res = sl.evaluate_ranking(bars, folds, foresight(bars), list(bars), groups={"large": large, "mid": mid})
    assert set(res["by_cap_group"]) == {"large", "mid"}
    g = res["by_cap_group"]["mid"]
    assert g["stocks_listed"] == 14 and g["stocks_scored"] == 14 and g["days"] > 0
    assert g["top5_excess_over_median"] > 0 and g["top5_excess_over_group_average"] > 0
    assert g["mean_ic"] > 0.9 and g["hit_share"] is not None
    # a group of 6 stocks has fewer than the 10 needed on a day: no day is measured for it
    assert res["by_cap_group"]["large"]["days"] == 0
    assert "same group" in res["benchmark"] or "SAME group" in res["benchmark"]


def test_the_group_average_benchmark_is_below_the_median_one_for_a_skewed_day():
    scores = {f"A{i}": {date(2024, 1, 2): float(i)} for i in range(10)}
    rets = {(f"A{i}", date(2024, 1, 2)): (0.5 if i == 9 else 0.0) for i in range(10)}
    top = sl.top5_measures(scores, rets)
    # best 5 = A9..A5 mean 0.1; median 0.0; group average 0.05
    assert top["excess"] == pytest.approx(0.1) and top["excess_vs_mean"] == pytest.approx(0.05)


def test_no_groups_given_means_an_empty_split_and_the_old_keys_stay():
    bars = universe()
    res = sl.evaluate_ranking(
        bars, sl.make_folds(date(2024, 8, 1), date(2024, 9, 30)), foresight(bars), list(bars)
    )
    assert res["by_cap_group"] == {} and {"r1", "r2", "r3", "ranking_verdict", "ic_by_day", "top5"} <= set(
        res
    )


def test_a_group_under_30_stocks_carries_the_warning_and_the_capped_label():
    bars = universe(15)
    res = sl.evaluate_ranking(
        bars, sl.make_folds(date(2024, 8, 1), date(2024, 9, 30)), foresight(bars), list(bars)
    )
    assert res["sample_warning"] == (
        "Limited experiment: 15 stocks. Wide uncertainty. Not a basis for trading approval on its own."
    )
    assert res["label"] == "NO WARNING (diagnostic, limited sample)" and res["qualifies_for_winner"] is False
    assert sl.sample_warning(30) is None and sl.sample_warning(29) is not None


def test_held_back_guard_names_the_list_and_the_stocks():
    with pytest.raises(ValueError, match=r"Held-back stocks found in mid: R1"):
        sl.assert_no_held_back(["R1", "R2"], used49=["A"], mid=["B", "R1"])
    sl.assert_no_held_back(["R1"], used49=["A"], mid=["B"])
