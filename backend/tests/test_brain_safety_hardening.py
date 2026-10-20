"""ps Wave 0 (owner approved 2026-10-20): the four "bolder on bad data" fixes, each pinned directly.

1. No market judge → the state fallback is never NORMAL; no breadth as well → NO NEW TRADES.
2. A TRADE needs 0 < stop < entry <= entry high < target, all real numbers, and a size inside the risk
   gate's approval (constitution C12); the order approval step applies the same rule again.
3. An opinion with a probability or buy level outside 0..1 (NaN included) is refused.
4. A NaN model score in the decide fallback is "no usable score" → WAIT.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from brain_fakes import FakeReader, allow_all_risk_gate, fresh_quality, make_module, registry, request
from swing_trade_ml.brain import constitution
from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.contracts import IdeaWord, MarketMode
from swing_trade_ml.brain.module import Step
from swing_trade_ml.brain.runner import execute


class BreadthReader(FakeReader):
    def __init__(self, breadth: pd.Series | Exception | None = None, **kw) -> None:
        super().__init__(**kw)
        self._breadth = breadth

    def breadth_series(self) -> pd.Series:
        if isinstance(self._breadth, Exception):
            raise self._breadth
        return self._breadth if self._breadth is not None else pd.Series(dtype=float)


def _run(reader, *classes):
    return execute(request(), reader, registry(*classes), modes={})


# 1. market backup ------------------------------------------------------------------------


@pytest.mark.parametrize("breadth", [None, RuntimeError("feed down"), pd.Series([0.5, float("nan")])])
def test_no_judge_and_no_breadth_means_no_new_trades(breadth):
    ctx = _run(BreadthReader(breadth=breadth))  # calm rising NIFTY: the old backup said NORMAL
    assert ctx.market.mode is MarketMode.NO_NEW_TRADES
    assert ctx.banner.mode is MarketMode.NO_NEW_TRADES


@pytest.mark.parametrize("share", [0.0, 0.9])
def test_no_judge_with_breadth_is_defensive_never_normal(share):
    ctx = _run(BreadthReader(breadth=pd.Series([share])))
    assert ctx.market.mode is MarketMode.DEFENSIVE
    assert ctx.market.breadth_pct == share
    assert "did not answer" in ctx.market.reasons[0]


# 2. the trade plan ------------------------------------------------------------------------

GOOD = {"entry_low": 100.0, "entry_high": 101.0, "stop": 96.0, "target": 108.0}


def _trade_module(**plan):
    def run(view):
        levels = {**GOOD, **plan}
        qty = levels.pop("qty", 10)
        return c.Contribution(
            decisions=(
                c.Decision(
                    symbol="ABC", kind="idea", word=IdeaWord.TRADE, reasons=("Test plan.",), qty=qty, **levels
                ),
            )
        )

    return make_module("M08", Step.DECIDE, writes=("Decision@1", "Banner@1"), run=run)


def _likes_abc():
    def run(view):
        return c.Contribution(
            opinions=(
                c.Opinion(source="model", symbol="ABC", stance=0.8, confidence=0.8, reasons=("Liked.",)),
            )
        )

    return make_module("M90", Step.REASON, writes=("Opinion@1",), run=run, kind="plugin")


class _Judge:
    """A working market judge (NORMAL), so only the plan decides the outcome."""

    @staticmethod
    def module():
        def run(view):
            return c.Contribution(market=c.MarketState(mode=MarketMode.NORMAL, reasons=("Calm.",)))

        return make_module("M10", Step.STATE, writes=("MarketState@1",), run=run)


def _plan_run(**plan):
    ctx = _run(
        BreadthReader(breadth=pd.Series([0.6])),
        fresh_quality(),
        _Judge.module(),
        _likes_abc(),
        allow_all_risk_gate(max_qty=10),
        _trade_module(**plan),
    )
    return ctx.decisions["ABC"]


def test_a_good_plan_stays_a_trade():
    d = _plan_run()
    assert d.word is IdeaWord.TRADE and d.qty == 10


@pytest.mark.parametrize(
    "plan",
    [
        {"stop": math.nan},
        {"target": math.inf},
        {"entry_low": None},
        {"stop": 0.0},
        {"stop": -1.0},
        {"stop": 100.5},  # stop inside the buy range
        {"target": 99.0},  # target below the buy price
        {"entry_low": 102.0},  # buy range upside down
        {"qty": -5},
    ],
)
def test_a_trade_without_a_usable_plan_becomes_wait(plan):
    d = _plan_run(**plan)
    assert d.word is IdeaWord.WAIT and d.qty == 0
    assert d.downgrade_reason == constitution.BAD_PLAN


def test_a_size_above_the_risk_gate_is_lowered_to_it():
    d = _plan_run(qty=10**9)
    assert d.word is IdeaWord.TRADE and d.qty == 10
    assert "10 shares the risk gate approved" in d.reasons[-1]


@pytest.mark.parametrize("bad", [None, math.nan, math.inf, "96", True])
def test_plan_check_refuses_anything_but_real_numbers(bad):
    assert not constitution.plan_is_usable(bad, 100.0, 101.0, 108.0)


def test_plan_check_accepts_stored_decimals():
    from decimal import Decimal

    assert constitution.plan_is_usable(Decimal("96"), Decimal("100"), Decimal("101"), Decimal("108"))


# 3. probability range ---------------------------------------------------------------------


@pytest.mark.parametrize("field,value", [("probability", 7.0), ("probability", math.nan), ("threshold", 1.5)])
def test_an_opinion_outside_0_to_1_is_refused(field, value):
    o = c.Opinion(source="m", symbol="ABC", stance=0.5, confidence=0.5, reasons=("x",), **{field: value})
    with pytest.raises(c.ContractError, match=r"outside 0..1"):
        c.validate_record(o)


def test_an_opinion_inside_0_to_1_is_accepted():
    c.validate_record(
        c.Opinion(
            source="m",
            symbol="ABC",
            stance=0.5,
            confidence=0.5,
            reasons=("x",),
            probability=0.7,
            threshold=0.6,
        )
    )


# 4. NaN score in the decide fallback ---------------------------------------------------------


def test_a_nan_model_score_in_the_decide_fallback_is_wait():
    ctx = _run(
        BreadthReader(breadth=pd.Series([0.6]), probabilities={"ABC": math.nan, "XYZ": 0.3}),
        fresh_quality(),
        _Judge.module(),
        allow_all_risk_gate(),
    )
    d = ctx.decisions["ABC"]
    assert d.word is IdeaWord.WAIT
    assert "not a usable number" in d.reasons[0]
