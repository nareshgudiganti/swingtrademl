"""Walk-forward harness (SX5 / SX10 research): synthetic data and stub models ONLY. No real data, no real fit."""

from __future__ import annotations

import json
import stat
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from swing_trade_ml.ml import sector_research as sr
from swing_trade_ml.ml import sector_walkforward as wf

SRC = Path(wf.__file__).resolve().parents[1]
SYMS = [f"S{i:02d}" for i in range(14)]


def make_matrix(horizon=5, n_days=760, seed=0, start="2022-09-01", syms=SYMS) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    days = pd.bdate_range(start, periods=n_days)
    frames = []
    for s in syms:
        n = n_days
        ts = pd.Series(
            [pd.Timestamp(d.date().isoformat() + " 00:00", tz="Asia/Kolkata").tz_convert("UTC") for d in days]
        )
        f = pd.DataFrame(rng.normal(size=(n, len(sr.RESEARCH_COLUMNS))), columns=list(sr.RESEARCH_COLUMNS))
        fr = 0.01 * f["rsi_14"].to_numpy() + rng.normal(0, 0.03, n)
        f["forward_return"] = fr
        f["target"] = (fr >= 0.02).astype(int)
        f["label_end_ts"] = ts.shift(-horizon)
        f["symbol"] = s
        f["ts"] = ts
        f["decision_date"] = pd.DatetimeIndex(days).normalize()
        frames.append(f.iloc[:-horizon])
    m = pd.concat(frames, ignore_index=True).sort_values(["ts", "symbol"]).reset_index(drop=True)
    m.attrs["inputs_source"] = "synthetic"
    return m


def spec_for(candidate="SX5", **kw):
    base = dict(
        candidate=candidate,
        symbols=tuple(SYMS),
        horizon_days=5,
        target_return=0.02,
        stop_return=None,
        label_kind="endpoint",
        data_cutoff=date(2026, 8, 31),
    )
    if candidate == "SX10":
        base.update(horizon_days=10, target_return=0.06, stop_return=0.035, label_kind="barrier")
    base.update(kw)
    return sr.DatasetSpec(**base)


def lstsq_fit(X, y, meta, *, seed):
    """A deterministic, data-dependent STUB (least squares), not a model recipe."""
    Xn = np.c_[np.ones(len(X)), X.to_numpy("float64")]
    coef, *_ = np.linalg.lstsq(Xn, y.to_numpy("float64"), rcond=None)
    return lambda Xt: np.c_[np.ones(len(Xt)), Xt.to_numpy("float64")] @ coef


FOLDS = wf.make_folds(date(2024, 6, 1), date(2024, 12, 31))


def run(matrix, tmp_path, *, fit=lstsq_fit, sub="a", folds=FOLDS, spec=None, **kw):
    kw.setdefault("synthetic", True)
    kw.setdefault("code_version", "deadbeef")
    return wf.run_walkforward(
        spec or spec_for(),
        matrix,
        fit_fn=fit,
        folds=folds,
        out_root=tmp_path / sub,
        marker_dir=tmp_path / (sub + "_markers"),
        **kw,
    )


@pytest.fixture(scope="module")
def matrix():
    return make_matrix()


# ------------------------------------------------------------------------------------------ folds and purge
def test_folds_equal_the_selection_lab_windows_and_the_draft_counts():
    from swing_trade_ml.brain import selection_lab as lab

    mine = wf.make_folds(wf.DEV_FIRST_START, wf.DEV_LAST_END)
    theirs = lab.make_folds(wf.DEV_FIRST_START, wf.DEV_LAST_END)
    assert [(f.cutoff, f.test_start, f.test_end) for f in mine] == [
        (f.cutoff, f.start, f.end) for f in theirs
    ]
    assert len(mine) == 34  # the drafts' "34 development folds"
    allf = wf.default_folds(include_holdout=True)
    assert allf[-1].kind == "holdout" and (allf[-1].test_start, allf[-1].test_end) == (
        wf.HOLDOUT_START,
        wf.HOLDOUT_END,
    )


def test_purge_property_over_random_fold_configurations():
    rng = np.random.default_rng(123)
    for trial in range(60):
        horizon = int(rng.choice([5, 10, 15]))
        m = make_matrix(horizon=horizon, n_days=int(rng.integers(150, 320)), seed=trial, syms=SYMS[:4])
        dmin, dmax = m["decision_date"].min(), m["decision_date"].max()
        span = (dmax - dmin).days
        ts = dmin + pd.Timedelta(days=int(rng.integers(30, max(31, span - 20))))
        te = ts + pd.Timedelta(days=int(rng.integers(6, 40)))
        emb = int(rng.choice([0, horizon, horizon + 3]))
        fold = wf.Fold(0, "dev", (ts - pd.Timedelta(days=1)).date(), ts.date(), te.date())
        sp = wf.split_for_fold(m, fold, emb)
        le = wf.label_end_dates(m)
        dd = m["decision_date"]
        tr, tst = m.loc[sp.train], m.loc[sp.test]
        # no overlap of any training label window with the test window, and no shared rows
        assert (le[sp.train] < ts).all()
        assert not (set(sp.train) & set(sp.test))
        assert (tr["decision_date"] < ts).all()
        assert ((tst["decision_date"] >= ts) & (tst["decision_date"] <= te)).all()
        # brute force: window [decision, label_end] never intersects [ts, te] for training rows
        for i in sp.train[:: max(1, len(sp.train) // 200)]:
            assert not (dd[i] <= te and le[i] >= ts)
        # embargo: the last `emb` sessions before the test start hold no training decision day
        cal = np.sort(dd[dd < ts].unique())
        if emb and len(cal) > emb:
            assert (tr["decision_date"] <= cal[-emb - 1]).all()
        # maximality: nothing eligible is thrown away
        ok = (dd < ts) & (le < ts)
        if emb and len(cal) > emb:
            ok &= dd <= cal[-emb - 1]
        elif emb:
            ok &= False
        assert set(sp.train) == set(m.index[ok])
        assert sp.n_purged_overlap == int(((dd < ts) & (le >= ts)).sum())


def test_training_never_sees_a_label_window_reaching_the_test_window(matrix):
    for f in FOLDS:
        sp = wf.split_for_fold(matrix, f, 5)
        assert len(sp.train) and len(sp.test)
        assert matrix.loc[sp.train, "decision_date"].max() < pd.Timestamp(f.test_start) - pd.Timedelta(days=5)


# ----------------------------------------------------------------------------------- arms, rows and records
def test_arm_definitions():
    arms = wf.build_arms()
    assert [len(arms[a]) for a in wf.ARM_IDS] == [53, 37, 56]
    assert set(arms["R_37"]) <= set(arms["A_53"]) and arms["C_56"][:53] == arms["A_53"]
    assert arms["C_56"][53:] == sr.SECTOR_COLUMNS
    assert not set(arms["R_37"]) & set(sr.SECTOR_COLUMNS)
    with pytest.raises(wf.HarnessRefused):
        wf.build_arms(["not_a_feature"])


def test_three_arms_receive_identical_rows_and_folds_and_only_their_own_columns(matrix, tmp_path):
    seen: dict[tuple, dict] = {}

    def spy(X, y, meta, *, seed):
        seen.setdefault(tuple(X.columns), {"idx": [], "y": []})
        seen[tuple(X.columns)]["idx"].append(tuple(X.index))
        seen[tuple(X.columns)]["y"].append(y.to_numpy().tobytes())
        return lambda Xt: np.arange(len(Xt), dtype="float64")

    res = run(matrix, tmp_path, fit=spy)
    arms = wf.build_arms()
    assert set(seen) == {tuple(arms[a]) for a in wf.ARM_IDS}  # each arm saw exactly its own columns
    idx = [v["idx"] for v in seen.values()]
    ys = [v["y"] for v in seen.values()]
    assert idx[0] == idx[1] == idx[2] and ys[0] == ys[1] == ys[2]  # same training rows and labels per fold
    recs = res.records
    assert len(recs) == len(FOLDS) * 3
    for f in FOLDS:
        r = [x for x in recs if x["fold"]["index"] == f.index]
        assert {x["arm"] for x in r} == set(wf.ARM_IDS)
        for k in (
            "train_rows_sha256",
            "test_rows_sha256",
            "n_train",
            "n_test",
            "rows_sha256",
            "fold_definition_sha256",
        ):
            assert len({json.dumps(x[k]) for x in r}) == 1
        assert len({json.dumps([(d["date"], d["n_stocks"]) for d in x["daily"]]) for x in r}) == 1
    wf.assert_identical_across_arms(recs)


def test_plan_folds_matches_the_run_records_and_every_arm_has_the_same_rows(matrix, tmp_path):
    plan = wf.plan_folds(matrix, FOLDS, 5)
    res = run(matrix, tmp_path)
    for p in plan:
        assert len({(a["rows_train"], a["rows_test"]) for a in p["arms"].values()}) == 1
        assert [a["columns"] for a in p["arms"].values()] == [53, 37, 56]
        for r in (x for x in res.records if x["fold"]["index"] == p["index"]):
            assert (r["n_train"], r["n_test"]) == (p["n_train"], p["n_test"])


def test_assert_identical_catches_a_difference(matrix, tmp_path):
    recs = [dict(r) for r in run(matrix, tmp_path).records]
    recs[1]["train_rows_sha256"] = "0" * 64
    with pytest.raises(wf.ArmMismatch):
        wf.assert_identical_across_arms(recs)


def test_records_carry_every_hash_and_are_immutable(matrix, tmp_path):
    res = run(matrix, tmp_path, code_version="abc1234")
    sp = spec_for()
    for r in res.records:
        for k in (
            "dataset_sha256",
            "rows_sha256",
            "fold_definition_sha256",
            "feature_list_sha256",
            "config_sha256",
            "harness_config_sha256",
            "record_sha256",
        ):
            assert len(r[k]) == 64
        assert r["code_version"] == "abc1234" and r["config_sha256"] == sp.config_sha256()
        assert r["dataset_sha256"] == sr.matrix_sha256(matrix)
    files = sorted(res.run_dir.glob("dev_*.json"))
    assert len(files) == len(res.records)
    for f in files:
        assert not f.stat().st_mode & stat.S_IWUSR  # read-only
        with pytest.raises(FileExistsError):
            wf.write_immutable_json(f, {"x": 1})
    with pytest.raises(wf.HarnessRefused, match="immutable"):
        run(matrix, tmp_path, code_version="abc1234")  # same run id, same folder: never overwritten


def test_repeat_runs_are_identical(matrix, tmp_path):
    a, b = run(matrix, tmp_path, sub="a"), run(matrix, tmp_path, sub="b")
    assert a.run_id == b.run_id
    assert [r["record_sha256"] for r in a.records] == [r["record_sha256"] for r in b.records]
    assert [r["predictions_sha256"] for r in a.records] == [r["predictions_sha256"] for r in b.records]
    assert a.manifest == b.manifest
    c = run(matrix, tmp_path, sub="c", code_version="other")
    assert c.run_id != a.run_id  # the code version is part of the identity


def test_hashes_are_stable_literals():
    assert wf.folds_sha256(wf.default_folds(True), 5, 5) == wf.folds_sha256(wf.default_folds(True), 5, 5)
    # pinned: a change to the fold rule or windows must be a deliberate, reviewed edit of this literal
    assert (
        wf.folds_sha256(wf.default_folds(True), 5, 5)
        == "9d16263a0f277705518b1e8cff5b44a8273b15dffa5416cc88ac945529948f91"
    )
    m = make_matrix(n_days=30, syms=SYMS[:2])
    assert wf.rows_sha256(m) == wf.rows_sha256(m.sample(frac=1, random_state=1))  # order does not matter
    assert wf.rows_sha256(m) != wf.rows_sha256(m.iloc[1:])


# ----------------------------------------------------------------------------------------------- refusals
def test_refuses_without_approval_and_calls_no_fit(matrix, tmp_path):
    calls = []

    def fit(X, y, meta, *, seed):
        calls.append(1)
        return lambda Xt: np.zeros(len(Xt))

    with pytest.raises(sr.ResearchApprovalRequired):
        wf.run_walkforward(
            spec_for(),
            matrix,
            fit_fn=fit,
            code_version="x",
            folds=FOLDS,
            out_root=tmp_path / "o",
            marker_dir=tmp_path / "m",
        )
    assert calls == [] and not (tmp_path / "o").exists()


def test_synthetic_flag_cannot_launder_database_data(matrix, tmp_path):
    m = matrix.copy()
    m.attrs["inputs_source"] = "database"
    with pytest.raises(wf.HarnessRefused, match="database"):
        run(m, tmp_path)


def test_approval_file_must_match_exact_configuration_then_run_is_allowed(matrix, tmp_path):
    sp = spec_for()
    tok = {
        "protocol_id": "test-only",
        "approved_by": "unit test",
        "candidate": "SX5",
        "config_sha256": sp.config_sha256(),
    }
    good = tmp_path / "ok.json"
    good.write_text(json.dumps(tok))
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({**tok, "config_sha256": "0" * 64}))
    common = dict(fit_fn=lstsq_fit, code_version="x", folds=FOLDS, marker_dir=tmp_path / "m")
    with pytest.raises(sr.ResearchApprovalRequired):
        wf.run_walkforward(sp, matrix, out_root=tmp_path / "o1", approval_path=bad, **common)
    with pytest.raises(wf.HarnessRefused, match="seed"):
        wf.run_walkforward(sp, matrix, out_root=tmp_path / "o2", approval_path=good, seed=1, **common)
    res = wf.run_walkforward(sp, matrix, out_root=tmp_path / "o3", approval_path=good, **common)
    assert res.records and "approved by unit test" in res.records[0]["approval"]


def test_code_version_and_matrix_are_checked(matrix, tmp_path):
    with pytest.raises(wf.HarnessRefused, match="code_version"):
        run(matrix, tmp_path, code_version=" ")
    with pytest.raises(wf.HarnessRefused, match="NaN|56 inputs"):
        bad = matrix.copy()
        bad.loc[3, "rsi_14"] = np.nan
        run(bad, tmp_path)
    with pytest.raises(wf.HarnessRefused, match="duplicate"):
        run(pd.concat([matrix, matrix.iloc[:2]], ignore_index=True), tmp_path)


def test_refuses_production_model_locations(matrix, tmp_path):
    with pytest.raises(sr.ResearchPathRefused):
        run(matrix, tmp_path, sub="ml_models")


# ------------------------------------------------------------------------------------------------ holdout
HOLD = [
    *wf.make_folds(date(2024, 6, 1), date(2024, 8, 31)),
    wf.Fold(99, "holdout", date(2024, 9, 1), date(2024, 9, 2), date(2024, 12, 20)),
]


def test_holdout_is_scored_once_even_after_a_crash(matrix, tmp_path):
    res = run(matrix, tmp_path, folds=HOLD, sub="h1")
    assert any(r["fold"]["kind"] == "holdout" and r["status"] == "ok" for r in res.records)
    marker = tmp_path / "h1_markers" / "SX5.holdout_used.json"
    assert marker.is_file()
    with pytest.raises(wf.HoldoutAlreadyUsed):
        run(matrix, tmp_path, folds=HOLD, sub="h1", code_version="again")
    # the development folds alone are still allowed
    assert run(matrix, tmp_path, folds=FOLDS, sub="h1", code_version="dev-only").records

    h2 = tmp_path / "h2_markers" / "SX5.holdout_used.json"

    def crash_on_holdout(X, y, meta, *, seed):
        if h2.exists():
            raise RuntimeError("boom")
        return lambda Xt: np.arange(len(Xt), dtype="float64")

    with pytest.raises(RuntimeError):
        run(matrix, tmp_path, folds=HOLD, sub="h2", fit=crash_on_holdout)
    assert (tmp_path / "h2_markers" / "SX5.holdout_used.json").is_file()  # a crash does not reset it
    with pytest.raises(wf.HoldoutAlreadyUsed):
        run(matrix, tmp_path, folds=HOLD, sub="h2")


def test_holdout_marker_is_written_before_the_first_holdout_fit(matrix, tmp_path):
    marker = tmp_path / "h3_markers" / "SX5.holdout_used.json"
    state = []

    def fit(X, y, meta, *, seed):
        state.append(marker.exists())
        return lambda Xt: np.zeros(len(Xt)) + np.arange(len(Xt))

    run(matrix, tmp_path, folds=HOLD, sub="h3", fit=fit)
    n_dev = len(HOLD) - 1
    assert state[: 3 * n_dev] == [False] * (3 * n_dev) and all(state[3 * n_dev :])


# ------------------------------------------------------------------------------------------------ metrics
def _scored(n_days=3, n=12, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for d in pd.bdate_range("2024-01-01", periods=n_days):
        for i in range(n):
            fr = rng.normal(0, 0.02)
            rows.append(
                {
                    "symbol": f"S{i:02d}",
                    "decision_date": d,
                    "forward_return": fr,
                    "target": int(fr >= 0.02),
                    "score": fr,
                }
            )
    return pd.DataFrame(rows)


def test_perfect_scores_give_ic_one_and_top5_beats_every_stock_and_random():
    agg, daily = wf.evaluate_fold(_scored())
    assert agg["n_days"] == 3 and agg["n_ideas"] == 15
    assert all(d["ic"] == pytest.approx(1.0) for d in daily)
    assert agg["mean_excess_vs_all"] > 0 and agg["mean_excess_vs_random"] > 0
    assert agg["top_hit_rate"] >= agg["all_hit_rate"]
    assert agg["net_after_costs"].startswith("not permitted") and agg["mean_net_top"] is None


def test_metrics_small_hand_example():
    d = pd.Timestamp("2024-01-02")
    fr = np.arange(10, dtype=float) / 100
    df = pd.DataFrame(
        {
            "symbol": [f"X{i}" for i in range(10)],
            "decision_date": d,
            "forward_return": fr,
            "target": (fr >= 0.05).astype(int),
            "score": fr[::-1],
        }
    )  # worst possible ranking
    agg, daily = wf.evaluate_fold(df, draws=50)
    assert daily[0]["ic"] == pytest.approx(-1.0)
    assert daily[0]["top_return"] == pytest.approx(np.mean([0, 1, 2, 3, 4]) / 100)
    assert daily[0]["all_return"] == pytest.approx(0.045)
    assert daily[0]["top_hit"] == 0.0 and daily[0]["all_hit"] == 0.5
    assert agg["mean_excess_vs_all"] == pytest.approx(0.02 - 0.045)


def test_days_with_few_stocks_are_left_out_and_ties_are_deterministic():
    df = _scored(n=9)
    assert wf.evaluate_fold(df)[0]["n_days"] == 0
    tied = _scored(n=12).assign(score=1.0)
    a, b = wf.evaluate_fold(tied)[1], wf.evaluate_fold(tied.sample(frac=1, random_state=3))[1]
    assert (
        [d["top_symbols"] for d in a]
        == [d["top_symbols"] for d in b]
        == [["S00", "S01", "S02", "S03", "S04"]] * 3
    )
    assert a[0]["ic"] is None  # constant score: no correlation, not a fake 0


def test_random5_benchmark_is_identical_for_every_arm(matrix, tmp_path):
    res = run(matrix, tmp_path)
    for f in FOLDS:
        r = [x for x in res.records if x["fold"]["index"] == f.index and x["status"] == "ok"]
        if r:
            assert len({json.dumps([d["random_return"] for d in x["daily"]]) for x in r}) == 1
            assert len({json.dumps([d["all_return"] for d in x["daily"]]) for x in r}) == 1


def test_net_after_costs_only_through_the_injected_hook(matrix, tmp_path):
    res = run(matrix, tmp_path, sub="n1")
    assert all(r["metrics"]["mean_net_top"] is None for r in res.records if r["status"] == "ok")
    res2 = run(matrix, tmp_path, sub="n2", net_fn=lambda s, d: -0.001 if s < "S05" else 0.002)
    ok = [r for r in res2.records if r["status"] == "ok"]
    assert ok and all(
        r["metrics"]["mean_net_top"] is not None and r["metrics"]["net_after_costs"] == "reported" for r in ok
    )


def test_a_fold_without_enough_training_rows_is_recorded_not_fitted(matrix, tmp_path):
    early = [wf.Fold(0, "dev", date(2022, 9, 7), date(2022, 9, 8), date(2022, 10, 20))]
    calls = []
    res = run(matrix, tmp_path, folds=early, fit=lambda X, y, m, seed: calls.append(1))
    assert calls == [] and {r["status"] for r in res.records} == {"skipped_not_enough_training_rows"}


# ---------------------------------------------------------------------------------- no future data leaks
def test_changing_data_after_a_fold_cut_changes_no_earlier_record(matrix, tmp_path):
    cut = pd.Timestamp("2024-09-15")
    base = run(matrix, tmp_path, sub="p1")
    m2 = matrix.copy()
    fut = m2["decision_date"] > cut
    rng = np.random.default_rng(99)
    cols = list(sr.RESEARCH_COLUMNS)
    m2.loc[fut, cols] = rng.normal(size=(int(fut.sum()), len(cols)))
    m2.loc[fut, "forward_return"] = rng.normal(0, 0.05, int(fut.sum()))
    m2.loc[fut, "target"] = rng.integers(0, 2, int(fut.sum()))
    other = run(m2, tmp_path, sub="p2", folds=FOLDS)
    safe = [f for f in FOLDS if pd.Timestamp(f.test_end) <= cut]
    assert safe and len(safe) < len(FOLDS)
    for f in safe:
        a = [r for r in base.records if r["fold"]["index"] == f.index]
        b = [r for r in other.records if r["fold"]["index"] == f.index]
        # records differ only in the hashes of the whole dataset; predictions and metrics are identical
        for x, y in zip(a, b, strict=True):
            assert x["predictions_sha256"] == y["predictions_sha256"] and x["metrics"] == y["metrics"]
            assert x["train_rows_sha256"] == y["train_rows_sha256"]
    # and a fold after the cut does change (the mutation was real)
    late = [f for f in FOLDS if pd.Timestamp(f.test_start) > cut][0]
    assert any(
        x["predictions_sha256"] != y["predictions_sha256"]
        for x, y in zip(
            [r for r in base.records if r["fold"]["index"] == late.index],
            [r for r in other.records if r["fold"]["index"] == late.index],
            strict=True,
        )
    )


def test_matrix_assembly_ignores_data_after_the_decision_day():
    """Mutate every input (stock, indices, VIX, breadth) after day T: rows decided on or before T keep their 56
    inputs, and rows whose label window ended on or before T keep their label and their eligibility."""
    from swing_trade_ml.ml import sector_features as sf
    from test_sector_research import STOCKS, _ohlcv  # the same synthetic builder as the research tests

    rng = np.random.default_rng(7)
    N = 520

    def build(mutate_after=None):
        r = np.random.default_rng(42)
        frames = {u: _ohlcv(r) for u in sf.DEFAULT_RANK_UNIVERSE}
        raw = {s: _ohlcv(r, 50.0 + 30 * i) for i, s in enumerate(STOCKS)}
        nifty, vix = _ohlcv(r), _ohlcv(r, 15.0)
        breadth = pd.DataFrame(
            {
                "ts": nifty["ts"],
                "breadth_pct_above_sma50": r.uniform(0.2, 0.8, N),
                "breadth_advance_pct": r.uniform(0.2, 0.8, N),
            }
        )
        if mutate_after is not None:
            rr = np.random.default_rng(1)

            def wreck(df):
                df = df.copy()
                late = df["ts"] > mutate_after
                for c in ("open", "high", "low", "close", "volume"):
                    df.loc[late, c] = df.loc[late, c].to_numpy() * rr.uniform(0.5, 2.0, int(late.sum()))
                df.loc[late, "high"] = df.loc[late, ["open", "high", "close"]].max(axis=1)
                df.loc[late, "low"] = df.loc[late, ["open", "low", "close"]].min(axis=1)
                return df

            frames = {k: wreck(v) for k, v in frames.items()}
            raw = {k: wreck(v) for k, v in raw.items()}
            nifty, vix = wreck(nifty), wreck(vix)
            late = breadth["ts"] > mutate_after
            breadth.loc[late, ["breadth_pct_above_sma50", "breadth_advance_pct"]] = rr.uniform(
                0, 1, (int(late.sum()), 2)
            )
        return sr.ResearchInputs(raw=raw, index_df=nifty, index_frames=frames, vix_df=vix, breadth_df=breadth)

    spec = sr.DatasetSpec(
        candidate="SX5",
        symbols=tuple(STOCKS),
        horizon_days=5,
        target_return=0.02,
        stop_return=None,
        label_kind="endpoint",
        data_cutoff=date(2026, 12, 31),
    )
    base = sr.assemble_training_matrix(spec, build())
    T = base["ts"].iloc[int(len(base) * 0.6)]
    mut = sr.assemble_training_matrix(spec, build(mutate_after=T))
    assert (base["ts"] <= T).sum() > 100
    for name, keep in (
        ("features", lambda m: m["ts"] <= T),
        ("labels and eligibility", lambda m: pd.to_datetime(m["label_end_ts"], utc=True) <= T),
    ):
        a, b = base[keep(base)].reset_index(drop=True), mut[keep(mut)].reset_index(drop=True)
        assert len(a) == len(b) and len(a) > 50, name
        assert (a["symbol"] == b["symbol"]).all() and (a["decision_date"] == b["decision_date"]).all(), name
        cols = (
            list(sr.RESEARCH_COLUMNS)
            if name == "features"
            else ["target", "forward_return", *sr.RESEARCH_COLUMNS]
        )
        pd.testing.assert_frame_equal(a[cols], b[cols], check_exact=True)


# ---------------------------------------------------------------- pinned LightGBM recipe, random data only
def test_lightgbm_with_the_drafts_pinned_recipe_is_deterministic_on_random_data(tmp_path):
    lgb = pytest.importorskip("lightgbm")
    from sklearn.preprocessing import StandardScaler

    def fit(X, y, meta, *, seed):
        assert seed == 42
        sc = StandardScaler().fit(X.to_numpy("float64"))  # training rows only
        est = lgb.LGBMClassifier(
            n_estimators=400,
            learning_rate=0.05,
            max_depth=6,
            num_leaves=31,
            subsample=0.8,
            colsample_bytree=0.8,
            min_child_samples=50,
            reg_alpha=0.1,
            reg_lambda=0.1,
            class_weight="balanced",
            random_state=seed,
            n_jobs=1,
            verbose=-1,
        )
        est.fit(sc.transform(X.to_numpy("float64")), y.to_numpy())
        return lambda Xt: est.predict_proba(sc.transform(Xt.to_numpy("float64")))[:, 1]

    m = make_matrix(n_days=330, syms=SYMS[:8], seed=5)
    folds = wf.make_folds(date(2023, 9, 1), date(2023, 10, 31))
    a = wf.run_walkforward(
        spec_for(),
        m,
        fit_fn=fit,
        code_version="x",
        folds=folds,
        synthetic=True,
        seed=42,
        out_root=tmp_path / "a",
        marker_dir=tmp_path / "ma",
    )
    b = wf.run_walkforward(
        spec_for(),
        m,
        fit_fn=fit,
        code_version="x",
        folds=folds,
        synthetic=True,
        seed=42,
        out_root=tmp_path / "b",
        marker_dir=tmp_path / "mb",
    )
    pa = [r["predictions_sha256"] for r in a.records]
    assert pa == [r["predictions_sha256"] for r in b.records] and all(pa)
    assert [r["record_sha256"] for r in a.records] == [r["record_sha256"] for r in b.records]
    # the arms differ in inputs, so their predictions differ; their rows and folds do not
    assert len({r["predictions_sha256"] for r in a.records if r["fold"]["index"] == 0}) > 1
    wf.assert_identical_across_arms(a.records)


# --------------------------------------------------------------------------------------------- isolation
def test_nothing_in_the_app_imports_the_harness_and_it_avoids_the_database_and_production():
    for p in SRC.rglob("*.py"):
        if p.name in ("sector_walkforward.py",):
            continue
        txt = p.read_text(encoding="utf-8")
        assert "sector_walkforward" not in txt, p
    own = (SRC / "ml" / "sector_walkforward.py").read_text(encoding="utf-8")
    for bad in (
        "ml.predict",
        "from swing_trade_ml.db",
        "swing_trade_ml.brain",
        "h05",
        "workers",
        "strategies",
        "brokers",
        "ml.registry",
        "ml_models",
        "SessionLocal",
        "sqlalchemy",
        "psycopg",
    ):
        code = [ln for ln in own.splitlines() if not ln.lstrip().startswith(("#", '"""')) and "import" in ln]
        assert not any(bad in ln for ln in code), bad
