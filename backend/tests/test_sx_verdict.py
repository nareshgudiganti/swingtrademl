"""SX verdict code: SYNTHETIC records only. No real arm, holdout, model or database."""

from __future__ import annotations

import json
import random
from datetime import date

import pytest

from swing_trade_ml.brain import service as _brain_service  # noqa: F401  (import order: avoids a repo circular import)
from swing_trade_ml.brain import walk_forward as bwf
from swing_trade_ml.ml import sx_verdict as v

H = 5


def params(**kw):
    base = dict(horizon=H, mde_h=0.01)
    base.update(kw)
    return v.VerdictParams(**base)


def day_rows(start_ordinal, ds, n_stocks=14):
    out = []
    for i, x in enumerate(ds):
        d = date.fromordinal(start_ordinal + i).isoformat()
        out.append({"date": d, "n_stocks": n_stocks, "top_symbols": list("abcde"), "excess_vs_all": x})
    return out


def make_records(fold_d, kind="dev", base=730000, status=None):
    """fold_d: fold index -> list of paired differences D (arm A excess 0, arm C excess D)."""
    recs, off = [], base
    for f in sorted(fold_d):
        ds = fold_d[f]
        st = (status or {}).get(f, "ok")
        for arm in ("A_53", "R_37", "C_56"):
            vals = [x if arm == "C_56" else 0.0 for x in ds]
            recs.append(
                {
                    "arm": arm,
                    "fold": {"index": f, "kind": kind},
                    "status": st,
                    "daily": day_rows(off, vals) if st == "ok" else None,
                }
            )
        off += len(ds) + 3
    return recs


def folds(p, fn, days=15):
    return {i: fn(i, days) for i in p.counted_folds}


def const(c):
    return lambda i, n: [c] * n


def noisy_zero(seed=1, amp=0.004):
    def f(i, n):
        r = random.Random(seed * 1000 + i)
        xs = [r.uniform(-amp, amp) for _ in range(n // 2)]
        return xs + [-x for x in xs] + ([0.0] if n % 2 else [])

    return f


def boom():
    raise AssertionError("holdout was read")


# ---------------------------------------------------------------- parameters
def test_mde_missing_refuses():
    with pytest.raises(TypeError):
        v.VerdictParams(horizon=5)  # no default
    for bad in (None, 0, -1, float("nan")):
        with pytest.raises(v.VerdictRefused):
            v.VerdictParams(horizon=5, mde_h=bad)


def test_params_hash_canonical_and_stable():
    a, b = params(), params()
    assert a.canonical_json() == b.canonical_json() and a.sha256() == b.sha256()
    assert params(mde_h=0.02).sha256() != a.sha256()
    assert json.loads(a.canonical_json())["seed"] == 7 and a.block == 10 and params(horizon=10).block == 20


def test_fold_numbering_zero_based_with_burn_in():
    p = params()
    assert p.counted_folds == tuple(range(4, 34)) and len(p.counted_folds) == 30
    assert params(burn_in_folds=0).counted_folds == tuple(range(0, 34))
    with pytest.raises(v.VerdictRefused):
        v.VerdictParams(horizon=5, mde_h=0.01, burn_in_folds=5, last_fold_index=3)


def test_code_hash_normalises_line_endings(tmp_path):
    a, b = tmp_path / "a.py", tmp_path / "b.py"
    a.write_bytes(b"x = 1\ny = 2\n")
    b.write_bytes(b"x = 1\r\ny = 2\r\n")
    assert v.verdict_code_sha256(a) == v.verdict_code_sha256(b)
    assert len(v.verdict_code_sha256()) == 64


# ---------------------------------------------------------------- bootstrap convention
def test_bootstrap_reproduces_walk_forward_bootstrap_low():
    r = random.Random(5)
    vals = [r.uniform(-1, 1) for _ in range(120)]
    means = v.block_bootstrap_means(vals, 10, 2000, 7)
    assert v.lower_bound(means, 0.05) == bwf.bootstrap_low(vals, block=10, draws=2000, seed=7)
    assert v.block_bootstrap_means(vals[:19], 10, 2000, 7) is None  # n < 2 x block


def test_bound_indices_known_answer():
    m = [float(i) for i in range(2000)]
    assert v.lower_bound(m, 0.05) == 100.0 and v.lower_bound(m, 0.025) == 50.0
    assert v.upper_bound(m, 0.05) == 1899.0
    assert v.p_value([1.0] * 2000) == 1 / 2001
    assert v.p_value([-1.0] * 2000) == 1.0


# ---------------------------------------------------------------- outcomes
def test_pass_after_holdout_completed():
    p = params()
    dev = make_records(folds(p, const(0.002)))
    hold = make_records({0: [0.001] * 20}, kind="holdout", base=740000)
    out = v.compute_verdict(dev, p, holdout_records=hold, holdout_completed=True)
    assert out["outcome"] == v.PASS and out["r1"]["met"] and out["r2"]["met"] and out["r4"]["met"]
    assert out["n_paired_days"] == 30 * 15 and out["r3"]["eligible_folds"] == 30
    txt = v.render_plain_english(out)
    assert "works" not in txt.lower() and "PASS" in txt and "forward shadow" in txt


def test_r4_zero_or_negative_holdout_is_inconclusive():
    p = params()
    dev = make_records(folds(p, const(0.002)))
    for hv in (0.0, -0.001):
        hold = make_records({0: [hv] * 20}, kind="holdout", base=740000)
        out = v.compute_verdict(dev, p, holdout_records=hold, holdout_completed=True)
        assert out["outcome"] == v.INCONCLUSIVE and out["r4"]["met"] is False


def test_pending_when_holdout_not_completed_and_never_read():
    p = params()
    dev = make_records(folds(p, const(0.002)))
    out = v.compute_verdict(dev, p, holdout_records=boom, holdout_completed=False)
    assert out["outcome"] == v.PENDING_HOLDOUT and out["r4"]["evaluated"] is False
    out2 = v.compute_verdict(dev, p, holdout_records=boom, holdout_completed=lambda: False)
    assert out2["outcome"] == v.PENDING_HOLDOUT


def test_holdout_not_read_when_outcome_does_not_depend_on_it():
    p = params()
    dev = make_records(folds(p, noisy_zero()))
    out = v.compute_verdict(dev, p, holdout_records=boom, holdout_completed=True)
    assert out["outcome"] in (v.FAIL, v.INCONCLUSIVE) and out["r4"]["evaluated"] is False


def test_completed_without_records_refuses():
    p = params()
    dev = make_records(folds(p, const(0.002)))
    with pytest.raises(v.VerdictRefused):
        v.compute_verdict(dev, p, holdout_records=None, holdout_completed=True)


def test_holdout_kind_in_dev_input_refuses():
    p = params()
    with pytest.raises(v.VerdictRefused):
        v.compute_verdict(make_records(folds(p, const(0.002)), kind="holdout"), p)


def test_fail_reachable():
    p = params(mde_h=0.01)
    out = v.compute_verdict(make_records(folds(p, noisy_zero(amp=0.002))), p)
    assert not out["r2"]["met"] and out["bootstrap"]["upper"] < 0.01 and out["outcome"] == v.FAIL


def test_inconclusive_when_interval_straddles_mde():
    p = params(mde_h=1e-6)
    out = v.compute_verdict(make_records(folds(p, noisy_zero(amp=0.004))), p)
    assert not out["r2"]["met"] and out["bootstrap"]["upper"] >= 1e-6
    assert out["outcome"] == v.INCONCLUSIVE and "at or above MDE_H" in out["outcome_detail"]


def test_inconclusive_data_too_few_eligible_folds():
    p = params()
    d = folds(p, const(0.002))
    short = list(d)[:20]
    for i in short:
        d[i] = d[i][:5]  # ineligible: 5 days
    out = v.compute_verdict(make_records(d), p)
    assert out["r3"]["eligible_folds"] == 10 and out["outcome"] == v.INCONCLUSIVE
    assert out["outcome_detail"] == "data" and out["ineligible_folds"] == sorted(short)


def test_inconclusive_data_few_picks_and_few_days():
    p = params(min_eligible_folds=1, min_picks=100)
    d = {i: [0.002] * 3 for i in p.counted_folds}
    d[p.counted_folds[0]] = [0.002] * 10
    out = v.compute_verdict(make_records(d), p)
    assert out["r3"]["picks"] == 50 and out["outcome_detail"] == "data"
    p2 = params(
        min_eligible_folds=0, min_picks=0, min_fold_days=1, min_fold_picks=1, burn_in_folds=4, last_fold_index=4
    )
    out2 = v.compute_verdict(make_records({4: [0.002] * 9}), p2)  # 9 days < 2h = 10
    assert out2["n_paired_days"] == 9 and out2["outcome_detail"] == "data"


def test_skipped_fold_makes_data_inconclusive():
    p = params()
    d = folds(p, const(0.002))
    d[10] = []
    out = v.compute_verdict(make_records(d, status={10: "skipped_no_test_rows"}), p)
    assert out["outcome"] == v.INCONCLUSIVE and out["outcome_detail"] == "data"


def test_inconclusive_r2_met_but_r1_not_met():
    p = params()

    def f(i, n):  # 17 folds lose a little, 13 win big: pooled mean and bound above 0, only 13 wins of 30
        return [-0.0001] * n if i < 21 else [0.01] * n

    out = v.compute_verdict(make_records(folds(p, f)), p)
    assert out["r2"]["met"] and not out["r1"]["met"] and out["r1"]["wins"] == 13
    assert out["outcome"] == v.INCONCLUSIVE and "R1 not met" in out["outcome_detail"]


def test_r1_threshold_known_answer():
    p = params()

    def k(n_win):
        return lambda i, n: [0.001] * n if i - 4 < n_win else [-0.001] * n

    o18 = v.compute_verdict(make_records(folds(p, k(18))), p)
    o17 = v.compute_verdict(make_records(folds(p, k(17))), p)
    assert o18["r1"] == {"met": True, "wins": 18, "eligible": 30, "needed": 18}
    assert o17["r1"]["met"] is False and o17["r1"]["wins"] == 17


def test_zero_fold_mean_is_not_a_win():
    p = params()
    out = v.compute_verdict(make_records(folds(p, const(0.0))), p)
    assert out["r1"]["wins"] == 0 and not out["r2"]["met"]


# ---------------------------------------------------------------- Holm
def test_holm_single_horizon_uses_strict_bound():
    p = params(holm_mode="single_horizon")
    out = v.compute_verdict(make_records(folds(p, noisy_zero(amp=0.003))), p)
    assert out["holm"]["alpha"] == 0.025
    assert out["r2"]["lower_bound"] == out["bootstrap"]["lower_2_5pct"]


def test_holm_two_horizon_levels_and_requirement():
    p = params(holm_mode="two_horizon")
    base = make_records(folds(p, noisy_zero(amp=0.003)))
    with pytest.raises(v.VerdictRefused):
        v.compute_verdict(base, p)
    me = v.compute_verdict(base, p, other_horizon_p=1.0)["holm"]
    assert me["alpha"] == 0.025  # my p is smaller
    assert v.compute_verdict(base, p, other_horizon_p=1e-9)["holm"]["alpha"] == 0.05
    assert v.compute_verdict(base, p, other_horizon_p=me["p_this_horizon"])["holm"]["alpha"] == 0.025  # SX5 wins ties

    p10 = params(horizon=10, holm_mode="two_horizon")
    rec10 = make_records(folds(p10, noisy_zero(amp=0.003), days=25))
    p_self = v.compute_verdict(rec10, p10, other_horizon_p=1.0)["holm"]["p_this_horizon"]
    assert v.compute_verdict(rec10, p10, other_horizon_p=p_self)["holm"]["alpha"] == 0.05  # SX10 loses ties


# ---------------------------------------------------------------- inputs, determinism
def test_r0_broken_arms_void():
    p = params()
    recs = make_records(folds(p, const(0.002)))
    for r in recs:
        if r["arm"] == "C_56" and r["fold"]["index"] == 7:
            r["daily"] = r["daily"][:-1]
    with pytest.raises(v.VerdictRefused):
        v.compute_verdict(recs, p)


def test_missing_counted_fold_and_duplicate_refuse():
    p = params()
    d = folds(p, const(0.002))
    d.pop(12)
    with pytest.raises(v.VerdictRefused):
        v.compute_verdict(make_records(d), p)
    recs = make_records(folds(p, const(0.002)))
    with pytest.raises(v.VerdictRefused):
        v.compute_verdict(recs + [recs[0]], p)


def test_burn_in_folds_are_not_counted():
    p = params()
    d = folds(p, const(0.002))
    d[0] = [-5.0] * 15
    d[3] = [-5.0] * 15
    out = v.compute_verdict(make_records(d), p)  # folds 0 and 3 present but ignored
    assert out["mean_d"] == pytest.approx(0.002) and out["n_paired_days"] == 450
    pall = params(burn_in_folds=0)
    d0 = {i: [0.002] * 15 for i in pall.counted_folds}
    assert v.compute_verdict(make_records(d0), pall)["n_paired_days"] == 34 * 15


def test_days_below_min_stocks_are_left_out():
    p = params()
    recs = make_records(folds(p, const(0.002)))
    for r in recs:
        if r["fold"]["index"] == 5:
            r["daily"][0]["n_stocks"] = 9
    assert v.compute_verdict(recs, p)["n_paired_days"] == 450 - 1


def test_determinism_and_file_order_independence():
    p = params()
    recs = make_records(folds(p, noisy_zero(amp=0.003)))
    a = v.compute_verdict(recs, p)
    shuffled = list(recs)
    random.Random(3).shuffle(shuffled)
    b = v.compute_verdict(shuffled, p)
    assert v.render_json(a, "x") == v.render_json(b, "x")
    assert a["record_sha256"] == b["record_sha256"] == v.compute_verdict(recs, p)["record_sha256"]


def test_sensitivity_labelled_and_primary_block_fixed():
    p = params()
    out = v.compute_verdict(make_records(folds(p, noisy_zero(amp=0.003))), p)
    s = out["sensitivity_NO_WEIGHT"]
    assert [s[k]["block"] for k in ("block_h", "block_3h", "day_iid")] == [5, 15, 1]
    assert out["bootstrap"]["block"] == 10


def test_render_texts_never_say_works():
    p = params()
    for fn in (noisy_zero(amp=0.003), const(0.002)):
        out = v.compute_verdict(make_records(folds(p, fn)), p)
        js = json.loads(v.render_json(out))
        assert js["verdict_code_sha256"] == v.verdict_code_sha256() and js["outcome"] == out["outcome"]
        txt = v.render_plain_english(out)
        assert "works" not in txt.lower() and out["outcome"] in txt


def test_module_has_no_registry_or_io_dependency():
    src = open(v.__file__, encoding="utf-8").read()
    code = src.split('"""', 2)[2]
    assert "import holdout_registry" not in code and "from swing_trade_ml" not in code
    assert "import os" not in code and "open(" not in code and "datetime" not in code
