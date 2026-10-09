"""A TRADE the brain itself lowered to WATCH only because the risk check said
no is kept as scored practice evidence: in practice it becomes a BUY tagged
blocked_by_risk_limit, so it is scored but never counts as placeable. Outside
practice, or for any other WATCH, nothing changes."""

from __future__ import annotations

import pandas as pd
import pytest

from brain_m18_fixtures import DAY, brain_strategy, decision, instrument, no_broker, run
from swing_trade_ml.core.enums import SignalType
from swing_trade_ml.db.models.trading import Order
from swing_trade_ml.services import execution
from swing_trade_ml.services.brain_golive import compare
from swing_trade_ml.services.brain_golive import stage as stage_mod
from swing_trade_ml.services.risk import RiskDecision
from swing_trade_ml.strategies import brain as brain_mod
from swing_trade_ml.strategies import get_strategy

DF = pd.DataFrame({"ts": [pd.Timestamp("2031-01-06")], "close": [101.0]})
REASON = "Good idea, but the risk check said no: The market looks under stress right now."


@pytest.fixture()
def today(monkeypatch):
    monkeypatch.setattr(brain_mod, "today_ist", lambda: DAY)
    return DAY


def _downgraded(db, run_id, symbol, *, reason=REASON, **kw):
    d = decision(db, run_id, symbol, "WATCH", reasons=(reason,), **kw)
    d.downgraded_from = "TRADE"
    d.downgrade_reason = reason
    db.flush()
    return d


def _evaluate(db, inst, strategy=None):
    return get_strategy(strategy or brain_strategy(db)).evaluate(DF, inst, db)


def test_practice_risk_downgrade_becomes_a_tagged_buy(db_session, today):
    inst = instrument(db_session, "RDGA", 921001)
    run(db_session, "rdg-r1")
    _downgraded(db_session, "rdg-r1", "RDGA")
    d = _evaluate(db_session, inst)
    assert d.signal == SignalType.BUY
    assert (d.stop_loss, d.take_profit, d.horizon_days) == (96.0, 108.0, 15)
    assert d.features[brain_mod.BLOCKED_BY_RISK_KEY] == "BRAIN_RISK_CHECK"
    assert brain_mod.BLOCKED_BY_RISK_KEY == execution.BLOCKED_BY_RISK_KEY == compare.BLOCKED_KEY


@pytest.mark.parametrize("stage", ["approval", "auto"])
def test_outside_practice_it_stays_a_hold(db_session, today, monkeypatch, stage):
    monkeypatch.setattr(stage_mod, "current_stage", lambda db: stage)
    inst = instrument(db_session, f"RDGB{stage[:2].upper()}", 921002 if stage == "approval" else 921003)
    run(db_session, f"rdg-r2-{stage}")
    _downgraded(db_session, f"rdg-r2-{stage}", inst.tradingsymbol)
    assert _evaluate(db_session, inst).signal == SignalType.HOLD


def test_other_watch_reasons_stay_a_hold(db_session, today):
    inst = instrument(db_session, "RDGC", 921004)
    run(db_session, "rdg-r3")
    _downgraded(db_session, "rdg-r3", "RDGC", reason="Results are due in 3 days.")
    assert _evaluate(db_session, inst).signal == SignalType.HOLD


def test_an_owner_overrule_is_never_turned_into_evidence(db_session, today):
    inst = instrument(db_session, "RDGD", 921005)
    run(db_session, "rdg-r4")
    _downgraded(db_session, "rdg-r4", "RDGD", overruled_word="AVOID", overrule_reason="No.")
    assert _evaluate(db_session, inst).signal == SignalType.HOLD


def test_without_levels_it_stays_a_hold(db_session, today):
    inst = instrument(db_session, "RDGE", 921006)
    run(db_session, "rdg-r5")
    _downgraded(db_session, "rdg-r5", "RDGE", stop=None)
    assert _evaluate(db_session, inst).signal == SignalType.HOLD


def test_recorded_as_blocked_and_never_placeable_even_if_v1_would_allow(db_session, today, monkeypatch):
    """The brain said no for today's book; if v1's later check passes, the idea
    must still not count toward the gate, and nothing is ordered."""
    no_broker(monkeypatch)
    monkeypatch.setattr(execution, "portfolio_value_and_cash", lambda db, mode: (1_000_000.0, 1_000_000.0))
    monkeypatch.setattr(execution.risk, "check_entry", lambda **kw: RiskDecision(True, 5, "ok"))
    strategy = brain_strategy(db_session, name="rdg-brain")
    inst = instrument(db_session, "RDGF", 921007)
    run(db_session, "rdg-r6")
    _downgraded(db_session, "rdg-r6", "RDGF")
    sig = execution.process_decision(db_session, strategy, inst, _evaluate(db_session, inst, strategy))
    assert sig.signal_type == SignalType.BUY
    assert sig.features[execution.BLOCKED_BY_RISK_KEY] == "BRAIN_RISK_CHECK"
    assert not sig.was_executed
    assert db_session.query(Order).filter_by(strategy_id=strategy.id).count() == 0


def test_blocked_evidence_is_never_made_an_approval(db_session, monkeypatch):
    """Switching to the approval stage mid-day must not turn the morning's
    practice evidence into ideas to approve."""
    from brain_m18_fixtures import signal
    from swing_trade_ml.services.brain_golive import approvals

    monkeypatch.setattr(approvals, "current_stage", lambda db: "approval")
    strategy = brain_strategy(db_session, name="rdg-appr")
    inst = instrument(db_session, "RDGG", 921008)
    sig = signal(db_session, strategy, inst)
    sig.features = {execution.BLOCKED_BY_RISK_KEY: "BRAIN_RISK_CHECK"}
    signal(db_session, strategy, instrument(db_session, "RDGH", 921009))  # a real idea, same day
    db_session.flush()
    symbols = {a.symbol for a in approvals.create_pending(db_session, DAY)}
    assert "RDGH" in symbols  # proves the path creates approvals at all
    assert "RDGG" not in symbols


def test_blocked_evidence_is_kept_off_the_buy_lists(db_session):
    from swing_trade_ml.api.v1.endpoints import signals as signals_ep

    tagged = type("S", (), {"features": {execution.BLOCKED_BY_RISK_KEY: "SLOTS"}})()
    plain = type("S", (), {"features": {}})()
    assert signals_ep._practice_evidence(tagged) is True
    assert signals_ep._practice_evidence(plain) is False


def test_dashboard_feed_skips_blocked_evidence_in_the_query(db_session):
    """The feed applies a row limit in SQL, so the filter must be in SQL too —
    otherwise a day of blocked ideas would push every real signal out."""
    from brain_m18_fixtures import signal
    from swing_trade_ml.api.v1.endpoints import signals as signals_ep

    strategy = brain_strategy(db_session, name="rdg-feed")
    real = signal(db_session, strategy, instrument(db_session, "RDGI", 921010))
    for n in range(3):
        s = signal(db_session, strategy, instrument(db_session, f"RDGJ{n}", 921011 + n), hh=15, mm=56 + n)
        s.features = {execution.BLOCKED_BY_RISK_KEY: "DEPLOYABLE"}
    db_session.flush()
    rows = signals_ep.latest_actionable(db_session, limit=1, symbol=None)
    assert [r["id"] for r in rows] == [real.id]
