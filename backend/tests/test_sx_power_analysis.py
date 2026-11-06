"""Pure tests for the S-9 power-analysis script (no database, no real prices, no model)."""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import numpy as np
import pytest

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "sx_power_analysis.py"
_spec = importlib.util.spec_from_file_location("sx_power_analysis", _PATH)
sx = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sx)  # type: ignore[union-attr]


def test_r1_threshold_known_answers():
    assert sx.r1_threshold(34) == 21  # 20/34 = 58.8% is below 60%
    assert sx.r1_threshold(30) == 18  # exactly 60%
    assert sx.r1_threshold(10) == 6


def test_fold_means_known():
    d = np.array([1.0, 3.0, 2.0, 2.0, 2.0, 10.0])
    assert sx.fold_means(d, [2, 3, 1]).tolist() == [2.0, 2.0, 10.0]


def test_top_k_mean_known():
    scores = np.array([[0.1, 0.9, 0.5, 0.7, 0.3, 0.2]])
    values = np.array([[10.0, 1.0, 2.0, 3.0, 4.0, 5.0]])
    assert sx.top_k_mean(values, scores, k=2)[0] == pytest.approx((1.0 + 3.0) / 2)


def test_rolling_forward_sum_known():
    daily = np.arange(1.0, 9.0)[:, None]  # rows 0..7 = 1..8; row 0 unused
    out = sx.rolling_forward_sum(daily, h=3, t=4)  # t=0 -> rows 1..3 = 2+3+4
    assert out[:, 0].tolist() == [9.0, 12.0, 15.0, 18.0]


def test_barrier_label_known_and_same_bar_tie_is_stop():
    close = np.array([100.0] * 6)
    high = np.array([100, 101, 107, 100, 100, 100.0])  # day 2 touches +6%
    low = np.array([100, 99, 99, 100, 100, 100.0])
    assert sx.barrier_label(close, high, low, 3, 0.06, 0.035).tolist() == [1, 1, 0]  # last 3 rows dropped
    low_tie = np.array([100, 99, 95, 100, 100, 100.0])  # day 2 touches both -> stop
    assert sx.barrier_label(close, high, low_tie, 3, 0.06, 0.035).tolist()[0] == 0


def test_block_bootstrap_constant_and_shape():
    rng = np.random.default_rng(1)
    (b,) = sx.block_means_bootstrap([np.full(50, 2.5)], block=10, draws=200, rng=rng)
    assert b.shape == (200,) and np.allclose(b, 2.5)
    # block as long as the series: every draw is the full-series mean
    x = np.arange(12.0)
    (b2,) = sx.block_means_bootstrap([x], block=100, draws=5, rng=np.random.default_rng(2))
    assert np.allclose(b2, x.mean())


def test_block_bootstrap_se_matches_theory_for_iid():
    rng = np.random.default_rng(3)
    x = np.random.default_rng(4).standard_normal(600)
    (b,) = sx.block_means_bootstrap([x], block=10, draws=4000, rng=rng)
    assert b.std() == pytest.approx(x.std() / math.sqrt(600), rel=0.12)


def test_effective_n_acf_iid_vs_persistent():
    rng = np.random.default_rng(5)
    iid = rng.standard_normal(5000)
    assert sx.effective_n_acf(iid, 20) > 0.8 * 5000
    z = sx.ar1_panel(rng, 5000, 1, 0.9)[:, 0]
    # AR(1) 0.9: variance inflation (1+phi)/(1-phi) = 19 -> n_eff about n/19 (taper and truncation bias it upward)
    assert 5000 / 40 < sx.effective_n_acf(z, 40) < 5000 / 8


def test_ar1_panel_lag1_and_variance():
    z = sx.ar1_panel(np.random.default_rng(6), 20000, 3, 0.7)
    assert z.var() == pytest.approx(1.0, abs=0.05)
    assert np.corrcoef(z[:-1, 0], z[1:, 0])[0, 1] == pytest.approx(0.7, abs=0.03)


def test_overlap_autocorrelation_of_forward_returns_is_triangular():
    h = 5
    r = sx.simulate_noise_returns(np.random.default_rng(7), 6000, h, np.full(4, 1.0), 0.0, None)
    for k in (1, 2, 4):
        c = np.corrcoef(r[:-k, 0], r[k:, 0])[0, 1]
        assert c == pytest.approx((h - k) / h, abs=0.05)
    assert abs(np.corrcoef(r[:-6, 0], r[6:, 0])[0, 1]) < 0.05  # no overlap beyond the horizon


def test_mde_from_curve_interpolates_and_none():
    d = np.array([0.0, 1.0, 2.0, 3.0])
    p = np.array([0.0, 0.4, 0.9, 1.0])
    assert sx.mde_from_curve(d, p, 0.5) == pytest.approx(1.2)
    assert sx.mde_from_curve(d, p, 0.8) == pytest.approx(1.8)
    assert sx.mde_from_curve(d, np.array([0, 0.1, 0.2, 0.3]), 0.8) is None


def test_holm_family_false_pass_known_flags():
    # columns r1, p25, p5, r4
    a = np.array([[1, 1, 1, 1], [1, 0, 1, 1], [1, 0, 1, 1], [0, 1, 1, 1]], dtype=bool)
    b = np.array([[0, 0, 0, 0], [0, 1, 1, 0], [0, 0, 1, 0], [0, 0, 0, 0]], dtype=bool)
    # sim0: A passes at 2.5%; sim1: A passes at 5% because B cleared 2.5%; sim2: A only 5%, B not 2.5% -> no;
    # sim3: A fails R1 -> no
    assert sx.holm_family_false_pass(a, b, with_r4=False) == pytest.approx(0.5)


_SMALL = dict(
    h=5,
    mode="paired",
    fold_days=[20] * 6,
    holdout_days=20,
    sd=np.full(20, 1.5),
    rho_c=0.15,
    df=6.0,
    vol_cluster=0.0,
    draws=400,
    n_grid=9,
    grid_max_se=5.0,
)


@pytest.fixture(scope="module")
def small_cell():
    return sx.simulate_cell(phi=0.5, rho_ac=0.8, n_sims=300, seed_key=(5, 0, 0, 99), **_SMALL)


def test_power_is_monotone_in_edge_and_null_is_controlled(small_cell):
    v = small_cell["variants"]["f34"]
    for key in ("r1p25", "p25", "r1p5"):
        p = np.asarray(v[key])
        assert np.all(np.diff(p) >= -0.06)  # monotone up to Monte Carlo noise (common random numbers)
        assert p[-1] > 0.6
    assert v["p25"][0] < 0.08  # nominal 2.5%, block 2h in a small sample: tolerant bound
    assert v["r1p5"][0] < 0.10
    assert v["r1p25"][0] <= v["p25"][0] + 1e-12  # adding R1 can only lower the pass rate


def test_deterministic_given_seed():
    a = sx.simulate_cell(phi=0.0, rho_ac=0.5, n_sims=20, seed_key=(5, 1, 1, 7), **_SMALL)
    b = sx.simulate_cell(phi=0.0, rho_ac=0.5, n_sims=20, seed_key=(5, 1, 1, 7), **_SMALL)
    assert a["variants"]["f34"]["p25"] == b["variants"]["f34"]["p25"]
    assert a["deltas"] == b["deltas"]


def test_true_edge_is_recovered_by_construction():
    # g_t has expectation 1, so D(delta) has expected value delta: check the mean of g in the paired mode
    h = 5
    rng = np.random.default_rng(8)
    n, t, rho = 47, 4000, 0.8
    m5 = sx.expected_top_k_mean(n)
    za, zn = sx.ar1_panel(rng, t, n, 0.0), sx.ar1_panel(rng, t, n, 0.0)
    zc = rho * za + math.sqrt(1 - rho**2) * zn
    g = (sx.top_k_mean(zn, zc) - sx.top_k_mean(zn, za)) / (m5 * math.sqrt(1 - rho**2))
    assert g.mean() == pytest.approx(1.0, abs=0.03)
    assert h == 5


def test_expected_top5_of_47_is_plausible():
    assert 1.6 < sx.expected_top_k_mean(47) < 1.75


def test_pick_repeat_share_grows_with_phi():
    rng = np.random.default_rng(9)
    low = sx.pick_repeat_share(sx.ar1_panel(rng, 800, 47, 0.0))
    high = sx.pick_repeat_share(sx.ar1_panel(rng, 800, 47, 0.9))
    assert low < 0.2 < 0.5 < high


def test_group_structure_clusters_picks_and_keeps_unit_variance():
    n = 47
    groups = np.arange(n) % 10
    rng = np.random.default_rng(10)
    z = sx.grouped_ar1_panel(rng, 3000, n, 0.0, groups, 0.3)
    assert z.var() == pytest.approx(1.0, abs=0.05)
    picks = sx.top_k_sets(z)
    distinct = np.mean([len(set(groups[row])) for row in picks])
    flat = np.mean([len(set(groups[row])) for row in sx.top_k_sets(sx.ar1_panel(rng, 3000, n, 0.0))])
    assert distinct < flat  # picks come from fewer groups when scores share a group component


def test_group_return_factor_raises_within_group_correlation():
    n = 20
    groups = np.arange(n) % 4
    r = sx.simulate_noise_returns(
        np.random.default_rng(11), 4000, 1, np.full(n, 1.0), 0.1, None, 0.0, groups, 0.2
    )
    same = np.corrcoef(r[:, 0], r[:, 4])[0, 1]  # both in group 0
    diff = np.corrcoef(r[:, 0], r[:, 1])[0, 1]
    assert same == pytest.approx(0.3, abs=0.06) and diff == pytest.approx(0.1, abs=0.06)
