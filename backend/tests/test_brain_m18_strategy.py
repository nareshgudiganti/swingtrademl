"""M18 task 1: the brain as a version-1 strategy reads today's stored decision."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import pytest

from brain_m18_fixtures import DAY, brain_strategy, decision, instrument, run
from swing_trade_ml.core.enums import SignalType
from swing_trade_ml.strategies import STRATEGY_REGISTRY, get_strategy
from swing_trade_ml.strategies import brain as brain_mod

DF = pd.DataFrame({"ts": [pd.Timestamp("2031-01-06")], "close": [101.0]})


@pytest.fixture()
def today(monkeypatch):
    monkeypatch.setattr(brain_mod, "today_ist", lambda: DAY)
    return DAY


def _evaluate(db, inst):
    return get_strategy(brain_strategy(db)).evaluate(DF, inst, db)


def test_brain_is_a_registered_strategy_that_needs_almost_no_history(db_session):
    assert STRATEGY_REGISTRY["brain"] is brain_mod.BrainStrategy
    assert get_strategy(brain_strategy(db_session)).min_bars_required() <= 5


def test_a_trade_idea_becomes_a_buy_with_the_brains_levels(db_session, today):
    inst = instrument(db_session, "M18AAA", 918001)
    run(db_session, "m18-r1")
    decision(db_session, "m18-r1", "M18AAA", "TRADE")
    d = _evaluate(db_session, inst)
    assert d.signal == SignalType.BUY
    assert (d.price, d.stop_loss, d.take_profit, d.horizon_days) == (101.0, 96.0, 108.0, 15)
    assert d.confidence == 0.62
    assert d.reason == "Strong trend with room to the target."
    assert d.features["brain_qty"] == 7  # informational only: v1 risk sizes the order


@pytest.mark.parametrize("word", ["TRADE", "WATCH", "WAIT", "AVOID"])
def test_the_strategy_returns_the_same_word_as_the_stored_decision(db_session, today, word):
    inst = instrument(db_session, "M18AAB", 918002)
    run(db_session, "m18-r2")
    decision(db_session, "m18-r2", "M18AAB", word, reasons=(f"Because {word}.",))
    d = _evaluate(db_session, inst)
    assert d.features["brain_word"] == word
    assert d.signal == (SignalType.BUY if word == "TRADE" else SignalType.HOLD)
    if word != "TRADE":
        assert d.reason == f"Because {word}."
        assert d.stop_loss is None and d.take_profit is None


def test_the_owners_overrule_wins(db_session, today):
    inst = instrument(db_session, "M18AAC", 918003)
    run(db_session, "m18-r3")
    decision(
        db_session, "m18-r3", "M18AAC", "TRADE", overruled_word="WATCH", overrule_reason="Results next week"
    )
    d = _evaluate(db_session, inst)
    assert d.signal == SignalType.HOLD
    assert d.features["brain_word"] == "WATCH"
    assert "Results next week" in d.reason


def test_an_idea_row_wins_over_a_holding_row_for_the_same_stock(db_session, today):
    inst = instrument(db_session, "M18AAD", 918004)
    run(db_session, "m18-r4")
    decision(db_session, "m18-r4", "M18AAD", "HOLD", kind="holding")
    decision(db_session, "m18-r4", "M18AAD", "TRADE")
    assert _evaluate(db_session, inst).signal == SignalType.BUY


def test_yesterdays_run_is_stale(db_session, today):
    inst = instrument(db_session, "M18AAE", 918005)
    run(db_session, "m18-r5", DAY - timedelta(days=1))
    decision(db_session, "m18-r5", "M18AAE", "TRADE")
    d = _evaluate(db_session, inst)
    assert (d.signal, d.reason) == (SignalType.HOLD, brain_mod.NO_RUN_TODAY)


@pytest.mark.parametrize(
    "kind,live,status,book",
    [
        ("nightly", False, "done", "paper"),  # a replay
        ("intraday", True, "done", "paper"),
        ("why", True, "done", "paper"),
        ("nightly", True, "failed", "paper"),
        ("nightly", True, "done", "live"),  # another book
    ],
)
def test_only_a_finished_live_nightly_run_of_the_same_book_counts(
    db_session, today, kind, live, status, book
):
    inst = instrument(db_session, "M18AAF", 918006)
    run_id = f"m18-r6-{kind}-{live}-{status}-{book}"
    run(db_session, run_id, kind=kind, live=live, status=status, book=book)
    decision(db_session, run_id, "M18AAF", "TRADE")
    assert _evaluate(db_session, inst).reason == brain_mod.NO_RUN_TODAY


def test_the_latest_nightly_run_of_the_day_wins(db_session, today):
    inst = instrument(db_session, "M18AAG", 918007)
    run(db_session, "m18-r7a", hh=15, mm=50)
    decision(db_session, "m18-r7a", "M18AAG", "TRADE")
    run(db_session, "m18-r7b", hh=18, mm=0)
    decision(db_session, "m18-r7b", "M18AAG", "WAIT", reasons=("Market turned careful.",))
    d = _evaluate(db_session, inst)
    assert d.signal == SignalType.HOLD and d.features["brain_run_id"] == "m18-r7b"


def test_a_stock_the_brain_did_not_look_at_is_held(db_session, today):
    inst = instrument(db_session, "M18AAH", 918008)
    run(db_session, "m18-r8")
    assert _evaluate(db_session, inst).reason == brain_mod.NOT_LOOKED_AT


def test_a_trade_without_stop_or_target_is_held(db_session, today):
    inst = instrument(db_session, "M18AAI", 918009)
    run(db_session, "m18-r9")
    decision(db_session, "m18-r9", "M18AAI", "TRADE", stop=None)
    d = _evaluate(db_session, inst)
    assert (d.signal, d.reason) == (SignalType.HOLD, brain_mod.NO_LEVELS)


def test_decisions_are_read_once_per_scan(db_session, today, monkeypatch):
    calls = []
    real = brain_mod.todays_decisions
    monkeypatch.setattr(brain_mod, "todays_decisions", lambda *a: calls.append(a) or real(*a))
    impl = get_strategy(brain_strategy(db_session))
    a = instrument(db_session, "M18AAJ", 918010)
    b = instrument(db_session, "M18AAK", 918011)
    run(db_session, "m18-r10")
    impl.evaluate(DF, a, db_session)
    impl.evaluate(DF, b, db_session)
    assert len(calls) == 1
