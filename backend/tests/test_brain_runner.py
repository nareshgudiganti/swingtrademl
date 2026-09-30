"""The brain runner: steps, fallbacks, shadow mode, budgets and the constitution.

These are the guarantees the rest of the brain is built on:
- a module can never break a run (it falls back instead),
- no TRADE leaves the brain without the mandatory risk gate,
- missing modules or data only ever make decisions more cautious.
"""

from __future__ import annotations

import time

from brain_fakes import (
    FakeReader,
    allow_all_risk_gate,
    fresh_quality,
    make_module,
    registry,
    request,
)
from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.contracts import HoldingWord, IdeaWord, MarketMode
from swing_trade_ml.brain.module import Mode, Step
from swing_trade_ml.brain.runner import execute


def _trace(ctx, module_id):
    return [e for e in ctx.trace if e.module_id == module_id]


# --- the empty brain -------------------------------------------------------


def test_empty_brain_decides_every_stock_and_trades_nothing():
    ctx = execute(request(), FakeReader(probabilities={"ABC": 0.9}), registry(), modes={})
    assert set(ctx.decisions) == {"ABC", "XYZ"}
    assert all(d.word in (IdeaWord.WATCH, IdeaWord.WAIT) for d in ctx.decisions.values())
    assert ctx.banner.mode is MarketMode.NO_NEW_TRADES


def test_empty_brain_explains_why_a_strong_stock_is_only_watch():
    ctx = execute(request(), FakeReader(probabilities={"ABC": 0.9}), registry(), modes={})
    abc = ctx.decisions["ABC"]
    assert abc.word is IdeaWord.WATCH
    assert abc.downgraded_from is IdeaWord.TRADE
    assert "risk gate" in abc.downgrade_reason.lower()


def test_every_step_uses_its_fallback_when_no_module_is_installed():
    ctx = execute(request(), FakeReader(), registry(), modes={})
    fallback_steps = {e.step for e in ctx.trace if e.module_id == "fallback" and e.status == "fallback"}
    assert fallback_steps == {s.value for s in Step}


def test_every_decision_has_a_reason():
    ctx = execute(request(), FakeReader(probabilities={"ABC": 0.9}), registry(), modes={})
    assert all(d.reasons for d in ctx.decisions.values())


def test_a_stock_with_no_price_data_is_wait_with_a_reason():
    reader = FakeReader(closes={"ABC": 100.0})
    ctx = execute(request(), reader, registry(), modes={})
    assert ctx.decisions["XYZ"].word is IdeaWord.WAIT
    assert "price" in ctx.decisions["XYZ"].reasons[0].lower()


# --- the risk gate and data quality -----------------------------------------


def test_with_risk_gate_and_fresh_data_a_strong_stock_is_a_trade():
    reg = registry(allow_all_risk_gate(max_qty=12), fresh_quality())
    ctx = execute(request(), FakeReader(probabilities={"ABC": 0.9}), reg, modes={})
    abc = ctx.decisions["ABC"]
    assert abc.word is IdeaWord.TRADE
    assert abc.qty == 12
    assert abc.stop == 96.0 and abc.target == 108.0
    assert ctx.banner.mode is MarketMode.NORMAL


def test_unchecked_data_caps_a_trade_at_watch():
    reg = registry(allow_all_risk_gate())
    ctx = execute(request(), FakeReader(probabilities={"ABC": 0.9}), reg, modes={})
    assert ctx.decisions["ABC"].word is IdeaWord.WATCH
    assert "data" in ctx.decisions["ABC"].downgrade_reason.lower()


def test_stale_data_caps_a_trade_at_watch():
    def stale(view):
        return c.Contribution(quality=(c.DataQuality(symbol="ABC", score=0.3, fresh=False),))

    reg = registry(
        allow_all_risk_gate(),
        make_module("M01", Step.PERCEIVE, writes=("DataQuality@1",), run=stale),
    )
    ctx = execute(request(), FakeReader(probabilities={"ABC": 0.9}), reg, modes={})
    assert ctx.decisions["ABC"].word is IdeaWord.WATCH


def test_a_refused_verdict_blocks_the_trade():
    def refuse(view):
        return c.Contribution(verdicts=(c.RiskVerdict(symbol="ABC", allowed=False, reason="Sector full"),))

    gate = make_module("M07", Step.RISK, writes=("RiskVerdict@1",), run=refuse, mandatory=True)
    ctx = execute(
        request(), FakeReader(probabilities={"ABC": 0.9}), registry(gate, fresh_quality()), modes={}
    )
    assert ctx.decisions["ABC"].word is not IdeaWord.TRADE


def test_a_failing_risk_gate_means_no_new_trades():
    def boom(view):
        raise RuntimeError("risk service down")

    gate = make_module("M07", Step.RISK, writes=("RiskVerdict@1",), run=boom, mandatory=True)
    ctx = execute(
        request(), FakeReader(probabilities={"ABC": 0.9}), registry(gate, fresh_quality()), modes={}
    )
    assert ctx.banner.mode is MarketMode.NO_NEW_TRADES
    assert ctx.decisions["ABC"].word is IdeaWord.WATCH


def test_verdicts_from_a_non_mandatory_module_are_rejected():
    def sneaky(view):
        return c.Contribution(verdicts=(c.RiskVerdict(symbol="ABC", allowed=True, max_qty=5),))

    imposter = make_module("M99", Step.RISK, writes=("RiskVerdict@1",), run=sneaky, kind="plugin")
    ctx = execute(
        request(), FakeReader(probabilities={"ABC": 0.9}), registry(imposter, fresh_quality()), modes={}
    )
    assert ctx.decisions["ABC"].word is IdeaWord.WATCH
    assert _trace(ctx, "M99")[0].status == "rejected"


def test_owner_halt_means_no_new_trades():
    reg = registry(allow_all_risk_gate(), fresh_quality())
    ctx = execute(request(), FakeReader(probabilities={"ABC": 0.9}, halted=True), reg, modes={})
    assert ctx.banner.mode is MarketMode.NO_NEW_TRADES
    assert ctx.decisions["ABC"].word is IdeaWord.WATCH
    assert "paused" in ctx.decisions["ABC"].downgrade_reason.lower()


def test_the_risk_gate_cannot_be_switched_off():
    reg = registry(allow_all_risk_gate(), fresh_quality())
    ctx = execute(request(), FakeReader(probabilities={"ABC": 0.9}), reg, modes={"M07": Mode.OFF})
    assert ctx.decisions["ABC"].word is IdeaWord.TRADE
    assert _trace(ctx, "M07")[0].status == "used"


# --- module failures fall back ----------------------------------------------


def test_a_module_that_raises_falls_back_and_the_run_completes():
    def boom(view):
        raise ValueError("bad maths")

    reg = registry(make_module("M02", Step.PERCEIVE, writes=("Snapshot@1",), run=boom))
    ctx = execute(request(), FakeReader(), reg, modes={})
    event = _trace(ctx, "M02")[0]
    assert event.status == "fallback" and "bad maths" in event.reason
    assert "ABC" in ctx.snapshots


def test_a_module_writing_an_undeclared_contract_is_rejected():
    def overreach(view):
        return c.Contribution(
            opinions=(c.Opinion(source="M02", symbol="ABC", stance=1, confidence=1, reasons=("x",)),)
        )

    reg = registry(make_module("M02", Step.PERCEIVE, writes=("Snapshot@1",), run=overreach))
    ctx = execute(request(), FakeReader(), reg, modes={})
    assert _trace(ctx, "M02")[0].status == "fallback"
    assert "undeclared" in _trace(ctx, "M02")[0].reason
    assert not [o for o in ctx.opinions if o.source == "M02"]


def test_a_module_over_its_time_budget_is_discarded():
    def slow(view):
        time.sleep(0.12)
        return c.Contribution(snapshots=(c.Snapshot(symbol="ABC", as_of="2026-09-29", close=999.0),))

    reg = registry(make_module("M02", Step.PERCEIVE, writes=("Snapshot@1",), run=slow, budget_s=0.05))
    ctx = execute(request(), FakeReader(), reg, modes={})
    assert _trace(ctx, "M02")[0].status == "fallback"
    assert ctx.snapshots["ABC"].close == 100.0


def test_a_module_reading_an_undeclared_contract_falls_back():
    def peek(view):
        _ = view.opinions  # not in reads
        return c.Contribution()

    reg = registry(make_module("M03", Step.STATE, writes=("MarketState@1",), run=peek))
    ctx = execute(request(), FakeReader(), reg, modes={})
    assert _trace(ctx, "M03")[0].status == "fallback"


# --- modes -----------------------------------------------------------------


def test_a_switched_off_module_is_skipped_and_the_fallback_answers():
    def snap(view):
        return c.Contribution(snapshots=(c.Snapshot(symbol="ABC", as_of="2026-09-29", close=999.0),))

    reg = registry(make_module("M02", Step.PERCEIVE, writes=("Snapshot@1",), run=snap))
    ctx = execute(request(), FakeReader(), reg, modes={"M02": Mode.OFF})
    assert _trace(ctx, "M02")[0].status == "skipped"
    assert ctx.snapshots["ABC"].close == 100.0


def test_a_shadow_module_is_recorded_but_not_used():
    def snap(view):
        return c.Contribution(snapshots=(c.Snapshot(symbol="ABC", as_of="2026-09-29", close=999.0),))

    reg = registry(make_module("M02", Step.PERCEIVE, writes=("Snapshot@1",), run=snap))
    ctx = execute(request(), FakeReader(), reg, modes={"M02": Mode.SHADOW})
    assert _trace(ctx, "M02")[0].status == "shadow"
    assert ctx.snapshots["ABC"].close == 100.0
    assert ctx.shadow["M02"].snapshots[0].close == 999.0


# --- merge rules -------------------------------------------------------------


def test_a_later_plugin_cannot_overwrite_an_earlier_modules_snapshot():
    def first(view):
        return c.Contribution(snapshots=(c.Snapshot(symbol="ABC", as_of="d", close=1.0),))

    def second(view):
        return c.Contribution(snapshots=(c.Snapshot(symbol="ABC", as_of="d", close=2.0),))

    reg = registry(
        make_module("M02", Step.PERCEIVE, writes=("Snapshot@1",), run=first),
        make_module("M90", Step.PERCEIVE, writes=("Snapshot@1",), run=second, kind="plugin"),
    )
    ctx = execute(request(), FakeReader(), reg, modes={})
    assert ctx.snapshots["ABC"].close == 1.0


# --- holdings, kinds, determinism, monotonicity ----------------------------------


def test_holdings_get_a_holding_decision():
    reader = FakeReader(
        symbols=("ABC",),
        holdings=(c.Holding(symbol="HELD", qty=5, avg_price=90.0),),
        closes={"ABC": 100.0, "HELD": 95.0},
    )
    ctx = execute(request(universe=("ABC",)), reader, registry(), modes={})
    held = ctx.decisions["HELD"]
    assert held.kind == "holding" and held.word is HoldingWord.HOLD


def test_intraday_run_skips_the_middle_steps():
    ctx = execute(request(kind="intraday"), FakeReader(), registry(), modes={})
    steps = {e.step for e in ctx.trace}
    assert Step.RECOGNISE.value not in steps and Step.LEARN.value not in steps
    assert Step.RISK.value in steps


def test_replay_does_not_use_live_only_inputs():
    ctx = execute(request(live=False), FakeReader(probabilities={"ABC": 0.9}), registry(), modes={})
    assert not ctx.opinions


def test_same_inputs_give_identical_decisions():
    reg = registry(allow_all_risk_gate(), fresh_quality())
    reader = FakeReader(probabilities={"ABC": 0.9, "XYZ": 0.4})
    a = execute(request(), reader, reg, modes={})
    b = execute(request(), reader, reg, modes={})
    assert a.decisions == b.decisions and a.banner == b.banner


def test_switching_any_module_off_never_makes_a_decision_bolder():
    def market_up(view):
        return c.Contribution(
            market=c.MarketState(trend="up", volatility="normal", mode=MarketMode.NORMAL, reasons=("Up",))
        )

    modules = (
        allow_all_risk_gate(),
        fresh_quality(),
        make_module("M03", Step.STATE, writes=("MarketState@1",), run=market_up),
    )
    reg = registry(*modules)
    reader = FakeReader(probabilities={"ABC": 0.9, "XYZ": 0.62})
    full = execute(request(), reader, reg, modes={})
    for cls in modules:
        reduced = execute(request(), reader, reg, modes={cls.manifest.id: Mode.OFF})
        for symbol, decision in reduced.decisions.items():
            assert c.rank(decision.word) <= c.rank(full.decisions[symbol].word), (cls.manifest.id, symbol)


def test_market_wide_stale_data_means_no_new_trades():
    def market_stale(view):
        return c.Contribution(
            quality=(
                c.DataQuality(symbol="ABC", score=1.0, fresh=True),
                c.DataQuality(symbol="*", score=0.3, fresh=False, issues=("NIFTY data is not fresh",)),
            )
        )

    reg = registry(
        allow_all_risk_gate(), make_module("M01", Step.PERCEIVE, writes=("DataQuality@1",), run=market_stale)
    )
    ctx = execute(request(), FakeReader(probabilities={"ABC": 0.9}), reg, modes={})
    assert ctx.banner.mode is MarketMode.NO_NEW_TRADES
    assert ctx.decisions["ABC"].word is IdeaWord.WATCH
    assert "NIFTY" in ctx.decisions["ABC"].downgrade_reason
