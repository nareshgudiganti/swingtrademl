"""Practice brain ideas refused by v1 risk limits are kept as labelled evidence,
counted separately from ideas that could really have been placed. v1 and every
real order path are unchanged."""

from __future__ import annotations

from datetime import timedelta

from brain_m18_fixtures import DAY, at, brain_strategy, candle, instrument, no_broker, v1_strategy
from swing_trade_ml.core.enums import SignalType
from swing_trade_ml.db.models.brain_golive import BrainStageChange
from swing_trade_ml.db.models.safety import RiskEvent
from swing_trade_ml.db.models.trading import Order, Signal
from swing_trade_ml.ml.predict import evaluate_pending_signals
from swing_trade_ml.services import execution
from swing_trade_ml.services.brain_golive import compare, stage
from swing_trade_ml.services.risk import RiskDecision
from swing_trade_ml.strategies.base import SignalDecision

BUY = SignalDecision(SignalType.BUY, 100.0, 0.6, "r", stop_loss=96.0, take_profit=108.0, horizon_days=15)


def _setup(monkeypatch):
    no_broker(monkeypatch)
    monkeypatch.setattr(execution, "portfolio_value_and_cash", lambda db, mode: (1_000_000.0, 1_000_000.0))
    monkeypatch.setattr(
        execution.risk,
        "check_entry",
        lambda **kw: RiskDecision(False, 0, "Market stressed, cap full", rule="DEPLOYABLE"),
    )


def test_stress_cap_block_is_tagged_scored_and_not_a_risk_event(db_session, monkeypatch):
    _setup(monkeypatch)
    strategy = brain_strategy(db_session, name="blk-brain")
    inst = instrument(db_session, "BLKA", 919001)
    sig = execution.process_decision(db_session, strategy, inst, BUY)
    assert sig.features[execution.BLOCKED_BY_RISK_KEY] == "DEPLOYABLE"
    assert sig.rejection_reason.startswith(execution.BLOCKED_BY_RISK_PREFIX)
    assert not sig.was_executed
    assert db_session.query(Order).filter_by(strategy_id=strategy.id).count() == 0
    assert db_session.query(RiskEvent).filter_by(strategy_id=strategy.id).count() == 0
    # still has stop/target/horizon, so v1's scorer finishes it
    sig.generated_at = at(DAY)
    candle(db_session, inst, DAY + timedelta(days=1), 105.0, high=109.0, low=101.0)
    db_session.flush()
    evaluate_pending_signals(db_session, now=at(DAY + timedelta(days=3)))
    db_session.refresh(sig)
    assert sig.outcome == "TARGET_HIT"


def test_slot_block_is_tagged_for_practice_brain(db_session, monkeypatch):
    _setup(monkeypatch)
    strategy = brain_strategy(db_session, name="blk-brain-slots")
    inst = instrument(db_session, "BLKB", 919002)
    sig = execution.process_decision(db_session, strategy, inst, BUY, ranked_out_reason="no slots")
    assert sig.features[execution.BLOCKED_BY_RISK_KEY] == "SLOTS"


def test_non_practice_and_v1_are_unchanged(db_session, monkeypatch):
    _setup(monkeypatch)
    v1 = v1_strategy(db_session, name="blk-v1")
    inst = instrument(db_session, "BLKC", 919003)
    sig = execution.process_decision(db_session, v1, inst, BUY)
    assert sig.rejection_reason == "Market stressed, cap full"
    assert execution.BLOCKED_BY_RISK_KEY not in (sig.features or {})
    assert db_session.query(RiskEvent).filter_by(strategy_id=v1.id).count() == 1
    slot = execution.process_decision(db_session, v1, inst, BUY, ranked_out_reason="no slots")
    assert slot.rejection_reason == "no slots" and execution.BLOCKED_BY_RISK_KEY not in (slot.features or {})

    # brain once the approval stage is live: real refusal, risk event, no tag
    db_session.add(BrainStageChange(stage="approval", previous_stage="shadow", changed_by="t", reason="t"))
    db_session.flush()
    brain = brain_strategy(db_session, name="blk-brain-live")
    inst2 = instrument(db_session, "BLKD", 919004)
    s2 = execution.process_decision(db_session, brain, inst2, BUY)
    assert s2.rejection_reason == "Market stressed, cap full"
    assert execution.BLOCKED_BY_RISK_KEY not in (s2.features or {})
    assert db_session.query(RiskEvent).filter_by(strategy_id=brain.id).count() == 1


def _finished_idea(db, strategy, inst, blocked):
    db.add(
        Signal(
            strategy_id=strategy.id, instrument_id=inst.id, signal_type=SignalType.BUY, mode="paper",
            price=100.0, stop_loss=96.0, take_profit=108.0, horizon_days=15, generated_at=at(DAY),
            features={execution.BLOCKED_BY_RISK_KEY: "DEPLOYABLE"} if blocked else {},
            outcome="TARGET_HIT", outcome_pct=0.08,
        )
    )
    db.flush()


def test_gate_counts_placeable_only_and_shows_blocked_separately(db_session):
    strategy = brain_strategy(db_session, name="cnt-brain")
    base = compare.finished_brain_ideas(db_session)
    blocked0 = compare.finished_blocked_brain_ideas(db_session)
    _finished_idea(db_session, strategy, instrument(db_session, "CNTA", 919011), blocked=False)
    _finished_idea(db_session, strategy, instrument(db_session, "CNTB", 919012), blocked=True)
    _finished_idea(db_session, strategy, instrument(db_session, "CNTC", 919013), blocked=True)
    assert compare.finished_brain_ideas(db_session) == base + 1
    assert compare.finished_blocked_brain_ideas(db_session) == blocked0 + 2
    overview = stage.stage_overview(db_session)
    assert overview["finished"] == base + 1 and overview["finished_blocked"] == blocked0 + 2
    rep = compare.report(db_session)
    assert rep["brain_finished_blocked"] == blocked0 + 2
    assert rep["brain_finished_placeable"] == base + 1
