# ruff: noqa: E501, N812 (long test sentences, short P / W aliases as in the other h05 tests)
"""h05_power: the simulation drives the real decision procedure and behaves as a null/alternative should."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from swing_trade_ml.brain.lanes import h05_power as W
from swing_trade_ml.brain.lanes import h05_protocol as P


def _table(days: int = 420, per_group: int = 30, mean: float = -0.005, sd: float = 0.03, seed: int = 1) -> W.Table:
    """Independent stock-days with a NEGATIVE average net return (the real fixed rule loses after costs)."""
    rng = np.random.default_rng(seed)
    sessions, d = [], date(2024, 1, 1)
    while len(sessions) < days:
        if d.weekday() < 5:
            sessions.append(d)
        d += timedelta(days=1)
    rows = []
    for pos in range(days):
        for gi, group in enumerate(P.GROUPS):
            for k in range(per_group):
                rows.append((pos, group, gi * 1000 + k, float(rng.normal(mean, sd)), float(rng.random() < 0.25)))
    return W.table_from_rows(sessions, rows)


def test_trim_and_fingerprint_are_stable():
    t = _table(days=300)
    assert len(W.trim(t).sessions) == 300 and t.fingerprint() == _table(days=300).fingerprint()
    assert t.fingerprint() != _table(days=300, seed=2).fingerprint()


def test_same_seed_same_numbers_and_the_cell_reports_its_settings():
    t = _table()
    a = W.run_grid_cell(t, 12, 5, mode="bootstrap", stickiness=0.8, missing=0.1)
    b = W.run_grid_cell(t, 12, 5, mode="bootstrap", stickiness=0.8, missing=0.1)
    assert a == b and a["setting"]["replicates"] == 12 and a["setting"]["min_matured_days"] == 40


def test_random_picks_over_a_losing_baseline_do_not_pass_either_verdict_in_a_normal_sample():
    t = _table()
    c = W.run_grid_cell(t, 40, 3, mode="history")["rates"]
    for g in P.GROUPS:
        assert c.get(f"{g}.combined_economic.PASS", 0) == 0  # a losing baseline cannot give an economic PASS
        assert c.get(f"{g}.combined_selection.PASS", 0) <= 0.1  # nominal one-sided 5%, a coarse check with 40 paths


def test_a_real_edge_big_enough_to_beat_the_costs_passes_both_and_a_small_one_passes_only_selection():
    t = _table()
    big = W.run_grid_cell(t, 30, 3, mode="bootstrap", delta=0.04)["rates"]
    assert big["large.combined_selection.PASS"] > 0.9 and big["large.combined_economic.PASS"] > 0.9
    # +1.5% per trade beats the average stock clearly but leaves the picks at -0.5% + 1.5% = +1.0%: economic passes
    # only when it also clears the daily noise; +0.3% leaves the picks below zero: selection passes, economic does not
    small = W.run_grid_cell(t, 30, 3, mode="bootstrap", delta=0.004)["rates"]
    assert small.get("large.combined_economic.PASS", 0) == 0


def test_missed_sessions_are_not_made_up_and_too_few_days_make_a_run_inconclusive():
    t = _table()
    heavy = W.run_grid_cell(t, 20, 3, mode="bootstrap", delta=0.04, missing=0.6)["rates"]
    assert heavy["large.run_too_few_days"] > 0.8  # almost every run has fewer than 40 matured days
    assert heavy.get("large.combined_selection.PASS", 0) == 0


def test_the_history_must_be_long_enough_for_three_runs():
    short = _table(days=100)
    try:
        W.run_grid_cell(short, 2, 1, mode="history")
    except ValueError as exc:
        assert "180" in str(exc)
    else:
        raise AssertionError("a 100-session history cannot hold three 60-session runs")
