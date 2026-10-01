"""M08 inside a full brain run (fake reader, no database)."""

from __future__ import annotations

from brain_fakes import FakeReader, allow_all_risk_gate, fresh_quality, registry, request
from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.contracts import HoldingWord, IdeaWord
from swing_trade_ml.brain.module import REGISTRY, Step
from swing_trade_ml.brain.modules.m08_decide.module import DecisionEngine
from swing_trade_ml.brain.opinions import pick_opinion
from swing_trade_ml.brain.runner import execute


def test_m08_is_the_decide_step_module():
    import swing_trade_ml.brain.modules  # noqa: F401

    assert REGISTRY.get("M08") is DecisionEngine
    assert DecisionEngine.manifest.step is Step.DECIDE and DecisionEngine.manifest.kind == "step"


def test_a_full_run_gives_a_trade_with_zone_levels_size_and_evidence():
    reg = registry(allow_all_risk_gate(max_qty=12), fresh_quality(), DecisionEngine)
    ctx = execute(request(), FakeReader(probabilities={"ABC": 0.9}), reg, modes={})
    d = ctx.decisions["ABC"]
    assert d.word is IdeaWord.TRADE and d.qty == 12
    assert d.target == 108.0 and d.stop == 96.0 and d.entry_low is not None
    assert "No similar-case record yet" in d.evidence_text
    assert any(e.module_id == "M08" and e.status == "used" for e in ctx.trace)


def test_the_banner_comes_from_m08():
    reg = registry(allow_all_risk_gate(), fresh_quality(), DecisionEngine)
    ctx = execute(request(), FakeReader(probabilities={"ABC": 0.9}), reg, modes={})
    assert ctx.banner.headline == ctx.market.reasons[0]


def test_holdings_get_a_holding_word_from_m08():
    held = (c.Holding(symbol="HLD", qty=5, avg_price=100.0, stop=96.0),)
    reader = FakeReader(symbols=("ABC",), closes={"ABC": 100.0, "HLD": 95.0}, holdings=held)
    ctx = execute(request(universe=("ABC",)), reader, registry(DecisionEngine), modes={})
    assert ctx.decisions["HLD"].word is HoldingWord.EXIT
    assert ctx.decisions["HLD"].reasons[0].startswith("Stop hit")


def test_with_only_m08_installed_every_stock_is_still_decided_and_nothing_trades():
    ctx = execute(request(), FakeReader(probabilities={"ABC": 0.9}), registry(DecisionEngine), modes={})
    assert set(ctx.decisions) == {"ABC", "XYZ"}
    assert all(d.word is not IdeaWord.TRADE for d in ctx.decisions.values())


def test_pick_opinion_prefers_the_combined_view_then_the_model():
    model = c.Opinion(source="model", symbol="A", stance=0.5, confidence=0.5, reasons=("m",))
    combined = c.Opinion(source="combined", symbol="A", stance=-0.2, confidence=0.6, reasons=("c",))
    other = c.Opinion(source="sector", symbol="A", stance=0.9, confidence=0.9, reasons=("s",))
    assert pick_opinion([other, model, combined]) is combined
    assert pick_opinion([other, model]) is model
    assert pick_opinion([other]) is other
    assert pick_opinion([]) is None
