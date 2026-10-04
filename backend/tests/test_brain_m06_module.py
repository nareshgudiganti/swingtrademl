"""M06 live: the saved combiner turns base-model scores on today's snapshot
into one calibrated chance, and M08 shows it honestly."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from brain_fakes import FakeReader, allow_all_risk_gate, fresh_quality, make_module, registry, request
from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.contracts import IdeaWord
from swing_trade_ml.brain.module import REGISTRY, Mode, Step
from swing_trade_ml.brain.modules.m06_reason import artifact
from swing_trade_ml.brain.modules.m06_reason import module as m06
from swing_trade_ml.brain.modules.m06_reason.module import Reasoning
from swing_trade_ml.brain.modules.m06_reason.trainer import Combiner, fit_honesty
from swing_trade_ml.brain.modules.m08_decide.module import DecisionEngine
from swing_trade_ml.brain.runner import execute
from swing_trade_ml.ml.features import FEATURE_COLUMNS


class FixedBundle:
    """A stand-in model bundle whose score is a feature's value."""

    def __init__(self, feature: str):
        self.feature = feature


def _payload(kind="meta_recent"):
    rng = np.random.default_rng(1)
    n = 2000
    frame = pd.DataFrame(
        {
            "day": pd.to_datetime(rng.choice(pd.bdate_range("2025-11-03", periods=200), n)),
            "p_barrier": rng.uniform(0.05, 0.6, n),
            "p_swing": rng.uniform(0.05, 0.6, n),
            "nifty_trend_regime": 1.0,
            "breadth_pct_above_sma50": 0.5,
            "vix_percentile_rank": 0.5,
            "relative_strength_20d": 0.0,
            "high_52w_dist": -0.1,
            "sector_trend_regime": 1.0,
        }
    )
    frame["target"] = (rng.uniform(0, 1, n) < frame["p_barrier"]).astype(int)
    return {
        "version": "v7",
        "combiner": Combiner.fit(frame, kind),
        "report": {
            "chosen": kind,
            "n_test_rows": 9551,
            "candidates": {
                kind: {
                    "auc": 0.636,
                    "top_decile_hit_rate": 0.409,
                    "calibration": [
                        {"low": 0.0, "high": 0.2, "n": 100, "mean_p": 0.1, "actual": 0.1},
                        {"low": 0.2, "high": 1.0, "n": 50, "mean_p": 0.5, "actual": 0.48},
                    ],
                }
            },
        },
        "base_models": {"barrier": "bm v1", "swing": "sm v1"},
    }


def _features(p_barrier: float) -> tuple:
    feats = dict.fromkeys(FEATURE_COLUMNS, 0.0)
    feats.update(
        {
            "rsi_14": p_barrier,
            "breadth_pct_above_sma50": 0.5,
            "nifty_trend_regime": 1.0,
            "sector_trend_regime": 1.0,
            "high_52w_dist": -0.1,
        }
    )
    return tuple(feats.items())


def _perceive(p_barrier=0.55):
    def run(view):
        return c.Contribution(
            snapshots=tuple(
                c.Snapshot(
                    symbol=s, as_of="2026-09-25", close=1000.0, atr_14=20.0, features=_features(p_barrier)
                )
                for s in view.request.universe
            )
        )

    return make_module("M02", Step.PERCEIVE, writes=("Snapshot@1",), run=run)


class Reader(FakeReader):
    def __init__(self, bundles=True, **kw):
        super().__init__(**kw)
        self.bundles = bundles

    def model_bundle(self, name, version):
        return FixedBundle("rsi_14") if self.bundles else None


@pytest.fixture(autouse=True)
def _fake_scoring(monkeypatch):
    monkeypatch.setattr(m06, "score_bundle", lambda bundle, feats: feats.get(bundle.feature))


def _run(reader, payload, *modules):
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(artifact, "load_latest", lambda: payload)
        return execute(request(), reader, registry(*modules), {"M06": Mode.ON})


def test_m06_is_the_reason_step_module_and_starts_on_trial():
    import swing_trade_ml.brain.modules  # noqa: F401

    assert REGISTRY.get("M06") is Reasoning
    assert Reasoning.manifest.step is Step.REASON and Reasoning.manifest.default_mode is Mode.SHADOW


def test_a_combined_calibrated_opinion_with_a_break_even_threshold():
    ctx = _run(Reader(), _payload(), _perceive(), Reasoning)
    op = next(o for o in ctx.opinions if o.source == "combined" and o.symbol == "ABC")
    assert op.calibrated and 0 < op.probability < 1
    assert 0.35 < op.threshold < 0.5  # break-even (about a third) plus a margin
    assert "Tested on 9551 unseen" in op.evidence


def test_m08_shows_the_calibrated_chance_and_expected_result():
    reg = (_perceive(0.6), Reasoning, allow_all_risk_gate(), fresh_quality(), DecisionEngine)
    ctx = _run(Reader(), _payload(), *reg)
    d = ctx.decisions["ABC"]
    assert "Calibrated chance" in d.evidence_text and " R per trade" in d.evidence_text


def test_a_low_calibrated_chance_is_wait_and_says_what_is_needed():
    reg = (_perceive(0.08), Reasoning, allow_all_risk_gate(), fresh_quality(), DecisionEngine)
    ctx = _run(Reader(), _payload(), *reg)
    d = ctx.decisions["ABC"]
    assert d.word is IdeaWord.WAIT and "needed to pay after costs" in d.reasons[0]


def test_no_trained_combiner_means_no_opinion():
    ctx = _run(Reader(), None, _perceive(), Reasoning)
    assert not [o for o in ctx.opinions if o.source == "combined"]


def test_missing_base_model_files_mean_no_opinion():
    ctx = _run(Reader(bundles=False), _payload(), _perceive(), Reasoning)
    assert not [o for o in ctx.opinions if o.source == "combined"]


def test_stocks_without_features_are_skipped():
    def bare(view):
        return c.Contribution(snapshots=(c.Snapshot(symbol="ABC", as_of="d", close=1000.0),))

    ctx = _run(
        Reader(), _payload(), make_module("M02", Step.PERCEIVE, writes=("Snapshot@1",), run=bare), Reasoning
    )
    assert not [o for o in ctx.opinions if o.source == "combined"]


def test_the_honesty_map_decides_the_chance_shown():
    """The combiner says ~60%; on unseen months such scores came true 30% of
    the time, so 30% is what the brain shows, and it waits."""
    payload = _payload()
    payload["honesty"] = fit_honesty(
        np.array([0.05, 0.95] * 500),
        np.array([0, 0, 1, 0, 0, 0] * 166 + [0] * 4),
        np.array(pd.bdate_range("2026-01-01", periods=1000)),
    )
    reg = (_perceive(0.6), Reasoning, allow_all_risk_gate(), fresh_quality(), DecisionEngine)
    ctx = _run(Reader(), payload, *reg)
    op = next(o for o in ctx.opinions if o.source == "combined")
    assert op.probability == pytest.approx(payload["honesty"].apply(np.array([0.6]))[0])
    assert op.probability < 0.4 and ctx.decisions["ABC"].word is IdeaWord.WAIT


def test_scores_beyond_what_testing_covered_are_flagged():
    payload = _payload()
    payload["honesty"] = fit_honesty(
        np.linspace(0.0, 0.3, 1000),
        np.array([0, 1] * 500),
        np.array(pd.bdate_range("2026-01-01", periods=1000)),
    )
    ctx = _run(Reader(), payload, _perceive(0.6), Reasoning)
    op = next(o for o in ctx.opinions if o.source == "combined")
    assert "beyond" in op.evidence
