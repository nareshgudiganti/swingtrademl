"""Layer 2 prerequisite 2 (tv6): one brain TRADE idea, end to end, reaches the trial counters.

Path under test, with nothing but the broker faked: a live nightly brain run stores a TRADE idea ->
the practice (shadow) scan records it as an advisory BUY through the normal strategy path, ordering
nothing -> version 1's signal evaluator finishes it -> the go-live counter ("N of 30", the same number
the M18 stage switch and the Brain page show) goes up by one, and the trial journal (protocol 5a)
counts it as a finished brain TRADE idea. A WATCH idea on the same run reaches neither counter, and an
unfinished idea does not count yet. Counts only: the trial seal allows them.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from brain_m18_fixtures import DAY, at, brain_strategy, candle, decision, instrument, no_broker, run
from swing_trade_ml.brain.trial_journal import journal_for
from swing_trade_ml.core.enums import SignalType
from swing_trade_ml.db.models.trading import Order, Signal
from swing_trade_ml.ml.predict import evaluate_pending_signals
from swing_trade_ml.services import engine, execution
from swing_trade_ml.services.brain_golive import compare, shadow, stage
from swing_trade_ml.services.risk import RiskDecision
from swing_trade_ml.strategies import brain as brain_mod


@pytest.fixture()
def safe_scan(monkeypatch):
    no_broker(monkeypatch)
    monkeypatch.setattr(brain_mod, "today_ist", lambda: DAY)
    monkeypatch.setattr(engine, "_buy_slot_budget", lambda db, strategy, mode: 5)
    monkeypatch.setattr(execution, "portfolio_value_and_cash", lambda db, mode: (1_000_000.0, 1_000_000.0))
    monkeypatch.setattr(execution.risk, "check_entry", lambda **kw: RiskDecision(True, 10))


def _journal_counts(db) -> tuple[int, int, int]:
    j = journal_for(db, DAY, DAY)
    row = j["summaries"]["brain_trade"]
    return j["sessions"], row["picked"], row["ideas"]


def test_a_trade_idea_reaches_the_go_live_counter_and_the_trial_journal(db_session, safe_scan):
    trade = instrument(db_session, "TV6CNT", 918701)
    watch = instrument(db_session, "TV6WCH", 918702)
    for inst in (trade, watch):
        candle(db_session, inst, DAY, 101.0)
    strategy = brain_strategy(db_session, name="tv6-counter-brain", symbols=["TV6CNT", "TV6WCH"])
    run(db_session, "tv6-counter")
    decision(db_session, "tv6-counter", "TV6CNT", "TRADE")
    decision(db_session, "tv6-counter", "TV6WCH", "WATCH")

    before = compare.finished_brain_ideas(db_session)
    assert _journal_counts(db_session) == (1, 1, 0)  # the session and the pick are seen; nothing finished

    # 1. the practice scan records the TRADE as an advisory BUY and orders nothing
    result = shadow.run_brain_strategy(db_session)
    assert result.errors == [] and result.buys == 1
    buys = db_session.query(Signal).filter_by(strategy_id=strategy.id, signal_type=SignalType.BUY).all()
    assert [b.instrument_id for b in buys] == [trade.id]  # WATCH never becomes a buy idea
    (sig,) = buys
    assert sig.advisory_only and sig.outcome is None
    assert db_session.query(Order).filter_by(strategy_id=strategy.id).count() == 0
    # The scan stamps the wall clock; the test's day is in 2031, so put the stamp on that day's evening
    # (the shadow scan runs right after the 15:50 nightly run).
    sig.generated_at = at(DAY, 16, 0)
    db_session.flush()

    # 2. not finished yet: the counter has not moved
    assert compare.finished_brain_ideas(db_session) == before

    # 3. the market moves: +8% reached the next day (signal rule) and two days later (journal rule:
    #    entry at the next open, +8% from there)
    candle(db_session, trade, DAY + timedelta(days=1), 105.0, high=109.0, low=101.0)
    candle(db_session, trade, DAY + timedelta(days=2), 115.0, high=116.0, low=112.0)
    for n in (1, 2):
        candle(db_session, watch, DAY + timedelta(days=n), 101.0)
    evaluate_pending_signals(db_session, now=at(DAY + timedelta(days=3)))
    db_session.refresh(sig)
    assert sig.outcome == "TARGET_HIT"

    # 4. the go-live counter ("N of 30") goes up by exactly one, as placeable, not blocked
    assert compare.finished_brain_ideas(db_session) == before + 1
    overview = stage.stage_overview(db_session)
    assert overview["finished"] == before + 1 and overview["needed"] == compare.NEEDED_FINISHED

    # 5. the trial journal counts it as a finished brain TRADE idea (protocol 5a's "finished")
    assert _journal_counts(db_session) == (1, 1, 1)
    j = journal_for(db_session, DAY, DAY)
    assert j["gate"]["finished"] == 1 and j["gate"]["word"] == "too early"
    assert j["summaries"]["brain_blocked"]["picked"] == 0


def test_an_idea_from_a_replayed_run_never_reaches_the_counter(db_session, safe_scan):
    inst = instrument(db_session, "TV6RPL", 918703)
    candle(db_session, inst, DAY, 101.0)
    strategy = brain_strategy(db_session, name="tv6-replay-brain", symbols=["TV6RPL"])
    run(db_session, "tv6-replay", live=False)
    decision(db_session, "tv6-replay", "TV6RPL", "TRADE")
    result = shadow.run_brain_strategy(db_session)
    assert "no brain run today" in result.errors[0]
    assert db_session.query(Signal).filter_by(strategy_id=strategy.id).count() == 0
    assert journal_for(db_session, DAY, DAY)["sessions"] == 0
