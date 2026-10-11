"""Caution only: bad or missing inputs may never make the brain bolder.

CLAUDE.md principle 5: "Decisions only move toward caution. Bad/stale data never
makes a decision more aggressive. Missing M07 risk gate -> NO NEW TRADES."

The constitution pass (the last step of every run) is a pure function of the run
context, so instead of a handful of hand-picked cases this walks EVERY combination
of: risk gate ran or not, owner halt, market-wide data freshness, the risk verdict,
the stock's own data freshness, the banner a module wrote, and a defensive
suggestion from situation recognition. For each one, for each word a module could
have proposed, it checks the rules that must always hold.

No database, no network: it runs in a second.
"""

from __future__ import annotations

from datetime import UTC, datetime
from itertools import product

import pytest

from swing_trade_ml.brain import constitution
from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.context import BrainContext
from swing_trade_ml.brain.contracts import HoldingWord, IdeaWord, MarketMode, rank

SYMBOL = "AAA"
HELD = "HLD"
AS_OF = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)

GATE = (True, False)  # did the mandatory risk gate run
SYSTEM = ("none", "ok", "halted")  # owner halt on new buys
OVERALL = ("absent", "fresh", "stale")  # market-wide data quality ("*")
VERDICT = ("absent", "allowed", "denied")  # M07's verdict for the stock
OWN = ("absent", "fresh", "stale")  # the stock's own data quality
BANNER_IN = (None, *MarketMode)  # what a module wrote
SUGGEST = (False, True)  # M04 suggests going defensive
PROPOSED = tuple(IdeaWord)  # every word a module could have proposed


def _quality(symbol: str, kind: str) -> list[c.DataQuality]:
    if kind == "absent":
        return []
    fresh = kind == "fresh"
    return [
        c.DataQuality(
            symbol=symbol,
            score=1.0 if fresh else 0.2,
            fresh=fresh,
            issues=() if fresh else ("last bar is old",),
        )
    ]


def _context(gate, system, overall, verdict, own, banner_in, suggest, word) -> BrainContext:
    ctx = BrainContext(
        request=c.RunRequest(run_id="caution", kind="nightly", as_of=AS_OF, universe=(SYMBOL,)),
        reader=None,
        risk_gate_ran=gate,
    )
    if system != "none":
        ctx.system = c.SystemState(entries_halted=system == "halted", halt_reason="paused for the test")
    for q in (*_quality("*", overall), *_quality(SYMBOL, own)):
        ctx.quality[q.symbol] = q
    if verdict != "absent":
        ctx.verdicts[SYMBOL] = c.RiskVerdict(symbol=SYMBOL, allowed=verdict == "allowed", max_qty=10)
    if banner_in is not None:
        ctx.banner = c.Banner(mode=banner_in, headline="written by a module")
    ctx.market = c.MarketState(mode=banner_in)
    if suggest:
        ctx.situations.append(
            c.Situation(
                scope="market",
                subject="NIFTY",
                label="crash",
                confidence=0.9,
                suggest_defensive=True,
                evidence=("a sharp fall",),
            )
        )
    ctx.decisions[SYMBOL] = c.Decision(
        symbol=SYMBOL,
        kind="idea",
        word=word,
        reasons=("proposed by a module",),
        entry_low=100.0,
        entry_high=101.0,
        target=108.0,
        stop=96.0,
        qty=10 if word is IdeaWord.TRADE else 0,
    )
    ctx.decisions[HELD] = c.Decision(
        symbol=HELD, kind="holding", word=HoldingWord.HOLD, reasons=("still fine",)
    )
    return ctx


def _stop_reasons_expected(gate, system, overall, banner_in=None) -> bool:
    return (not gate) or system == "halted" or overall == "stale" or banner_in is MarketMode.NO_NEW_TRADES


ALL = list(product(GATE, SYSTEM, OVERALL, VERDICT, OWN, BANNER_IN, SUGGEST, PROPOSED))


def _label(args) -> str:
    gate, system, overall, verdict, own, banner_in, suggest, word = args
    return (
        f"gate={gate} system={system} overall={overall} verdict={verdict} own={own} "
        f"banner_in={banner_in} suggest={suggest} proposed={word.value}"
    )


def test_the_grid_covers_every_combination():
    assert len(ALL) == 2 * 3 * 3 * 3 * 3 * 4 * 2 * 4  # 7,776 situations


def test_no_input_ever_makes_a_decision_bolder():
    """For every situation: the word never goes up, a TRADE survives only when
    every safety check passed, and the banner is never bolder than written."""
    for args in ALL:
        gate, system, overall, verdict, own, banner_in, _suggest, word = args
        ctx = _context(*args)
        constitution.enforce(ctx)
        out = ctx.decisions[SYMBOL]
        where = _label(args)

        # 1. never bolder than proposed; a holding is never touched
        assert rank(out.word) <= rank(word), f"became bolder: {where}"
        assert ctx.decisions[HELD].word is HoldingWord.HOLD, f"holding changed: {where}"

        # 2. a TRADE comes out only if every check passed
        if out.word is IdeaWord.TRADE:
            assert gate, f"TRADE without the risk gate: {where}"
            assert system != "halted", f"TRADE while the owner paused buying: {where}"
            assert banner_in is not MarketMode.NO_NEW_TRADES, f"TRADE under a NO NEW TRADES banner: {where}"
            assert overall != "stale", f"TRADE on stale market data: {where}"
            assert verdict == "allowed", f"TRADE without an allowed verdict: {where}"
            assert own == "fresh", f"TRADE without fresh data for the stock: {where}"
            assert word is IdeaWord.TRADE, f"TRADE out of nothing: {where}"

        # 3. and a TRADE that passes every check is not blocked for no reason
        if (
            word is IdeaWord.TRADE
            and gate
            and system != "halted"
            and overall != "stale"
            and verdict == "allowed"
            and own == "fresh"
            and banner_in is not MarketMode.NO_NEW_TRADES
        ):
            assert out.word is IdeaWord.TRADE, f"a clean TRADE was blocked: {where}"

        # 4. a lowered decision says so, and has nothing to buy
        if out.word is not word:
            assert out.downgraded_from is word, f"downgrade not recorded: {where}"
            assert out.downgrade_reason, f"downgrade has no reason: {where}"
            assert out.reasons[0] == out.downgrade_reason, f"reason not first: {where}"
            assert out.qty == 0, f"a lowered idea still has a quantity: {where}"


def test_the_banner_is_never_bolder_than_what_was_written():
    for args in ALL:
        gate, system, overall, _verdict, _own, banner_in, suggest, _word = args
        ctx = _context(*args)
        constitution.enforce(ctx)
        where = _label(args)
        assert ctx.banner is not None, f"no banner: {where}"

        if _stop_reasons_expected(gate, system, overall, banner_in):
            assert ctx.banner.mode is MarketMode.NO_NEW_TRADES, f"should stop all new trades: {where}"
        if banner_in is None:
            assert ctx.banner.mode is not MarketMode.NORMAL, f"no banner written but NORMAL: {where}"
        else:
            assert rank(ctx.banner.mode) <= rank(banner_in), f"banner became bolder: {where}"
        # a defensive suggestion is never lost on a NORMAL banner
        if (
            banner_in is MarketMode.NORMAL
            and suggest
            and not _stop_reasons_expected(gate, system, overall, banner_in)
        ):
            assert ctx.banner.mode is MarketMode.DEFENSIVE, f"defensive suggestion lost: {where}"


def test_no_new_trades_means_no_trade_decision_at_all():
    for args in ALL:
        ctx = _context(*args)
        constitution.enforce(ctx)
        if ctx.banner.mode is MarketMode.NO_NEW_TRADES:
            assert ctx.decisions[SYMBOL].word is not IdeaWord.TRADE, _label(args)


def test_every_stock_always_gets_a_decision_with_a_reason():
    """C11: a stock no module decided on still gets a cautious, explained answer."""
    ctx = BrainContext(
        request=c.RunRequest(run_id="c11", kind="nightly", as_of=AS_OF, universe=("A", "B", "C")),
        reader=None,
        risk_gate_ran=True,
    )
    constitution.enforce(ctx)
    assert set(ctx.decisions) == {"A", "B", "C"}
    for d in ctx.decisions.values():
        assert d.word is IdeaWord.WAIT
        assert d.reasons and all(r.strip() for r in d.reasons)


@pytest.mark.parametrize("word", PROPOSED)
def test_running_the_constitution_twice_changes_nothing(word):
    """Idempotent: a second pass over an already-checked run lowers nothing further."""
    for args in ALL:
        if args[-1] is not word:
            continue
        ctx = _context(*args)
        constitution.enforce(ctx)
        once = (ctx.banner, dict(ctx.decisions))
        constitution.enforce(ctx)
        assert (ctx.banner, dict(ctx.decisions)) == once, _label(args)
