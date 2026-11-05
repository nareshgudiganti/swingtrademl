"""Prediction Reliability: pure measures, health states, no pooling, open outcomes, and the trial seal."""

from __future__ import annotations

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


def test_drift_not_measured_is_honest_and_flags_watch():
    assert pr.psi_flag(None, None)["text"] == "drift: not measured"
    good = make(60, lambda i, r: 1, lambda i, r: 0, 0.05, -0.02)
    m = pr.measure(good[:], 5, good)
    m["avg_excess"] = 0.05
    drift = {"measured": True, "psi": 0.5, "text": "x"}
    assert pr.health(m, GATE, drift=drift)["state"] in (pr.WATCH, pr.FAIL)


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
