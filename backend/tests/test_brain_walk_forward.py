"""Walk-forward back-test: windows, baselines, the verdict rule and a full run on fake data."""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from swing_trade_ml.brain import walk_forward as wf
from swing_trade_ml.brain.replay_scoring import StrictOutcome

START = date(2026, 1, 1)


def _bars(closes, start=START) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"day": start + timedelta(days=i), "open": c, "high": c * 1.001, "low": c * 0.999, "close": c}
            for i, c in enumerate(closes)
        ]
    )


def test_folds_are_back_to_back_and_the_cutoff_is_the_day_before():
    folds = wf.make_folds(date(2026, 1, 1), date(2026, 3, 31), test_days=28)
    assert [f.start for f in folds[:2]] == [date(2026, 1, 1), date(2026, 1, 29)]
    assert all(f.cutoff == f.start - timedelta(days=1) for f in folds)
    assert folds[0].end + timedelta(days=1) == folds[1].start
    assert folds[-1].end == date(2026, 3, 25)  # the 6 days left after it are too few


def test_a_tiny_last_window_is_dropped():
    folds = wf.make_folds(date(2026, 1, 1), date(2026, 1, 31), test_days=28)
    assert len(folds) == 1  # 29 to 31 Jan is 3 days: too short to mean anything


def test_the_last_scoreable_day_leaves_time_for_picks_to_finish():
    assert wf.latest_scoreable_end(date(2026, 10, 12)) == date(2026, 9, 17)


def test_momentum_uses_only_the_past():
    closes = [100.0] * 20 + [110.0, 120.0]
    out = wf.momentum_scores({"A": _bars(closes)}, [START + timedelta(days=20), START + timedelta(days=21)])[
        "A"
    ]
    assert out[START + timedelta(days=20)] == pytest.approx(0.10)
    assert out[START + timedelta(days=21)] == pytest.approx(0.20)


def test_momentum_skips_days_without_enough_history():
    assert wf.momentum_scores({"A": _bars([100.0] * 10)}, [START + timedelta(days=5)])["A"] == {}


@pytest.mark.parametrize(("end_close", "label"), [(110.0, "rising"), (90.0, "falling"), (101.0, "sideways")])
def test_window_is_labelled_by_how_the_average_stock_moved(end_close, label):
    df = _bars([100.0, 100.0, end_close])
    assert wf.classify_regime({"A": df}, START, START + timedelta(days=2))["label"] == label


def test_bootstrap_low_is_positive_for_a_steady_edge_and_not_for_noise():
    assert wf.bootstrap_low([0.01] * 60) > 0
    noisy = [0.05, -0.05] * 30
    assert wf.bootstrap_low(noisy) < 0.01
    assert wf.bootstrap_low([0.01] * 10) is None  # fewer than two blocks of 15 days


def test_blocks_make_a_streaky_edge_less_certain_than_single_days():
    streaky = ([0.02] * 15 + [-0.02] * 15) * 4  # the same average as noise, but in long runs
    assert wf.bootstrap_low(streaky, block=15) < wf.bootstrap_low(streaky, block=1)


def _row(days=19, ideas=50, model=0.01, every=0.0):
    return {
        "days": days,
        "model": {"ideas": ideas, "avg_net_by_day": model},
        "every_stock": {"avg_net_by_day": every},
    }


def test_a_fold_with_too_few_days_or_ideas_is_not_eligible():
    assert wf.is_eligible(_row())
    assert not wf.is_eligible(_row(days=9))
    assert not wf.is_eligible(_row(ideas=19))


def _verdict(**over):
    base = {
        "model_ideas": 500,
        "eligible": 20,
        "predictive_wins": 14,
        "economic_wins": 14,
        "edge_low": 0.001,
        "pooled_avg_net": 0.002,
    }
    return wf.verdict(**{**base, **over})


def test_both_parts_pass_only_with_enough_folds_won_and_the_extra_check():
    v = _verdict()
    assert (v["predictive"]["word"], v["economic"]["word"]) == ("pass", "pass")
    assert _verdict(predictive_wins=11)["predictive"]["word"] == "fail"  # 55% is under 60%
    assert _verdict(predictive_wins=12)["predictive"]["word"] == "pass"  # exactly 60%
    assert _verdict(edge_low=-0.001)["predictive"]["word"] == "fail"


def test_the_two_parts_are_independent():
    v = _verdict(edge_low=-0.001)  # beat-random check fails, profit still passes
    assert (v["predictive"]["word"], v["economic"]["word"]) == ("fail", "pass")
    assert "make money" not in v["reading"] and "made money" in v["reading"]
    v = _verdict(pooled_avg_net=-0.001)
    assert (v["predictive"]["word"], v["economic"]["word"]) == ("pass", "fail")


def test_too_few_folds_or_ideas_is_insufficient_not_a_fail():
    assert _verdict(eligible=11)["predictive"]["word"] == "insufficient"
    assert _verdict(model_ideas=99)["economic"]["word"] == "insufficient"
    assert _verdict(edge_low=None)["predictive"]["word"] == "insufficient"


def test_daily_edge_is_picks_minus_every_stock():
    day = START
    win = StrictOutcome("target", 0.08, 3, False, False, day)
    loss = StrictOutcome("stop", -0.04, 2, False, False, day)
    outcomes = {("A", day): win, ("B", day): loss}
    assert wf.daily_edge({day: ["A"]}, {day: ["A", "B"]}, outcomes) == [pytest.approx(0.08 - 0.02)]


def test_open_ideas_are_left_out_of_the_edge():
    day = START
    open_ = StrictOutcome("open", None, None, False, False, None)
    assert wf.daily_edge({day: ["A"]}, {day: ["A"]}, {("A", day): open_}) == []


class _FakeDb:
    def __init__(self, instruments):
        self._instruments = instruments

    def execute(self, *_a, **_k):
        return SimpleNamespace(scalars=lambda: iter(self._instruments))


def _universe(n_days=200):
    """UP rises steadily, DOWN falls steadily; both have bars long enough for 15-day outcomes."""
    up = _bars([100.0 + 0.8 * i for i in range(n_days)])
    down = _bars([300.0 - 0.8 * i for i in range(n_days)])
    return {"UP": up, "DOWN": down}


def test_a_model_that_picks_the_riser_beats_every_stock_in_every_window(monkeypatch):
    bars = _universe()
    monkeypatch.setattr(wf, "load_bars", lambda db, symbols, upto: bars)
    instruments = [SimpleNamespace(tradingsymbol="UP"), SimpleNamespace(tradingsymbol="DOWN")]
    trained = []

    def train(db, cutoff, horizon, target, stop):
        trained.append(cutoff)
        return SimpleNamespace(roc_auc=0.6)

    def score(db, inst, model, after):
        good = 1.0 if inst.tradingsymbol == "UP" else 0.0
        return {START + timedelta(days=i): good for i in range(200)}

    res = wf.run_walk_forward(
        _FakeDb(instruments),
        first_start=START + timedelta(days=40),
        last_end=START + timedelta(days=130),
        test_days=28,
        top_k=1,
        train_fn=train,
        score_fn=score,
    )
    assert len(res["folds"]) == len(trained) >= 3
    # each model was trained the day before its own window and never later
    assert all(
        c == date.fromisoformat(f["start"]) - timedelta(days=1)
        for c, f in zip(trained, res["folds"], strict=True)
    )
    for f in res["folds"]:
        assert f["model"]["avg_net"] > f["every_stock"]["avg_net"]
        assert f["model_days_better"]["better"] == f["model_days_better"]["of"] > 0
    assert res["pooled"]["model_edge_per_day"] > 0
    assert res["protocol"] == wf.PROTOCOL_VERSION
    # momentum also picks the riser here, so the simple rule matches the model
    assert res["pooled"]["momentum"]["avg_net"] == pytest.approx(res["pooled"]["model"]["avg_net"])


def test_report_names_the_verdict_and_every_window(monkeypatch):
    bars = _universe()
    monkeypatch.setattr(wf, "load_bars", lambda db, symbols, upto: bars)
    instruments = [SimpleNamespace(tradingsymbol="UP"), SimpleNamespace(tradingsymbol="DOWN")]
    res = wf.run_walk_forward(
        _FakeDb(instruments),
        first_start=START + timedelta(days=40),
        last_end=START + timedelta(days=100),
        test_days=28,
        top_k=1,
        train_fn=lambda *a: SimpleNamespace(roc_auc=None),
        score_fn=lambda db, inst, model, after: {START + timedelta(days=i): 0.5 for i in range(200)},
    )
    text = wf.plain_report(res)
    assert "## Verdict:" in text and "Predictive skill" in text
    assert text.count("| 2026-") >= len(res["folds"])


def test_no_window_fitting_is_an_error():
    with pytest.raises(ValueError):
        wf.run_walk_forward(None, first_start=date(2026, 6, 1), last_end=date(2026, 6, 3))
