# backend/tests/test_brain_cost_stress.py
from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd

from swing_trade_ml.brain import cost_stress as cs
from swing_trade_ml.brain import walk_forward as wf
from swing_trade_ml.brain.replay_scoring import NORMAL, CostStress, after_day, strict_score

START = date(2026, 1, 1)


def _bars(closes):
    return pd.DataFrame(
        [
            {"day": START + timedelta(days=i), "open": c, "high": c * 1.01, "low": c * 0.99, "close": c}
            for i, c in enumerate(closes)
        ]
    )


class _FakeDb:
    def __init__(self, instruments):
        self._instruments = instruments

    def execute(self, *_a, **_k):
        return SimpleNamespace(scalars=lambda: iter(self._instruments))


def test_settings_are_normal_double_charges_worse_fills_and_both():
    assert [s.label for s in cs.STRESSES] == [
        "normal costs",
        "2x charges",
        "fills 0.30% worse",
        "2x charges, fills 0.30% worse",
    ]
    assert CostStress(charges_x=2.0, extra_slip=0.003) == cs.HARSHEST


def test_a_measured_slippage_is_added_once():
    assert cs.stresses_with(None) == cs.STRESSES
    assert cs.stresses_with(30) == cs.STRESSES  # same as the fixed 0.3%
    assert cs.stresses_with(12)[-1] == CostStress(extra_slip=0.0012)


def test_walk_forward_trains_each_model_once_and_costs_only_lower_results(monkeypatch):
    bars = {
        "UP": _bars([100.0 + 0.8 * i for i in range(200)]),
        "DOWN": _bars([300.0 - 0.8 * i for i in range(200)]),
    }
    monkeypatch.setattr(wf, "load_bars", lambda db, symbols, upto: bars)
    instruments = [SimpleNamespace(tradingsymbol="UP"), SimpleNamespace(tradingsymbol="DOWN")]
    trained, scored = [], []

    def train(db, cutoff, horizon, target, stop):
        trained.append(cutoff)
        return SimpleNamespace(roc_auc=0.6)

    def score(db, inst, model, after):
        scored.append((inst.tradingsymbol, after))
        good = 1.0 if inst.tradingsymbol == "UP" else 0.0
        return {START + timedelta(days=i): good for i in range(200)}

    out = cs.stress_walk_forward(
        _FakeDb(instruments),
        first_start=START + timedelta(days=40),
        last_end=START + timedelta(days=130),
        top_k=1,
        train_fn=train,
        score_fn=score,
    )
    assert list(out) == [s.label for s in cs.STRESSES]
    folds = out["normal costs"]["folds"]
    assert len(trained) == folds >= 3  # once per fold, not once per fold per cost setting
    assert len(scored) == 2 * folds
    base, harsh = out["normal costs"], out[cs.HARSHEST.label]
    assert base["model"]["ideas"] == harsh["model"]["ideas"]  # same picks
    assert harsh["model"]["avg_net"] < base["model"]["avg_net"]
    assert harsh["every_stock"]["avg_net"] < base["every_stock"]["avg_net"]


def test_stored_ideas_reproduce_at_normal_costs_and_mismatches_are_counted(monkeypatch):
    df = _bars([100.0 + 0.5 * i for i in range(60)])
    monkeypatch.setattr(cs, "load_bars", lambda db, symbols, upto: {"A": df})
    day = START + timedelta(days=3)
    stored = strict_score(after_day(df, day)).net_return
    ideas = [
        {"day": day.isoformat(), "symbol": "A", "strict_net_return": stored},
        {"day": day.isoformat(), "symbol": "A", "strict_net_return": stored + 0.01},
        {"day": day.isoformat(), "symbol": "GONE", "strict_net_return": 0.0},
    ]
    out = cs.stress_ideas(None, ideas)
    assert (out["reproduced"], out["mismatched"], out["no_price_data"]) == (1, 1, 1)
    assert out["by_costs"]["normal costs"]["ideas"] == 2
    assert out["by_costs"]["normal costs"]["avg_net"] == stored
    assert out["by_costs"][cs.HARSHEST.label]["avg_net"] < stored


def test_report_gives_the_one_sentence_answer():
    r = {"ideas": 1, "hit_rate": 0.0, "avg_net": -0.01}
    result = {
        "protocol": cs.PROTOCOL_ID,
        "harshest": cs.HARSHEST.label,
        "top_k": 5,
        "ideas_source": "x.json",
        "ideas": {
            "ideas": 1,
            "reproduced": 1,
            "mismatched": 0,
            "no_price_data": 0,
            "by_costs": {NORMAL.label: {**r, "avg_net": 0.002}, cs.HARSHEST.label: r},
        },
    }
    text = cs.plain_report(result)
    assert "does not stay above zero (-1.00%)" in text
    assert "Diagnostic on development data, not proof" in text
    assert cs.survives(0.001) == "stays above zero"
    assert cs.survives(None).startswith("not testable")
