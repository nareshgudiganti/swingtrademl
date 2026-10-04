"""The effective market mode: the market brain's mode, made more careful
(never bolder) when situation recognition suggests going defensive."""

from __future__ import annotations

from brain_fakes import FakeReader, allow_all_risk_gate, fresh_quality, make_module, registry, request
from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.contracts import MarketMode
from swing_trade_ml.brain.market_mode import effective_mode
from swing_trade_ml.brain.module import Mode, Step
from swing_trade_ml.brain.modules.m08_decide.module import DecisionEngine
from swing_trade_ml.brain.runner import execute

CRASH = c.Situation(
    scope="market",
    subject="NIFTY 50",
    label="crash",
    confidence=0.8,
    suggest_defensive=True,
    evidence=("NIFTY fell 5.0% on 23 Mar 2020.",),
)
CALM = c.MarketState(trend="up", mode=MarketMode.NORMAL, reasons=("Calm market.",))


def test_a_defensive_suggestion_turns_normal_into_defensive_with_its_reason():
    assert effective_mode(CALM, [CRASH]) == (MarketMode.DEFENSIVE, "NIFTY fell 5.0% on 23 Mar 2020.")


def test_effective_mode_never_gets_bolder():
    stop = c.MarketState(mode=MarketMode.NO_NEW_TRADES, reasons=("Data not fresh.",))
    assert effective_mode(stop, [CRASH]) == (MarketMode.NO_NEW_TRADES, None)


def test_without_a_suggestion_the_market_mode_stands():
    assert effective_mode(CALM, []) == (MarketMode.NORMAL, None)
    assert effective_mode(None, []) == (MarketMode.DEFENSIVE, None)
    stock = c.Situation(scope="stock", subject="ABC", label="x", confidence=1.0, suggest_defensive=True)
    assert effective_mode(CALM, [stock]) == (MarketMode.NORMAL, None)  # only market situations count


def _run(with_decide=True):
    def state(view):
        return c.Contribution(market=CALM)

    def recognise(view):
        return c.Contribution(situations=(CRASH,))

    mods = [
        make_module("M03", Step.STATE, writes=("MarketState@1",), run=state),
        make_module("M04", Step.RECOGNISE, writes=("Situation@1",), run=recognise),
        allow_all_risk_gate(),
        fresh_quality(),
    ]
    if with_decide:
        mods.append(DecisionEngine)
    return execute(request(), FakeReader(), registry(*mods), {"M04": Mode.ON})


def test_the_banner_follows_the_suggestion_and_names_it():
    ctx = _run()
    assert ctx.banner.mode is MarketMode.DEFENSIVE
    assert ctx.banner.headline == "NIFTY fell 5.0% on 23 Mar 2020."


def test_the_constitution_applies_it_even_without_the_decision_engine():
    ctx = _run(with_decide=False)
    assert ctx.banner.mode is MarketMode.DEFENSIVE


def test_the_constitution_catches_a_decide_module_that_ignored_it():
    def careless_decide(view):
        return c.Contribution(
            banner=c.Banner(mode=MarketMode.NORMAL, headline="All calm.", reasons=("All calm.",))
        )

    reg = registry(
        make_module("M03", Step.STATE, writes=("MarketState@1",), run=lambda v: c.Contribution(market=CALM)),
        make_module(
            "M04", Step.RECOGNISE, writes=("Situation@1",), run=lambda v: c.Contribution(situations=(CRASH,))
        ),
        allow_all_risk_gate(),
        fresh_quality(),
        make_module("M08", Step.DECIDE, writes=("Banner@1",), run=careless_decide),
    )
    ctx = execute(request(), FakeReader(), reg, {})
    assert ctx.banner.mode is MarketMode.DEFENSIVE and ctx.banner.headline.startswith("NIFTY fell")
