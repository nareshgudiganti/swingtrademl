"""An owner's overrule survives a same-day rerun of the brain.

"Run the brain now" stores a new live run, which becomes today's run for the
M18 strategy and for approvals. Without carrying the overrule forward, a stock
the owner overruled TRADE -> AVOID would read TRADE again and could be bought.
Overrules only ever move toward caution, and never carry across days.
"""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import pytest
from sqlalchemy import select

from brain_m18_fixtures import DAY, at, brain_strategy, decision, instrument, run
from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain import service
from swing_trade_ml.brain.context import BrainContext
from swing_trade_ml.brain.module import REGISTRY
from swing_trade_ml.core.enums import SignalType
from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
from swing_trade_ml.strategies import brain as brain_mod
from swing_trade_ml.strategies import get_strategy

DF = pd.DataFrame({"ts": [pd.Timestamp("2031-01-06")], "close": [101.0]})


def _store_rerun(db, run_id, decisions, *, day=DAY, hh=16, mm=30, kind="nightly", live=True):
    """Store a run exactly as run_brain does, at a fixed IST time."""
    request = c.RunRequest(run_id=run_id, kind=kind, as_of=at(day, hh, mm), universe=(), live=live)
    ctx = BrainContext(request=request, reader=None)
    ctx.banner = c.Banner(mode=c.MarketMode.NORMAL, headline="ok")
    for d in decisions:
        ctx.decisions[d.symbol] = d
    service._store(db, ctx, REGISTRY, {}, 1)
    db.flush()
    db.get(BrainRun, run_id).started_at = at(day, hh, mm)  # a real rerun starts after the first
    db.flush()


def _idea(symbol, word="TRADE"):
    return c.Decision(
        symbol=symbol,
        kind="idea",
        word=c.IdeaWord(word),
        reasons=("Strong trend.",),
        stop=96.0,
        target=108.0,
        qty=5,
    )


def _holding(symbol, word="HOLD"):
    return c.Decision(symbol=symbol, kind="holding", word=c.HoldingWord(word), reasons=("Fine.",))


def _row(db, run_id, symbol, kind="idea") -> BrainDecision:
    return db.execute(
        select(BrainDecision).where(
            BrainDecision.run_id == run_id, BrainDecision.symbol == symbol, BrainDecision.kind == kind
        )
    ).scalar_one()


def _overruled_earlier(db, run_id, symbol, word, new_word, *, kind="idea", day=DAY):
    run(db, run_id, day)
    first = decision(db, run_id, symbol, word, kind=kind)
    service.overrule(db, first.id, new_word, "Results next week", "owner")
    return first


def test_a_same_day_rerun_keeps_the_owners_trade_to_avoid_overrule(db_session):
    first = _overruled_earlier(db_session, "carry-r1a", "CARRYA", "TRADE", "AVOID")
    _store_rerun(db_session, "carry-r1b", [_idea("CARRYA", "TRADE")])
    row = _row(db_session, "carry-r1b", "CARRYA")
    assert row.word == "TRADE"  # the brain's own word is kept
    assert row.overruled_word == "AVOID"
    assert row.overrule_reason == "Results next week"
    assert row.overruled_by == "owner"
    assert row.overruled_at == first.overruled_at


def test_after_a_rerun_the_brain_strategy_does_not_buy_the_overruled_stock(db_session, monkeypatch):
    monkeypatch.setattr(brain_mod, "today_ist", lambda: DAY)
    inst = instrument(db_session, "CARRYB", 931002)
    _overruled_earlier(db_session, "carry-r2a", "CARRYB", "TRADE", "AVOID")
    _store_rerun(db_session, "carry-r2b", [_idea("CARRYB", "TRADE")])
    assert brain_mod.todays_run(db_session, DAY, "paper").id == "carry-r2b"  # the rerun is today's run
    d = get_strategy(brain_strategy(db_session)).evaluate(DF, inst, db_session)
    assert d.signal != SignalType.BUY
    assert d.features["brain_word"] == "AVOID"


def test_an_overrule_from_yesterday_does_not_carry(db_session):
    _overruled_earlier(db_session, "carry-r3a", "CARRYC", "TRADE", "AVOID", day=DAY - timedelta(days=1))
    _store_rerun(db_session, "carry-r3b", [_idea("CARRYC", "TRADE")])
    assert _row(db_session, "carry-r3b", "CARRYC").overruled_word is None


@pytest.mark.parametrize(
    ("kind", "old", "overruled", "new"),
    [
        ("idea", "TRADE", "WATCH", "AVOID"),
        ("idea", "TRADE", "AVOID", "AVOID"),
        ("holding", "HOLD", "REDUCE", "EXIT"),
    ],
)
def test_a_rerun_already_as_careful_is_left_alone(db_session, kind, old, overruled, new):
    _overruled_earlier(db_session, "carry-r4a", "CARRYD", old, overruled, kind=kind)
    fresh = _idea("CARRYD", new) if kind == "idea" else _holding("CARRYD", new)
    _store_rerun(db_session, "carry-r4b", [fresh])
    row = _row(db_session, "carry-r4b", "CARRYD", kind)
    assert row.word == new
    assert row.overruled_word is None


def test_a_holding_hold_to_reduce_overrule_carries(db_session):
    _overruled_earlier(db_session, "carry-r5a", "CARRYE", "HOLD", "REDUCE", kind="holding")
    _store_rerun(db_session, "carry-r5b", [_holding("CARRYE", "HOLD")], kind="intraday")
    row = _row(db_session, "carry-r5b", "CARRYE", "holding")
    assert (row.word, row.overruled_word) == ("HOLD", "REDUCE")


def test_a_replay_does_not_pick_up_todays_overrule(db_session):
    _overruled_earlier(db_session, "carry-r6a", "CARRYF", "TRADE", "AVOID")
    _store_rerun(db_session, "carry-r6b", [_idea("CARRYF", "TRADE")], live=False)
    assert _row(db_session, "carry-r6b", "CARRYF").overruled_word is None
