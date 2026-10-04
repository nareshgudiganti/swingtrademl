"""Modifier opinions (sector tilt, later setups and events): they nudge the
order and add card lines, but never speak for a stock on their own."""

from __future__ import annotations

from brain_fakes import FakeReader, allow_all_risk_gate, fresh_quality, make_module, registry, request
from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.contracts import HoldingWord, IdeaWord, MarketMode
from swing_trade_ml.brain.module import Step
from swing_trade_ml.brain.modules.m08_decide.engine import (
    HoldingFacts,
    IdeaFacts,
    decide_holding,
    decide_idea,
)
from swing_trade_ml.brain.modules.m08_decide.module import DecisionEngine
from swing_trade_ml.brain.modules.m08_decide.policy import DecidePolicy
from swing_trade_ml.brain.opinions import TILT_WEIGHT, modifier_notes, pick_opinion, rank_strength
from swing_trade_ml.brain.runner import execute


def _model(symbol="ABC", p=0.7):
    return c.Opinion(
        source="model",
        symbol=symbol,
        stance=0.4,
        confidence=0.4,
        probability=p,
        threshold=0.6,
        reasons=(f"Model {p:.0%}.",),
    )


def _sector(symbol="ABC", stance=0.1):
    return c.Opinion(
        source="sector",
        symbol=symbol,
        stance=stance,
        confidence=0.3,
        reasons=("Sector: IT, ranked 1 of 15, leading.",),
    )


def test_a_sector_tilt_alone_never_speaks_for_a_stock():
    assert pick_opinion([_sector()]) is None
    assert pick_opinion([_sector(), _model()]).source == "model"


def test_the_tilt_only_breaks_ties_in_ranking():
    assert rank_strength([_model(p=0.70), _sector(stance=0.1)]) == 0.70 + TILT_WEIGHT * 0.1
    assert rank_strength([_model(p=0.70), _sector(stance=-0.1)]) < rank_strength([_model(p=0.70)])
    assert rank_strength([_sector()]) == 0.0


def test_notes_come_from_modifiers_only():
    assert modifier_notes([_model(), _sector()]) == ("Sector: IT, ranked 1 of 15, leading.",)


def test_an_idea_with_only_a_sector_tilt_waits_in_a_full_run():
    def perceive(view):
        return c.Contribution(
            snapshots=tuple(c.Snapshot(symbol=s, as_of="d", close=100.0) for s in view.request.universe),
            opinions=tuple(_sector(s) for s in view.request.universe),
        )

    reg = registry(
        make_module("M02", Step.PERCEIVE, writes=("Snapshot@1", "Opinion@1"), run=perceive),
        allow_all_risk_gate(),
        fresh_quality(),
        DecisionEngine,
    )
    ctx = execute(request(live=False), FakeReader(), reg, {})
    assert all(d.word is IdeaWord.WAIT for d in ctx.decisions.values())


def test_notes_are_added_to_cards_without_changing_the_word():
    facts = IdeaFacts(
        symbol="ABC",
        snapshot=c.Snapshot(symbol="ABC", as_of="d", close=1000.0, atr_14=20.0),
        opinion=_model(),
        verdict=c.RiskVerdict(symbol="ABC", allowed=True, max_qty=5),
        quality=c.DataQuality(symbol="ABC", score=1.0, fresh=True),
        stock=None,
        situations=(),
        recall=None,
        market_mode=MarketMode.NORMAL,
        notes=("Sector: IT, ranked 1 of 15, leading.",),
    )
    d = decide_idea(facts, DecidePolicy())
    assert d.word is IdeaWord.TRADE and d.reasons[-1].startswith("Sector: IT")

    h = decide_holding(
        HoldingFacts(
            holding=c.Holding(symbol="ABC", qty=5, avg_price=990.0),
            snapshot=facts.snapshot,
            stock=None,
            market_mode=MarketMode.NORMAL,
            notes=("Sector: IT, ranked 15 of 15, lagging.",),
        ),
        DecidePolicy(),
    )
    assert h.word is HoldingWord.HOLD and h.reasons[-1].startswith("Sector: IT")
