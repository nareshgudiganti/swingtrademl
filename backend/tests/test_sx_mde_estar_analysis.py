"""Pure tests for the MDE_H / E* / duration analysis script (no database, no real prices, no model)."""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import numpy as np
import pytest

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "sx_mde_estar_analysis.py"
_spec = importlib.util.spec_from_file_location("sx_mde_estar_analysis", _PATH)
X = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(X)  # type: ignore[union-attr]


def test_round_trip_cost_known_answers():
    # large: 11.9 + 10.4 + 2*10 + 15.93/100000*10000 = 43.893 bps
    assert X.round_trip_cost_bps("large") == pytest.approx(43.893)
    assert X.round_trip_cost_bps("mid") == pytest.approx(63.893)
    # the 15-day note's figure: 5 bps slippage a side on a Rs 40,000 position -> about 0.36%
    assert X.round_trip_cost_bps(slip_bps=5.0, notional=40_000.0) == pytest.approx(36.2825, abs=1e-3)


def test_analytic_mde_known_answer():
    # (1.95996 + 0.84162) x 0.0583 = 0.16334
    assert X.analytic_mde(0.0583) == pytest.approx(0.16334, abs=2e-4)
    assert X.analytic_mde(0.1, alpha=0.05, power=0.5) == pytest.approx(0.16449, abs=1e-4)


def test_outcome_word_order_matches_verdict_code():
    assert X.outcome_word(True, True, True, 9.0, 0.16) == "PASS"
    assert X.outcome_word(True, True, False, 9.0, 0.16) == "INCONCLUSIVE"  # R4 fails
    assert X.outcome_word(True, False, True, 9.0, 0.16) == "INCONCLUSIVE"  # R1 fails
    assert X.outcome_word(False, False, False, 0.10, 0.16) == "FAIL"  # R2 not met, upper below MDE_H
    assert X.outcome_word(False, True, True, 0.10, 0.16) == "FAIL"  # R1/R4 cannot rescue a FAIL
    assert X.outcome_word(False, True, True, 0.16, 0.16) == "INCONCLUSIVE"  # upper == MDE_H is not below
    assert X.outcome_word(False, True, True, 0.20, 0.16) == "INCONCLUSIVE"


def test_synthetic_fold_days_sums_and_balance():
    fd = X.synthetic_fold_days(1000, 53)
    assert sum(fd) == 1000 and len(fd) == 53 and max(fd) - min(fd) <= 1


def test_interp_first_crossing_known():
    xs = [0.0, 0.1, 0.2, 0.3]
    assert X.interp_first_crossing(xs, [0.0, 0.4, 0.9, 1.0], 0.8) == pytest.approx(0.18)
    assert X.interp_first_crossing(xs, [0.0, 0.1, 0.2, 0.3], 0.8) is None


def test_estar_candidates_arithmetic():
    out = X.estar_candidates(
        gross_every_stock_pct=0.05, edge_a_pct=0.0, cost_pct=0.44, se_mean_pp=0.06, mde80_pp=0.17
    )
    assert out["E_costs"] == pytest.approx(0.44)
    assert out["E_breakeven"] == pytest.approx(0.39)
    assert out["E_sd"] == pytest.approx(0.0987)
    assert out["E_mde80"] == pytest.approx(0.17)


def test_independent_days_scale_with_inverse_square():
    a = X.independent_days_needed(1.0, 0.1)
    b = X.independent_days_needed(1.0, 0.2)
    assert a == pytest.approx(4 * b)
    assert a == pytest.approx(((1.959964 + 0.841621) / 0.1) ** 2, rel=1e-4)


def test_fold_days_file_counts():
    fd = X.read_fold_days_all(5)
    assert len(fd) == 34 and sum(fd) == 642
    assert sum(fd[X.BURN_IN :]) == 565  # the series the verdict counts (folds 4-33, 0-based)
    assert len(fd[X.BURN_IN :]) == 30


def _tiny(**over):
    kw = dict(
        h=5, phi=0.5, rho_ac=0.8, n_sims=30, fold_days=X.synthetic_fold_days(120, 6), burn_in=1,
        holdout_days=20, sd=np.full(12, 1.5), rho_c=0.25, df=5.0, seed_key=(9, 9, 9, 9),
        deltas=np.array([0.0, 0.5, 5.0]), mdes=(0.1, 100.0), draws=300,
    )
    kw.update(over)
    return X.simulate_outcomes(**kw)


def test_simulation_is_deterministic_and_words_sum_to_one():
    # draws=300 would break the fixed 2000-draw bound indices; so use the real draw count with a tiny panel
    a = _tiny(draws=2000)
    b = _tiny(draws=2000)
    assert a == b
    for m in a["words_2_5"].values():
        tot = np.array(m["PASS"]) + np.array(m["FAIL"]) + np.array(m["INCONCLUSIVE"])
        assert np.allclose(tot, 1.0)
    assert a["counted_days"] == 100 and a["counted_folds"] == 5 and a["r1_threshold"] == 3


def test_huge_edge_always_passes_and_never_fails():
    r = _tiny(draws=2000)
    i = r["deltas"].index(5.0)
    assert r["tallies"]["pass_25"][i] == 1.0
    assert r["words_2_5"]["0.1"]["FAIL"][i] == 0.0


def test_huge_mde_makes_fail_the_complement_of_r2_when_no_edge():
    # with MDE_H = 100 the upper bound is always below it, so FAIL == (R2 not met) and PASS needs R2
    r = _tiny(draws=2000)
    fail = np.array(r["words_2_5"]["100.0"]["FAIL"])
    r2 = np.array(r["tallies"]["r2_25"])
    assert np.allclose(fail, 1.0 - r2)


def test_no_holdout_means_r4_is_not_applied():
    r = _tiny(holdout_days=0, draws=2000)
    assert all(v == 1.0 for v in r["tallies"]["r4"])


def test_mc_se_is_binomial():
    assert math.isclose(X.S.mc_se(0.5, 2000), math.sqrt(0.25 / 2000))


def test_days_needed_from_cells_interpolates():
    def cell(p):
        return {"tallies": {"r2_25": [0.0, p]}, "deltas": [0.0, 0.1]}

    cells = {"dur|h5|central|T1000": cell(0.4), "dur|h5|central|T2000": cell(0.9)}
    # power 0.4 at T=1000 and 0.9 at T=2000 -> 80% at T = 1000 + (0.8-0.4)/(0.5) x 1000 = 1800
    assert X.days_needed_from_cells(cells, "dur", 5, "central", "r2_25", 0.1, [1000, 2000]) == pytest.approx(1800.0)
    assert X.days_needed_from_cells(cells, "dur", 5, "central", "r2_25", 0.1, [1000]) is None


def test_analytic_days_r2_only_scales_with_inverse_square_edge():
    a = X.analytic_days_r2_only(0.06, 565, 0.10)
    b = X.analytic_days_r2_only(0.06, 565, 0.20)
    assert a == pytest.approx(4 * b)
    # at the edge equal to the MDE80 of the current length, the answer is the current length
    assert X.analytic_days_r2_only(0.06, 565, X.analytic_mde(0.06)) == pytest.approx(565.0)


def test_independent_days_for_known_sd():
    # sd 1.275 pp, edge 0.17 pp: ((1.95996+0.84162) x 1.275 / 0.17)^2 = 441.3
    assert X.independent_days_needed(1.275, 0.17) == pytest.approx(441.3, abs=0.5)
