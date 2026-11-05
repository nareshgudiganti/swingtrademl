"""Prediction Reliability: pure measures, health states, no pooling, open outcomes, and the trial seal."""

from __future__ import annotations

import inspect
import json
from datetime import date, timedelta

import pytest

from swing_trade_ml.brain import prediction_reliability as pr
from swing_trade_ml.brain.prediction_reliability import Rec
from swing_trade_ml.services import trial_seal

OLD = date(2026, 1, 5)  # before the seal
GATE = {"min_days": 15, "min_completed": 30}


def days(n, start=OLD):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def make(n_days, hit_top, hit_rest, ret_top, ret_rest, start=OLD, per_day=8, score=None):
    """Each day: ranks 1..per_day; top 5 use the *_top figures, ranks 6+ the *_rest figures."""
    recs = []
    for i, d in enumerate(days(n_days, start)):
        for r in range(1, per_day + 1):
            top = r <= 5
            h = hit_top(i, r) if top else hit_rest(i, r)
            recs.append(
                Rec(
                    d,
                    f"S{r}",
                    score if score is not None else 0.9 - r * 0.05,
                    r,
                    h,
                    ret_top if top else ret_rest,
                )
            )
    return recs


def test_wilson_known_values():
    lo, hi = pr.wilson(50, 100)
    assert lo == pytest.approx(0.4038, abs=1e-3) and hi == pytest.approx(0.5962, abs=1e-3)
    assert pr.wilson(0, 0) is None
    lo, hi = pr.wilson(0, 10)
    assert lo == 0.0 and hi == pytest.approx(0.2775, abs=1e-3)


def test_brier():
    assert pr.brier([1.0, 0.0], [1, 0]) == 0.0
    assert pr.brier([0.5, 0.5], [1, 0]) == pytest.approx(0.25)
    assert pr.brier([], []) is None


def test_effective_blocks_overlap():
    ds = days(20)
    assert pr.effective_blocks(ds, 5) < len(ds)
    assert pr.effective_blocks(ds, 15) < pr.effective_blocks(ds, 5)
    assert pr.effective_blocks([], 5) == 0


def test_open_outcomes_never_counted():
    recs = [
        Rec(OLD, "A", 0.8, 1, 1, 0.05),
        Rec(OLD, "B", 0.7, 2, None, None),
        Rec(OLD, "C", 0.6, 3, 0, -0.03),
    ]
    m = pr.measure(recs, 5)
    assert m["picked"] == 3 and m["completed"] == 2 and m["open"] == 1
    assert m["hit_rate"] == 0.5
    assert m["avg_net"] == pytest.approx(0.01)


def test_insufficient_below_gates_even_when_great():
    recs = make(5, lambda i, r: 1, lambda i, r: 0, 0.05, -0.01)
    rep = pr.report_series({"horizon": 15}, recs, "brain", has_baseline_pool=True)
    assert rep["health"]["top5"]["state"] == pr.INSUFFICIENT


def test_healthy_and_fail_and_watch_transitions():
    # strong edge, many days: top 5 always hit and win, the rest lose
    good = make(60, lambda i, r: 1, lambda i, r: 0, 0.05, -0.02)
    rep = pr.report_series({"horizon": 5}, good, "brain", has_baseline_pool=True)
    assert rep["health"]["top5"]["state"] == pr.HEALTHY
    # top 5 never hit and lose money while the rest win: FAIL
    bad = make(60, lambda i, r: 0, lambda i, r: 1, -0.04, 0.03)
    assert (
        pr.report_series({"horizon": 5}, bad, "brain", has_baseline_pool=True)["health"]["top5"]["state"]
        == pr.FAIL
    )
    # same as the rest: no clear edge -> WATCH
    same = make(60, lambda i, r: i % 2, lambda i, r: i % 2, 0.01, 0.01, score=0.5)
    assert (
        pr.report_series({"horizon": 5}, same, "brain", has_baseline_pool=True)["health"]["top5"]["state"]
        == pr.WATCH
    )


def test_health_never_healthy_when_sealed_flag():
    m = pr.measure(make(60, lambda i, r: 1, lambda i, r: 0, 0.05, -0.02), 5)
    m["avg_excess"] = 0.1
    assert pr.health(m, GATE, sealed=True)["state"] == pr.INSUFFICIENT


def test_drift_not_measured_is_honest():
    assert pr.psi_flag(None, None)["text"].startswith("drift: not measured")
    assert pr.psi_flag(None, None)["measured"] is False


def test_horizons_and_models_never_pooled():
    a = make(40, lambda i, r: 1, lambda i, r: 0, 0.05, -0.02)
    b = make(40, lambda i, r: 0, lambda i, r: 1, -0.05, 0.02)
    rep = pr.build_report(
        [
            ({"source": "lane", "horizon": 10, "model": "v1", "group": "10d-large"}, a, "lane", False),
            ({"source": "lane", "horizon": 15, "model": "v1", "group": "15d-large"}, b, "lane", False),
        ]
    )
    assert len(rep["series"]) == 2
    s10, s15 = rep["series"]
    assert s10["sets"]["top5"]["hit_rate"] == 1.0 and s15["sets"]["top5"]["hit_rate"] == 0.0
    assert "total" not in json.dumps(rep).lower()
    assert s10["sets"]["ranks_6_20"] == pr.NOT_RECORDED


def test_seal_leak_counts_only(monkeypatch):
    monkeypatch.setattr(trial_seal, "SEALED", True)
    sealed_start = trial_seal.SEALED_FROM + timedelta(days=1)
    sealed = [
        Rec(d, f"S{r}", 0.9 - r * 0.05, r, 1, 0.0777123 if r <= 5 else -0.0233456)
        for d in days(40, sealed_start)
        for r in range(1, 9)
    ]
    # all sealed: counts only, INSUFFICIENT
    rep = pr.build_report(
        [({"source": "brain", "horizon": 15, "model": "m", "group": "all"}, sealed, "brain", True)]
    )
    blob = json.dumps(rep, default=str) + pr.plain_report(rep)
    for leak in ("0.0777", "7.77", "0.0233", "2.33", "7.8%"):
        assert leak not in blob
    s = rep["series"][0]
    assert s["health"]["top5"]["state"] == pr.INSUFFICIENT
    assert s["sealed_counts"]["top5"]["picked"] == 200 and s["sealed_counts"]["top5"]["avg_net"] is None
    # mixed: open-day figures are computed from open days only, so subtracting from them reveals nothing
    old = make(60, lambda i, r: 1, lambda i, r: 0, 0.05, -0.02)
    rep2 = pr.build_report(
        [({"source": "brain", "horizon": 15, "model": "m", "group": "all"}, old + sealed, "brain", True)]
    )
    only_old = pr.build_report(
        [({"source": "brain", "horizon": 15, "model": "m", "group": "all"}, old, "brain", True)]
    )
    assert rep2["series"][0]["sets"] == only_old["series"][0]["sets"]
    assert "0.0777" not in json.dumps(rep2, default=str)


def test_write_report_refuses_overwrite(tmp_path):
    p = pr.write_report("a", tmp_path, OLD)
    assert p.read_text() == "a"
    with pytest.raises(FileExistsError):
        pr.write_report("b", tmp_path, OLD)


# ----------------------------------------------------------------------------- owner rules, 2026-11-05

SERIES = {"source": "brain", "horizon": 15, "model": "m", "group": "all"}


def _market_recs(n_days=60, edge=0.02, hit_top=1, score=None, start=OLD):
    """A strong common market swing each day (+/-4%); the top 5 beat the rest by `edge` every day."""
    recs = []
    for i, d in enumerate(days(n_days, start)):
        m = 0.04 if i % 2 == 0 else -0.04
        for r in range(1, 9):
            top = r <= 5
            recs.append(
                Rec(
                    d,
                    f"S{r}",
                    score if score is not None else 0.9 - r * 0.05,
                    r,
                    hit_top if top else 0,
                    m + (edge if top else 0.0),
                )
            )
    return recs


def test_paired_block_comparison_removes_the_common_market_swing():
    recs = _market_recs()
    top = [r for r in recs if r.rank <= 5]
    # per-day paired gap is the same every day although each side swings by +/-4%
    gaps = pr.paired_days(top, recs, "ret")
    assert len(gaps) == 60
    assert all(g == pytest.approx(0.02 * 3 / 8) for g in gaps)
    m = pr.measure(top, 15, recs)
    assert m["excess_days"] == 60 and m["avg_excess"] == pytest.approx(0.0075)
    assert m["excess_boot_low"] == pytest.approx(0.0075) and m["hit_boot_low"] > 0
    # it is the existing block bootstrap (BLOCK_DAYS = 15): too few days -> no bound at all
    keep = set(days(20))
    short = pr.measure([r for r in top if r.day in keep], 15, [r for r in recs if r.day in keep])
    assert short["excess_boot_low"] is None


def test_pairing_skips_a_day_missing_on_either_side_never_zero():
    recs = _market_recs(40)
    top = [r for r in recs if r.rank <= 5]
    gone = days(40)[0]
    base = [r for r in recs if r.day != gone]  # baseline has no record for the first day
    assert len(pr.paired_days(top, base, "ret")) == 39
    open_top = [r if r.day != gone else Rec(r.day, r.symbol, r.score, r.rank, None, None) for r in top]
    assert len(pr.paired_days(open_top, recs, "ret")) == 39


def test_brier_never_gates_an_uncalibrated_series():
    # stated chance 5% but they always hit: a terrible Brier score, and an excellent edge
    recs = _market_recs(score=0.05)
    m = pr.measure([r for r in recs if r.rank <= 5], 15, recs)
    assert m["brier"] > m["brier_naive"] + 0.02  # it would have failed the old Brier rule
    default = pr.report_series(dict(SERIES), recs, "brain", has_baseline_pool=True)
    assert default["calibrated"] is False and default["health"]["top5"]["state"] == pr.HEALTHY
    flagged = pr.report_series({**SERIES, "calibrated": True}, recs, "brain", has_baseline_pool=True)
    assert flagged["health"]["top5"]["state"] == pr.FAIL
    assert "information only" in pr.plain_report({"disclaimer": "", "series": [default]})


def test_psi_is_a_warning_only_with_a_valid_reference_sample():
    recs = _market_recs()
    m = pr.measure([r for r in recs if r.rank <= 5], 15, recs)
    assert pr.health(m, GATE)["state"] == pr.HEALTHY
    assert pr.health(m, GATE, drift=pr.psi_flag(None, None))["state"] == pr.HEALTHY
    assert pr.health(m, GATE, drift={"measured": False, "psi": 9.0})["state"] == pr.HEALTHY
    assert pr.health(m, GATE, drift={"measured": True, "psi": 0.19})["state"] == pr.HEALTHY
    assert pr.health(m, GATE, drift={"measured": True, "psi": 0.2})["state"] == pr.WATCH
    # a reference or recent sample that is too small is "not measured"
    few = [0.5] * 10
    assert pr.psi_flag(few, few * 20)["measured"] is False
    assert pr.psi_flag(few * 20, None)["measured"] is False
    ref = [i / 100 for i in range(100)]
    shifted = [0.7 + i / 400 for i in range(100)]
    d = pr.psi_flag(ref, shifted)
    assert d["measured"] and d["psi"] >= 0.2
    assert pr.health(m, GATE, drift=d)["state"] == pr.WATCH


def test_drift_cannot_turn_a_fail_or_insufficient_into_anything_else():
    bad = make(60, lambda i, r: 0, lambda i, r: 1, -0.04, 0.03)
    m = pr.measure([r for r in bad if r.rank <= 5], 5, bad)
    assert pr.health(m, GATE, drift={"measured": True, "psi": 0.9})["state"] == pr.FAIL
    assert pr.health(None, GATE, drift={"measured": True, "psi": 0.9})["state"] == pr.INSUFFICIENT


def test_missing_required_evidence_is_never_healthy():
    recs = _market_recs()
    top = [r for r in recs if r.rank <= 5]
    # (a) lanes: a stored same-day baseline for returns but none for hit rate -> never HEALTHY
    lane = [Rec(r.day, r.symbol, r.score, r.rank, r.hit, r.ret, baseline_ret=r.ret - 0.01) for r in top]
    rep = pr.report_series({**SERIES, "source": "lane"}, lane, "lane", has_baseline_pool=False)
    st = rep["health"]["top5"]
    assert st["state"] == pr.WATCH and "not recorded" in st["why"]
    # (b) no stored baseline at all: avg_excess stays None (not 0) -> INSUFFICIENT
    nobase = [Rec(r.day, r.symbol, r.score, r.rank, r.hit, r.ret, None) for r in top]
    m = pr.measure(nobase, 15, None)
    assert m["avg_excess"] is None and m["hit_excess"] is None and m["baseline_avg_net"] is None
    rep = pr.report_series({**SERIES, "source": "lane"}, nobase, "lane", has_baseline_pool=False)
    assert rep["health"]["top5"]["state"] == pr.INSUFFICIENT
    # (c) too few days for the block test: gates met but no bound -> not HEALTHY
    short = _market_recs(20)
    ms = pr.measure([r for r in short if r.rank <= 5], 15, short)
    assert ms["days"] == 20 and pr.health(ms, GATE)["state"] == pr.WATCH
    # (d) open picks are None, not 0
    openm = pr.measure([Rec(OLD, "A", None, 1, None, None)], 5)
    assert openm["avg_net"] is None and openm["hit_rate"] is None and openm["completed"] == 0
    assert pr.split_sets([Rec(OLD, "A", None, 1, 1, 0.1)])["over_80"] == []  # missing score is not 0 or high


def test_states_are_diagnostic_only_nothing_is_imported_that_acts():
    import ast
    import inspect

    src = inspect.getsource(pr)
    tree = ast.parse(src)
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mods.add(node.module or "")
            mods.update(f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
    banned = (
        "trainer",
        "order",
        "kite",
        "activation",
        "registry",
        "promote",
        "retrain",
        "stage",
        "strategies",
    )
    assert not [m for m in mods if any(b in m.lower() for b in banned)], mods
    writes = {"add", "add_all", "commit", "flush", "delete", "merge", "bulk_save_objects", "write_text"}
    called = {
        n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    assert not (called & writes)
    assert "DIAGNOSTIC ONLY" in (pr.__doc__ or "")
    assert "never switch, retrain, disable or promote" in pr.build_report([])["disclaimer"]


def test_empty_input_is_insufficient_data():
    rep = pr.build_report([])
    assert rep["series"] == [] and rep["empty"]["state"] == pr.INSUFFICIENT
    assert "INSUFFICIENT DATA" in pr.plain_report(rep)
    rep = pr.build_report([(dict(SERIES), [], "brain", True)])
    assert rep["series"][0]["health"]["top5"]["state"] == pr.INSUFFICIENT


def test_accuracy_economics_ranking_calibration_drift_stay_separate():
    recs = _market_recs()
    rep = pr.report_series(dict(SERIES), recs, "brain", has_baseline_pool=True)
    m = rep["sets"]["top5"]
    for k in ("hit_rate", "avg_net", "avg_excess", "brier", "calibration"):
        assert k in m
    assert rep["ranking"]["net_gap_days"] == 60 and "drift" in rep
    assert not any(k in m for k in ("overall", "blended", "composite", "reliability_score"))


# ----------------------------------------------------------------------------- seal: nothing derivable


def _sealed_recs(n_days, ret_top, ret_rest, hit_top=1, start=None):
    start = start or trial_seal.SEALED_FROM
    return [
        Rec(d, f"S{r}", 0.9 - r * 0.05, r, hit_top if r <= 5 else 0, ret_top if r <= 5 else ret_rest)
        for d in days(n_days, start)
        for r in range(1, 9)
    ]


def _all_ints(obj, acc=None):
    acc = set() if acc is None else acc
    if isinstance(obj, dict):
        for v in obj.values():
            _all_ints(v, acc)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _all_ints(v, acc)
    elif isinstance(obj, int) and not isinstance(obj, bool):
        acc.add(obj)
    return acc


def test_seal_nothing_derivable_by_subtraction_or_difference(monkeypatch):
    monkeypatch.setattr(trial_seal, "SEALED", True)
    old = _market_recs(60)
    sealed_a = _sealed_recs(7, 0.0777123, -0.0233456)
    sealed_b = _sealed_recs(7, -0.0555321, 0.0411789, hit_top=0)  # same counts, opposite results

    def build(extra):
        return pr.build_report([(dict(SERIES), old + extra, "brain", True)])

    ra, rb, r0 = build(sealed_a), build(sealed_b), build([])
    # whatever the sealed results are, nothing in the output changes (so nothing can be recovered)
    assert json.dumps(ra, default=str) == json.dumps(rb, default=str)
    assert pr.plain_report(ra) == pr.plain_report(rb)
    # and every figure other than the sealed counts equals the run without sealed days (no total mixes them)
    sa, s0 = dict(ra["series"][0]), dict(r0["series"][0])
    assert sa.pop("sealed_counts") is not None and s0.pop("sealed_counts") is None
    sa.pop("sealed_note")
    s0.pop("sealed_note")
    assert sa == s0
    # no total of unsealed + sealed picks anywhere
    ints = _all_ints(ra)
    unsealed_top5, sealed_top5 = 60 * 5, 7 * 5
    assert unsealed_top5 in ints and sealed_top5 in ints and (unsealed_top5 + sealed_top5) not in ints
    assert (60 * 8 + 7 * 8) not in ints
    # no per-day series and no sealed date anywhere
    blob = json.dumps(ra, default=str) + pr.plain_report(ra)
    assert str(trial_seal.SEALED_FROM) not in blob and "2026-10-2" not in blob


def test_seal_counts_carry_no_result_fields(monkeypatch):
    monkeypatch.setattr(trial_seal, "SEALED", True)
    rep = pr.build_report([(dict(SERIES), _sealed_recs(10, 0.05, -0.02), "brain", True)])
    s = rep["series"][0]
    for c in s["sealed_counts"].values():
        assert c["avg_net"] is None and c["hit_rate"] is None
        assert set(c) == {"picked", "finished", "open", "avg_net", "hit_rate"}
    assert s["ranking"] is None
    assert all(h["state"] == pr.INSUFFICIENT for h in s["health"].values())
    assert s["sets"]["top5"]["picked"] == 0 and s["sets"]["top5"]["hit_rate"] is None


def test_seal_boundary_day_before_is_open_day_on_is_sealed(monkeypatch):
    monkeypatch.setattr(trial_seal, "SEALED", True)
    before = trial_seal.SEALED_FROM - timedelta(days=1)
    recs = [Rec(before, f"S{r}", 0.9, r, 1, 0.03) for r in range(1, 6)] + [
        Rec(trial_seal.SEALED_FROM, f"S{r}", 0.9, r, 0, -0.5) for r in range(1, 6)
    ]
    rep = pr.report_series(dict(SERIES), recs, "brain", has_baseline_pool=True)
    assert rep["sets"]["top5"]["picked"] == 5 and rep["sets"]["top5"]["avg_net"] == pytest.approx(0.03)
    assert rep["sealed_counts"]["top5"]["picked"] == 5
    assert "-0.5" not in json.dumps(rep, default=str)


def test_seal_off_control_shows_results(monkeypatch):
    monkeypatch.setattr(trial_seal, "SEALED", False)
    rep = pr.report_series(dict(SERIES), _sealed_recs(10, 0.05, -0.02), "brain", has_baseline_pool=True)
    assert rep["sealed_counts"] is None and rep["sets"]["top5"]["avg_net"] == pytest.approx(0.05)


def test_report_cli_output_and_dated_file_match_and_do_not_leak(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(trial_seal, "SEALED", True)

    class _Session:
        def __enter__(self):
            return object()

        def __exit__(self, *a):
            return False

    import swing_trade_ml.db.session as dbs

    monkeypatch.setattr(dbs, "SessionLocal", _Session)
    outs = {}
    for label, extra in (
        ("a", _sealed_recs(7, 0.0777123, -0.0233456)),
        ("b", _sealed_recs(7, -0.0911, 0.0422, hit_top=0)),
    ):
        data = [(dict(SERIES), _market_recs(60) + extra, "brain", True)]
        monkeypatch.setattr(pr, "collect", lambda db, s, e, data=data: data)
        d = tmp_path / label
        assert pr.main(["--from", "2026-01-01", "--to", "2026-12-31", "--out", str(d)]) == 0
        printed = capsys.readouterr().out
        files = list(d.glob("prediction-reliability-*.md"))
        assert len(files) == 1
        text = files[0].read_text(encoding="utf-8")
        assert text in printed
        for leak in ("0.0777", "7.77", "0.0233", "2.33", "0.0911", "9.11", "4.22"):
            assert leak not in text
        outs[label] = text
    assert outs["a"] == outs["b"]


def test_sample_gates_equal_the_existing_ones_and_lanes_package_is_not_imported():
    from swing_trade_ml.brain.lanes.h05_protocol import RUN_VALUES
    from swing_trade_ml.brain.trial_journal import GATE_MIN_IDEAS, MIN_SESSIONS
    from swing_trade_ml.shadow_lanes.lane_review import CHECKPOINTS

    g = pr._gates()
    assert g["h05"]["min_days"] == RUN_VALUES["min_evidence_per_group"]["matured_signal_days"]
    assert g["h05"]["min_completed"] == g["h05"]["min_days"]
    assert g["brain"] == {"min_days": MIN_SESSIONS, "min_completed": GATE_MIN_IDEAS}
    assert g["lane"] == {"min_days": CHECKPOINTS[0], "min_completed": CHECKPOINTS[0]}
    assert "brain.lanes" not in inspect.getsource(pr)
