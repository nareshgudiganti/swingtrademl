"""R4 research run for #219 (5D large cap): pure rules, fingerprints and fits. No database."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from swing_trade_ml.brain.lanes import r4_5d as r4
from swing_trade_ml.ml import model_card
from swing_trade_ml.ml.features import FEATURE_COLUMNS, build_features, on_balance_volume


def _sessions(n: int, start: date = date(2024, 1, 1)) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


# ------------------------------------------------------------------ feature set version


def test_feature_names_are_todays_53_in_order():
    assert list(r4.FEATURE_NAMES) == list(FEATURE_COLUMNS)
    assert len(r4.FEATURE_NAMES) == 53


def test_corrected_obv_slope_is_the_volume_denominator_formula():
    c = model_card.synthetic_candles(0.0)
    got = r4.corrected_obv_slope(c["close"], c["volume"])
    obv = on_balance_volume(c["close"], c["volume"])
    want = obv.diff(10) / c["volume"].rolling(20).mean()
    pd.testing.assert_series_equal(got, want, check_names=False)
    old = obv.diff(10) / obv.rolling(20).mean().abs()
    assert not np.allclose(got.dropna().to_numpy(), old.reindex(got.dropna().index).to_numpy())


def test_research_features_pin_obv_slope_even_if_builder_changes(monkeypatch):
    c = model_card.synthetic_candles(0.0)
    idx, sec = model_card.synthetic_candles(1.1), model_card.synthetic_candles(2.2)
    vix = model_card.synthetic_candles(3.3)[["ts", "close"]]
    breadth = pd.DataFrame({"ts": c["ts"], "breadth_pct_above_sma50": 0.5, "breadth_advance_pct": 0.5})
    base = build_features(c, idx, sec, vix, breadth)
    got = r4.research_features(c, idx, sec, vix, breadth)
    pd.testing.assert_series_equal(got["obv_slope"], base["obv_slope"], check_names=False)

    def broken(*a, **k):
        out = base.copy()
        out["obv_slope"] = 999.0
        return out

    monkeypatch.setattr(r4, "build_features", broken)
    pinned = r4.research_features(c, idx, sec, vix, breadth)
    assert not (pinned["obv_slope"].dropna() == 999.0).any()


def test_feature_set_fingerprint_is_stable_and_names_the_version():
    a, b = r4.feature_set_fingerprint(), r4.feature_set_fingerprint()
    assert a == b
    assert a["version"] == r4.FEATURE_SET_VERSION
    assert len(a["fingerprint_sha256"]) == 64


# ------------------------------------------------------------------ windows and purging


def test_runs_are_consecutive_60_session_blocks_with_leftover():
    days = _sessions(130)
    runs, leftover = r4.make_runs(days, 60)
    assert [len(r) for r in runs] == [60, 60]
    assert runs[1][0] == days[60]
    assert leftover == days[120:]


def test_signal_days_stop_where_session_5_exists():
    s = _sessions(30)
    days = r4.signal_days(s, s[3])
    assert days[0] == s[3] and days[-1] == s[-6]


def test_training_rows_are_purged_and_embargoed():
    s = _sessions(40)
    start = s[30]
    last_ok = r4.last_training_index(s, start)
    assert last_ok == 30 - 5 - 5 - 1
    # the last allowed row's label ends (session +5) strictly before the embargo gap before the test start
    assert last_ok + r4.HORIZON < 30 - r4.EMBARGO


def test_window_m2_starts_after_model_2_last_training_row_plus_purge():
    s = _sessions(60, date(2025, 10, 1))
    last_train = s[7]
    start = r4.window_start_after(s, last_train)
    assert s.index(start) == 7 + r4.HORIZON + r4.EMBARGO + 1


# ------------------------------------------------------------------ labels and momentum


def test_endpoint_label_uses_session_calendar():
    s = _sessions(10)
    closes = dict.fromkeys(s, 100.0)
    closes[s[5]] = 102.0
    assert r4.endpoint_label(closes, s, s[0]) == 1
    closes[s[5]] = 101.99
    assert r4.endpoint_label(closes, s, s[0]) == 0
    del closes[s[5]]
    assert r4.endpoint_label(closes, s, s[0]) is None


def test_momentum_top5_ties_by_symbol_and_needs_21_closes():
    s = _sessions(30)
    bars = {}
    for k, sym in enumerate(["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG"]):
        growth = 1 + 0.01 * (k % 3)
        bars[sym] = {d: (100 * growth**i, 0, 0, 100 * growth**i) for i, d in enumerate(s)}
    bars["HHH"] = dict.fromkeys(s[-10:], (100.0, 0, 0, 100.0))  # too short
    scores, excluded = r4.momentum_scores(bars, s[-1], list(bars))
    assert "HHH" not in scores and excluded["HHH"] == "fewer_than_21_closes"
    picks, short = r4.top_k(scores)
    assert short == 0
    assert picks == ["CCC", "FFF", "BBB", "EEE", "AAA"]  # 2%: C,F; 1%: B,E; 0%: A (A before D, G)


def test_momentum_excludes_unexplained_overnight_gap():
    s = _sessions(25)
    bars = {"AAA": {}, "BBB": {}}
    for i, d in enumerate(s):
        bars["AAA"][d] = (100.0, 0, 0, 100.0)
        o = 150.0 if i == 20 else 100.0 + i
        bars["BBB"][d] = (o, 0, 0, 100.0 + i)
    scores, excluded = r4.momentum_scores(bars, s[-1], ["AAA", "BBB"])
    assert excluded == {"BBB": "overnight_gap_over_20pct"}
    assert set(scores) == {"AAA"}


# ------------------------------------------------------------------ run evaluation


def _outcomes(days, pool, net_of, label_of=lambda d, s: 1):
    return {
        (d, s): r4.Outcome(net_of(d, s), net_of(d, s) - 0.01, label_of(d, s), ()) for d in days for s in pool
    }


def test_evaluate_run_counts_edge_repeats_and_unresolved_on_both_sides():
    s = _sessions(20)
    days = s[:12]
    pool = [f"S{i:02d}" for i in range(12)]
    picks = dict.fromkeys(days, pool[:5])  # same five every day: repeats blocked for 4 days after each count

    def net(d, sym):
        return 0.02 if sym in pool[:5] else 0.0

    out = _outcomes(days, pool, net)
    out[(days[0], "S11")] = r4.Outcome(None, None, None, ("missing_candle",))  # unresolved pool row
    res = r4.evaluate_run(days, s, dict.fromkeys(days, pool), picks, out)
    # counted on sessions 0, 5, 10 only
    assert res["matured_days"] == 3
    assert res["counted_picks"] == 15
    assert res["blocked_repeats"] == 45
    assert res["picks_net"] == pytest.approx([0.02] * 3)
    # day 0 pool: 11 finished rows (S11 dropped), 5 at 2% -> mean 0.1/11
    assert res["pool_net"][0] == pytest.approx(0.10 / 11)
    assert res["trade_edge"][0] == pytest.approx(0.02 - 0.10 / 11)
    assert res["shortfall_day_share"] == 0.0


def test_day_with_fewer_than_10_scored_is_not_matured():
    s = _sessions(15)
    days = s[:1]
    pool = [f"S{i}" for i in range(9)]
    out = _outcomes(days, pool, lambda d, sym: 0.01)
    res = r4.evaluate_run(days, s, {days[0]: pool}, {days[0]: pool[:5]}, out)
    assert res["matured_days"] == 0


def test_run_verdict_inconclusive_when_too_many_counted_picks_unresolved():
    res = {"counted_picks": 100, "unresolved_counted": 21}
    assert r4.unresolved_override(res) == "more than 20% of counted picks UNRESOLVED"
    assert r4.unresolved_override({"counted_picks": 100, "unresolved_counted": 20}) is None


def test_combine_runs_rule():
    pos = [0.01, 0.012, 0.009, 0.011, 0.013] * 12
    neg = [-v for v in pos]
    assert r4.combine_runs(["PASS", "INCONCLUSIVE", "PASS"], pos)["verdict"] == "PASS"
    assert r4.combine_runs(["PASS", "FAIL", "PASS"], pos)["verdict"] == "INCONCLUSIVE"
    assert r4.combine_runs(["FAIL", "FAIL", "PASS"], pos)["verdict"] == "FAIL"
    assert r4.combine_runs(["PASS", "PASS", "PASS"], neg)["verdict"] == "FAIL"
    assert r4.combine_runs(["PASS", "PASS"], pos)["verdict"] == "INCONCLUSIVE"


def test_paired_difference_uses_common_days_only():
    a = dict.fromkeys((date(2024, 1, d) for d in range(1, 21)), 0.01)
    b = dict.fromkeys((date(2024, 1, d) for d in range(2, 22)), 0.0)
    diff = r4.paired_difference(a, b)
    assert len(diff) == 19 and all(v == pytest.approx(0.01) for v in diff)


# ------------------------------------------------------------------ fingerprints and fits


def test_config_fingerprint_changes_with_any_setting():
    base = r4.config_fingerprint("C2")
    assert base == r4.config_fingerprint("C2")
    assert base != r4.config_fingerprint("C3")
    tweaked = {**r4.CANDIDATES["C2"], "params": {**r4.CANDIDATES["C2"]["params"], "n_estimators": 401}}
    assert r4.config_fingerprint("C2", candidate=tweaked) != base


def test_snapshot_sha256_depends_on_values_and_order_of_names():
    f = pd.DataFrame({"ts": pd.to_datetime(["2024-01-01"], utc=True), "close": [1.0]})
    a = r4.snapshot_sha256({"A": f, "B": f})
    assert a == r4.snapshot_sha256({"B": f, "A": f})
    assert a != r4.snapshot_sha256({"A": f, "B": f.assign(close=[1.0000001])})


@pytest.mark.parametrize("cid", ["C2", "C3"])
def test_fit_is_deterministic(cid):
    rng = np.random.default_rng(0)
    x = rng.normal(size=(600, 6))
    y = (x[:, 0] + rng.normal(size=600) > 0.5).astype(int)
    s1, e1 = r4.fit_candidate(cid, x, y)
    s2, e2 = r4.fit_candidate(cid, x, y)
    np.testing.assert_array_equal(r4.predict(s1, e1, x), r4.predict(s2, e2, x))


def test_universe_is_the_frozen_52():
    assert len(r4.UNIVERSE) == 52 and len(set(r4.UNIVERSE)) == 52
    assert list(r4.UNIVERSE) == sorted(r4.UNIVERSE)


# ------------------------------------------------------------------ runner helpers (no database)


def _stock(sessions, n_feat_nan_at=None):
    from swing_trade_ml.brain.lanes import r4_5d_run as run

    feats = pd.DataFrame(1.0, index=sessions, columns=list(r4.FEATURE_NAMES))
    if n_feat_nan_at is not None:
        feats.loc[sessions[n_feat_nan_at], "obv_slope"] = np.nan
    bars = {d: (100.0, 101.0, 99.0, 100.0 + (i % 7)) for i, d in enumerate(sessions)}
    return run.Stock(
        feats, bars, {d: b[3] for d, b in bars.items()}, {d: i + 1 for i, d in enumerate(sessions)}
    )


def test_eligible_needs_220_bars_and_finite_inputs():
    from swing_trade_ml.brain.lanes import r4_5d_run as run

    s = _sessions(260)
    st = _stock(s, n_feat_nan_at=250)
    assert not run.eligible(st, s[218])  # 219 bars
    assert run.eligible(st, s[219])
    assert not run.eligible(st, s[250])


def test_training_frame_never_contains_rows_after_the_purge_index():
    from swing_trade_ml.brain.lanes import r4_5d_run as run

    s = _sessions(300)
    panel = {"AAA": _stock(s), "BBB": _stock(s)}
    tr = run.training_frame(panel, s, 280)
    assert tr["day"].max() == s[280]
    assert tr["day"].min() == s[219]
    assert list(tr[["day", "symbol"]].itertuples(index=False)) == sorted(
        tr[["day", "symbol"]].itertuples(index=False)
    )


def _candles(shift: float, n: int) -> pd.DataFrame:
    c = model_card.synthetic_candles(shift, n)
    c["ts"] = pd.bdate_range("2022-01-03", periods=n, tz="UTC")
    return c


def test_run_end_to_end_on_synthetic_data_is_reproducible(tmp_path, monkeypatch):
    """Exercises the whole runner on fixed synthetic candles: no database, no real data."""
    from lightgbm import LGBMClassifier
    from sklearn.preprocessing import StandardScaler

    from swing_trade_ml.brain.lanes import r4_5d_run as run

    n = 1100
    syms = [f"S{i:02d}" for i in range(12)]
    idx = _candles(9.9, n)
    inp = run.Inputs(
        sessions=sorted({run._day(t) for t in idx["ts"]}),
        candles={s: _candles(0.37 * k, n) for k, s in enumerate(syms)},
        index_df=idx,
        vix_df=_candles(3.3, n)[["ts", "close"]].assign(close=lambda d: 12 + d["close"] / 20),
        breadth_df=pd.DataFrame(
            {"ts": idx["ts"], "breadth_pct_above_sma50": 0.5, "breadth_advance_pct": 0.5}
        ),
        sector_of=dict.fromkeys(syms, "SEC"),
        sector_dfs={"SEC": _candles(2.2, n)},
    )
    m2_names = list(r4.FEATURE_NAMES[:37])
    rng = np.random.default_rng(1)
    xf = rng.normal(size=(300, 37))
    sc = StandardScaler().fit(xf)
    est = LGBMClassifier(n_estimators=5, verbose=-1).fit(sc.transform(xf), (xf[:, 0] > 0).astype(int))
    bundle = {"estimator": est, "scaler": sc, "feature_names": m2_names}
    monkeypatch.setattr(run, "_load_model2", lambda path: bundle)

    a = run.run(inp, tmp_path / "a", tmp_path / "m2.joblib", prereg=run.fingerprints(inp))
    b = run.run(inp, tmp_path / "b", tmp_path / "m2.joblib", prereg=run.fingerprints(inp))
    assert a["metrics_sha256"] == b["metrics_sha256"]
    w = a["windows"]["W_FULL"]
    assert len(w["runs"]) >= 3
    assert set(w["candidates"]) == {"C1", "C2", "C3", "MOM"}
    assert "C2_minus_MOM" in w["comparisons"] and "C3_minus_C1" in w["comparisons"]
    cards = [x["card"] for x in a["artifacts"]]
    assert cards and all(
        c["artifact_sha256"] and c["feature_set"]["version"] == r4.FEATURE_SET_VERSION for c in cards
    )
    assert all(c["label"]["kind"] == "endpoint" for c in cards)
    # every training row of each fitted model ends before its run's first test day (purge + embargo)
    for c in cards:
        start = date.fromisoformat(a["windows"][c["candidate"]["window"]]["runs"][c["candidate"]["run"]][0])
        assert pd.Timestamp(c["data_window"]["train_end"]).date() < start


# ------------------------------------------------------------------ post-review (PR #505) checks


def _tiny_inputs():
    from swing_trade_ml.brain.lanes import r4_5d_run as run

    n = 30
    idx = _candles(9.9, n)
    return run.Inputs(
        sessions=sorted({run._day(t) for t in idx["ts"]}),
        candles={"S00": _candles(0.0, n)},
        index_df=idx,
        vix_df=idx[["ts", "close"]],
        breadth_df=pd.DataFrame(
            {"ts": idx["ts"], "breadth_pct_above_sma50": 0.5, "breadth_advance_pct": 0.5}
        ),
        sector_of={"S00": "SEC"},
        sector_dfs={"SEC": _candles(2.2, n)},
    )


def test_run_itself_refuses_a_mismatched_preregistration_before_any_work(tmp_path, monkeypatch):
    from swing_trade_ml.brain.lanes import r4_5d_run as run

    inp = _tiny_inputs()
    monkeypatch.setattr(run, "build_panel", lambda i: pytest.fail("work started despite a mismatch"))
    pre = {**run.fingerprints(inp), "data_snapshot_sha256": "0" * 64}
    with pytest.raises(run.PreregMismatchError, match="data_snapshot_sha256"):
        run.run(inp, tmp_path / "out", tmp_path / "m2.joblib", prereg=pre)
    assert not (tmp_path / "out").exists()


def test_cli_exits_3_on_mismatch(tmp_path, monkeypatch, capsys):
    import contextlib
    import json

    from swing_trade_ml.brain.lanes import r4_5d_run as run

    inp = _tiny_inputs()
    monkeypatch.setenv("R219_DATABASE_URL", "unused")
    monkeypatch.setattr(run, "readonly_session", lambda url: contextlib.nullcontext())
    monkeypatch.setattr(run, "load_inputs", lambda db: inp)
    pre = tmp_path / "pre.json"
    pre.write_text(json.dumps({**run.fingerprints(inp), "code_sha256": {}}), encoding="utf-8")
    code = run.main(["run", "--out", str(tmp_path / "o"), "--prereg", str(pre), "--model2", "x"])
    assert code == 3
    assert "refusing to run" in capsys.readouterr().err
    assert not (tmp_path / "o").exists()


def test_code_fingerprint_v2_covers_reused_modules_and_leaves_v1_alone():
    from swing_trade_ml.brain.lanes import r4_5d_run as run

    v1 = run.code_sha256()
    assert set(v1) == {"brain/lanes/r4_5d.py", "brain/lanes/r4_5d_run.py"}
    v2 = run.code_fingerprint_v2()
    assert v2 == run.code_fingerprint_v2() and v2["version"] == 2
    for rel in (
        "brain/lanes/h05_rules.py",
        "brain/lanes/h05_verdict.py",
        "ml/model_card.py",
        "ml/features.py",
    ):
        assert rel in v2["files"]
    assert {k: v2["files"][k] for k in v1} == v1
    assert len(v2["combined_sha256"]) == 64


def test_combine_runs_reads_min_runs_passing_and_matches_the_hard_coded_rule():
    import itertools

    from swing_trade_ml.brain.lanes import h05_protocol as proto
    from swing_trade_ml.brain.lanes import h05_verdict as verdict

    assert proto.RUN_VALUES["combined_three_run_rule"]["min_runs_passing"] == 2

    def reference(words, pooled):  # the rule as first written, with a literal 2
        passing, failing = sum(w == "PASS" for w in words), sum(w == "FAIL" for w in words)
        word = verdict._word(verdict._range(pooled))
        if word == "FAIL" or failing >= 2:
            return "FAIL"
        return "PASS" if passing >= 2 and failing == 0 and word == "PASS" else "INCONCLUSIVE"

    pos = [0.01, 0.012, 0.009, 0.011, 0.013] * 12
    series = (pos, [-v for v in pos], [0.01, -0.01] * 30)
    for n in (3, 4):
        for words in itertools.product(("PASS", "FAIL", "INCONCLUSIVE"), repeat=n):
            for pooled in series:
                assert r4.combine_runs(words, pooled)["verdict"] == reference(words, pooled)


def test_stress_series_skips_a_day_whose_stress_trades_are_all_unresolved():
    s = _sessions(15)
    d = s[0]
    pool = [f"S{i:02d}" for i in range(12)]
    out = {(d, sym): r4.Outcome(0.01, None, 1, ()) for sym in pool}
    res = r4.evaluate_run([d], s, {d: pool}, {d: pool[:5]}, out)
    assert res["matured_days"] == 1 and res["picks_net_stress"] == []
