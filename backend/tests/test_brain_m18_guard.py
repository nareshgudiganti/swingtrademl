"""M18 task 2: the brain is always advisory in the scan path; version 1 is
unchanged when it is switched on; positions the owner approved get v1's real
exits. No test here can reach a broker."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from brain_m18_fixtures import brain_strategy, instrument, no_broker, v1_strategy
from swing_trade_ml.core import strategy_policy as policy
from swing_trade_ml.core.enums import ExitReason, PositionStatus, SignalType
from swing_trade_ml.db.models.brain_golive import BrainStageChange
from swing_trade_ml.db.models.safety import RiskEvent
from swing_trade_ml.db.models.trading import Order, Position, Strategy
from swing_trade_ml.services import engine, execution, risk
from swing_trade_ml.services.risk import RiskDecision
from swing_trade_ml.strategies.base import SignalDecision

HEADERS = {"X-API-Key": "test-api-key"}
BUY = SignalDecision(SignalType.BUY, 100.0, 0.6, "r", stop_loss=96.0, take_profit=108.0, horizon_days=15)


def _row(strategy_type: str, execution_mode: str = "advisory"):
    return SimpleNamespace(strategy_type=strategy_type, execution_mode=execution_mode)


def test_the_brain_is_advisory_in_the_scan_path_even_if_its_row_says_auto():
    assert policy.requires_advisory("brain") is True
    assert policy.is_advisory(_row("brain", "auto")) is True


def test_only_long_term_value_is_refused_by_the_order_path():
    policy.require_broker_execution(_row("brain"))  # approvals may order for it
    with pytest.raises(ValueError, match="Long-term"):
        policy.require_broker_execution(_row("long_term_value"))


def test_exits_of_an_approved_brain_position_are_real_sells():
    assert policy.exits_are_advisory(_row("brain")) is False
    assert policy.exits_are_advisory(_row("long_term_value")) is True
    assert policy.exits_are_advisory(_row("ml_swing", "advisory")) is True
    assert policy.exits_are_advisory(_row("ml_swing", "auto")) is False


def test_the_brain_strategy_cannot_be_switched_to_auto_through_the_strategies_api(client):
    r = client.post(
        "/api/v1/strategies", json={"name": "m18-api-brain", "strategy_type": "brain"}, headers=HEADERS
    )
    assert r.status_code == 201 and r.json()["execution_mode"] == "advisory"
    r2 = client.patch(
        f"/api/v1/strategies/{r.json()['id']}", json={"execution_mode": "auto"}, headers=HEADERS
    )
    assert r2.status_code == 422 and "Brain page" in r2.json()["detail"]
    r3 = client.post(
        "/api/v1/strategies",
        json={"name": "m18-api-brain2", "strategy_type": "brain", "execution_mode": "auto"},
        headers=HEADERS,
    )
    assert r3.status_code == 422


def _allow_everything(monkeypatch) -> list[str]:
    no_broker(monkeypatch)
    sent: list[str] = []
    monkeypatch.setattr(
        execution.notifier, "send_sync", lambda text, event="system": sent.append(text) or True
    )
    monkeypatch.setattr(execution, "portfolio_value_and_cash", lambda db, mode: (1_000_000.0, 1_000_000.0))
    monkeypatch.setattr(execution.risk, "check_entry", lambda **kw: RiskDecision(True, 10))
    return sent


def test_a_shadow_brain_buy_never_creates_an_order(db_session, monkeypatch):
    sent = _allow_everything(monkeypatch)
    strategy = brain_strategy(db_session)
    inst = instrument(db_session, "M18GRD", 918101)
    sig = execution.process_decision(db_session, strategy, inst, BUY)
    assert sig.advisory_only is True and sig.rejection_reason is None and sig.was_executed is False
    assert db_session.query(Order).filter_by(strategy_id=strategy.id).count() == 0
    assert db_session.query(Position).filter_by(strategy_id=strategy.id).count() == 0
    assert sent == []  # practice ideas are never announced as recommendations


def test_an_advisory_v1_buy_is_still_announced(db_session, monkeypatch):
    sent = _allow_everything(monkeypatch)
    strategy = v1_strategy(db_session, name="m18-adv-v1", execution_mode="advisory")
    inst = instrument(db_session, "M18GRE", 918102)
    execution.process_decision(db_session, strategy, inst, BUY)
    assert len(sent) == 1


def test_the_daily_scan_never_runs_the_brain_strategy(db_session, monkeypatch):
    brain_strategy(db_session, name="m18-scan-brain")
    v1_strategy(db_session, name="m18-scan-v1")
    ran: list[str] = []
    monkeypatch.setattr(
        engine,
        "run_strategy",
        lambda db, s, interval="day": ran.append(s.strategy_type) or engine.ScanResult(strategies_run=1),
    )
    engine.run_all_active(db_session)
    assert "brain" not in ran and "ml_swing" in ran


def _hold(db, strategy, symbol: str, token: int) -> None:
    inst = instrument(db, symbol, token)
    db.add(
        Position(
            strategy_id=strategy.id,
            instrument_id=inst.id,
            mode="paper",
            status=PositionStatus.OPEN,
            quantity=1,
            initial_quantity=1,
            entry_price=100.0,
            entry_at=datetime.now(UTC),
            stop_loss=96.0,
            initial_stop_loss=96.0,
            take_profit=108.0,
            highest_price=100.0,
            current_price=100.0,
            total_charges=0.0,
        )
    )
    db.flush()


def _entry(db, strategy, inst) -> RiskDecision:
    return risk.check_entry(
        db=db,
        mode="paper",
        instrument_id=inst.id,
        price=100.0,
        stop_loss=96.0,
        portfolio_value=1_000_000.0,
        available_cash=1_000_000.0,
        strategy=strategy,
    )


def test_the_brain_gets_a_slot_share_and_version_1_keeps_its_own(db_session, monkeypatch):
    """1 version-1 strategy, 5 slots account-wide: the brain may hold
    5 // (1 + 1) = 2, so its morning buys can never fill every slot before
    version 1's 15:45 scan; version 1 keeps its full share up to the account cap."""
    real = risk.limits_for
    monkeypatch.setattr(risk, "limits_for", lambda value, s=None: replace(real(value, s), max_positions=5))
    db_session.query(Strategy).filter(Strategy.mode == "paper").update({"is_active": False})
    v1 = v1_strategy(db_session, name="m18-share-v1")
    brain = brain_strategy(db_session, name="m18-share-brain")
    _hold(db_session, brain, "M18SH1", 918201)
    _hold(db_session, brain, "M18SH2", 918202)
    refused = _entry(db_session, brain, instrument(db_session, "M18SH3", 918203))
    assert not refused.allowed and refused.rule == "POSITION_LIMIT"
    assert "2 of its 2 positions" in refused.reason
    _hold(db_session, v1, "M18SH4", 918204)
    _hold(db_session, v1, "M18SH5", 918205)
    assert _entry(db_session, v1, instrument(db_session, "M18SH6", 918206)).rule != "POSITION_LIMIT"
    _hold(db_session, v1, "M18SH7", 918207)
    full = _entry(db_session, v1, instrument(db_session, "M18SH8", 918208))
    assert not full.allowed and full.rule == "POSITION_LIMIT"
    assert "You already hold 5 positions" in full.reason


def test_an_active_brain_strategy_does_not_shrink_version_1s_slot_share(db_session, monkeypatch):
    real = risk.limits_for
    monkeypatch.setattr(risk, "limits_for", lambda value, s=None: replace(real(value, s), max_positions=4))
    db_session.query(Strategy).filter(Strategy.mode == "paper").update({"is_active": False})
    v1 = v1_strategy(db_session, name="m18-share-v1b")
    brain_strategy(db_session, name="m18-share-brain-b")
    for i in range(3):
        _hold(db_session, v1, f"M18SV{i}", 918210 + i)
    # With the brain switched on, version 1 alone may still take every slot.
    assert _entry(db_session, v1, instrument(db_session, "M18SV9", 918219)).rule != "POSITION_LIMIT"


def test_an_approved_brain_position_at_its_stop_is_sold_by_version_1(db_session, monkeypatch):
    strategy = brain_strategy(db_session, name="m18-exit-brain")
    inst = instrument(db_session, "M18GRF", 918103)
    pos = Position(
        strategy_id=strategy.id,
        instrument_id=inst.id,
        mode="paper",
        status=PositionStatus.OPEN,
        quantity=10,
        initial_quantity=10,
        entry_price=100.0,
        entry_at=datetime.now(UTC),
        stop_loss=96.0,
        initial_stop_loss=96.0,
        take_profit=108.0,
        highest_price=100.0,
        current_price=100.0,
        total_charges=0.0,
    )
    db_session.add(pos)
    db_session.flush()
    fake = no_broker(monkeypatch)
    fake.get_ltp = lambda keys, db: {inst.symbol_key: 95.0}
    closed = []
    monkeypatch.setattr(
        execution,
        "close_position",
        lambda db, p, price, reason, note=None, quantity=None: closed.append((p.id, reason)),
    )
    monkeypatch.setattr(execution, "_claim_exit", lambda db, p: True)
    monkeypatch.setattr(execution, "_release_exit", lambda db, p: None)
    execution.check_exits(db_session)
    assert closed == [(pos.id, ExitReason.STOP_LOSS_HIT)]


# --- Fix round 1: a position is only ever sold through the broker of its own book.


def _open_position(db, strategy, inst, mode: str = "paper") -> Position:
    pos = Position(
        strategy_id=strategy.id,
        instrument_id=inst.id,
        mode=mode,
        status=PositionStatus.OPEN,
        quantity=10,
        initial_quantity=10,
        entry_price=100.0,
        entry_at=datetime.now(UTC),
        stop_loss=96.0,
        initial_stop_loss=96.0,
        take_profit=108.0,
        highest_price=100.0,
        current_price=100.0,
        total_charges=0.0,
    )
    db.add(pos)
    db.flush()
    return pos


def _watch_exits(monkeypatch, broker_mode: str, prices: dict[str, float]):
    fake = no_broker(monkeypatch)
    fake.mode = broker_mode
    fake.get_ltp = lambda keys, db: {k: v for k, v in prices.items() if k in keys}
    closed: list = []
    sent: list[str] = []
    monkeypatch.setattr(
        execution,
        "close_position",
        lambda db, p, price, reason, note=None, quantity=None: closed.append((p.id, reason, quantity)),
    )
    monkeypatch.setattr(execution, "_claim_exit", lambda db, p: True)
    monkeypatch.setattr(execution, "_release_exit", lambda db, p: None)
    monkeypatch.setattr(
        execution.notifier, "send_sync", lambda text, event="system": sent.append(text) or True
    )
    return closed, sent


def test_a_paper_brain_position_at_its_stop_is_not_sold_while_the_bot_is_live(db_session, monkeypatch):
    strategy = brain_strategy(db_session, name="m18-book-brain")
    inst = instrument(db_session, "M18GRG", 918104)
    pos = _open_position(db_session, strategy, inst, mode="paper")
    closed, sent = _watch_exits(monkeypatch, "live", {inst.symbol_key: 95.0})
    execution.check_exits(db_session)
    execution.check_exits(db_session)  # alerts once, not every minute
    assert closed == []
    assert len(sent) == 1 and "paper book" in sent[0] and "live mode" in sent[0]
    assert pos.advisory_alert_sent_at is not None


def test_a_paper_brain_position_is_not_partly_sold_while_the_bot_is_live(db_session, monkeypatch):
    strategy = brain_strategy(db_session, name="m18-book-brain-half")
    inst = instrument(db_session, "M18GRH", 918105)
    _open_position(db_session, strategy, inst, mode="paper")
    closed, sent = _watch_exits(monkeypatch, "live", {inst.symbol_key: 106.0})
    monkeypatch.setattr(execution, "scale_out_quantity", lambda policy, **kw: 5)  # half-out is due
    execution.check_exits(db_session)
    assert closed == [] and sent == []


def test_version_1_positions_exit_exactly_as_before(db_session, monkeypatch):
    auto = v1_strategy(db_session, name="m18-book-v1-auto")
    adv = v1_strategy(db_session, name="m18-book-v1-adv", execution_mode="advisory")
    i1 = instrument(db_session, "M18GRI", 918106)
    i2 = instrument(db_session, "M18GRJ", 918107)
    p_auto = _open_position(db_session, auto, i1, mode="paper")
    p_adv = _open_position(db_session, adv, i2, mode="paper")
    closed, sent = _watch_exits(monkeypatch, "paper", {i1.symbol_key: 95.0, i2.symbol_key: 95.0})
    execution.check_exits(db_session)
    assert closed == [(p_auto.id, ExitReason.STOP_LOSS_HIT, None)]
    assert len(sent) == 1 and "book" not in sent[0]  # the advisory one: plain alert, as before
    assert p_adv.advisory_alert_sent_at is not None


def test_a_version_1_auto_paper_position_is_left_alone_while_the_bot_is_live(db_session, monkeypatch):
    auto = v1_strategy(db_session, name="m18-book-v1-auto-live")
    inst = instrument(db_session, "M18GRK", 918108)
    _open_position(db_session, auto, inst, mode="paper")
    closed, sent = _watch_exits(monkeypatch, "live", {inst.symbol_key: 95.0})
    execution.check_exits(db_session)
    assert closed == [] and sent == []


EXIT = SignalDecision(SignalType.EXIT, 95.0, 0.7, "The brain no longer likes this stock.")


def test_a_brain_exit_decision_sells_an_approved_position_in_its_own_book(db_session, monkeypatch):
    strategy = brain_strategy(db_session, name="m18-exit-decision")
    inst = instrument(db_session, "M18GRL", 918109)
    pos = _open_position(db_session, strategy, inst, mode="paper")
    closed, sent = _watch_exits(monkeypatch, "paper", {})
    sig = execution.process_decision(db_session, strategy, inst, EXIT)
    assert closed == [(pos.id, ExitReason.SIGNAL_EXIT, None)]
    assert sent == [] and sig.advisory_only is False


def test_a_brain_exit_decision_only_alerts_when_the_bot_is_in_the_other_mode(db_session, monkeypatch):
    strategy = brain_strategy(db_session, name="m18-exit-decision-live")
    inst = instrument(db_session, "M18GRM", 918110)
    _open_position(db_session, strategy, inst, mode="paper")
    closed, sent = _watch_exits(monkeypatch, "live", {})
    sig = execution.process_decision(db_session, strategy, inst, EXIT)
    assert closed == []
    assert len(sent) == 1 and "paper book" in sent[0] and "live mode" in sent[0]
    assert sig.advisory_only is True and sig.was_executed is False


def test_a_brain_buy_never_runs_the_confidence_decay_check(db_session, monkeypatch):
    """The brain's confidence is not always a probability, so version 1's
    decay alert must not read it (to_signal strips it on a HOLD likewise)."""
    _allow_everything(monkeypatch)
    calls: list[int] = []
    monkeypatch.setattr(execution, "_check_confidence_decay", lambda db, p, *a: calls.append(p.id))
    strategy = brain_strategy(db_session, name="m18-decay-brain")
    _hold(db_session, strategy, "M18DCY", 918301)
    inst = db_session.query(Position).filter_by(strategy_id=strategy.id).one().instrument
    execution.process_decision(db_session, strategy, inst, BUY)
    assert calls == []
    v1 = v1_strategy(db_session, name="m18-decay-v1")
    _hold(db_session, v1, "M18DCZ", 918302)
    v1_inst = db_session.query(Position).filter_by(strategy_id=v1.id).one().instrument
    execution.process_decision(db_session, v1, v1_inst, BUY)
    assert len(calls) == 1  # version 1 is unchanged


def _refuse(monkeypatch) -> None:
    _allow_everything(monkeypatch)
    monkeypatch.setattr(
        execution.risk,
        "check_entry",
        lambda **kw: RiskDecision(False, 0, "Sector limit reached", rule="SECTOR_CAP"),
    )


def test_a_practice_brain_idea_refused_by_the_safety_check_writes_no_risk_event(db_session, monkeypatch):
    _refuse(monkeypatch)
    strategy = brain_strategy(db_session, name="m18-noise-brain")
    inst = instrument(db_session, "M18NOI", 918311)
    sig = execution.process_decision(db_session, strategy, inst, BUY)
    assert sig.rejection_reason == "Sector limit reached"  # the reason is still on the idea
    assert db_session.query(RiskEvent).filter_by(strategy_id=strategy.id).count() == 0


def test_once_the_brain_can_buy_its_refusals_are_risk_events_again(db_session, monkeypatch):
    _refuse(monkeypatch)
    db_session.add(BrainStageChange(stage="approval", previous_stage="shadow", changed_by="t", reason="t"))
    db_session.flush()
    strategy = brain_strategy(db_session, name="m18-noise-brain2")
    inst = instrument(db_session, "M18NOJ", 918312)
    execution.process_decision(db_session, strategy, inst, BUY)
    assert db_session.query(RiskEvent).filter_by(strategy_id=strategy.id).count() == 1


def test_a_version_1_refusal_is_still_a_risk_event(db_session, monkeypatch):
    _refuse(monkeypatch)
    strategy = v1_strategy(db_session, name="m18-noise-v1")
    inst = instrument(db_session, "M18NOK", 918313)
    execution.process_decision(db_session, strategy, inst, BUY)
    assert db_session.query(RiskEvent).filter_by(strategy_id=strategy.id).count() == 1
