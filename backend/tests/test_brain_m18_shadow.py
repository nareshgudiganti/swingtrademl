"""M18 task 3: the brain strategy runs right after the nightly brain run,
records its ideas through the normal strategy path and orders nothing; v1's
signal evaluator scores them."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from brain_m18_fixtures import DAY, at, brain_strategy, candle, decision, instrument, no_broker, run, signal
from swing_trade_ml.cli import build_parser
from swing_trade_ml.core.enums import SignalType
from swing_trade_ml.db.models.trading import Order, Signal
from swing_trade_ml.services import engine, execution
from swing_trade_ml.services.brain_golive import shadow
from swing_trade_ml.services.risk import RiskDecision
from swing_trade_ml.strategies import brain as brain_mod


@pytest.fixture()
def safe_scan(monkeypatch):
    no_broker(monkeypatch)
    monkeypatch.setattr(brain_mod, "today_ist", lambda: DAY)
    monkeypatch.setattr(engine, "_buy_slot_budget", lambda db, strategy, mode: 5)
    monkeypatch.setattr(execution, "portfolio_value_and_cash", lambda db, mode: (1_000_000.0, 1_000_000.0))
    monkeypatch.setattr(execution.risk, "check_entry", lambda **kw: RiskDecision(True, 10))


def test_ensure_brain_strategy_is_idempotent_and_advisory(db_session, monkeypatch):
    monkeypatch.setattr(shadow, "current_mode", lambda: "paper")
    a = shadow.ensure_brain_strategy(db_session)
    b = shadow.ensure_brain_strategy(db_session)
    assert a.id == b.id
    assert (a.strategy_type, a.execution_mode, a.is_active, a.mode) == ("brain", "advisory", True, "paper")


def test_the_shadow_scan_records_the_idea_and_orders_nothing(db_session, safe_scan):
    inst = instrument(db_session, "M18SHD", 918202)
    candle(db_session, inst, DAY, 101.0)
    strategy = brain_strategy(db_session, symbols=["M18SHD"])
    run(db_session, "m18-shd")
    decision(db_session, "m18-shd", "M18SHD", "TRADE")
    result = shadow.run_brain_strategy(db_session)
    assert result.errors == [] and result.buys == 1
    sig = db_session.query(Signal).filter_by(strategy_id=strategy.id).one()
    assert (sig.signal_type, sig.advisory_only, sig.stop_loss, sig.take_profit, sig.horizon_days) == (
        SignalType.BUY,
        True,
        96.0,
        108.0,
        15,
    )
    assert db_session.query(Order).filter_by(strategy_id=strategy.id).count() == 0


def test_no_brain_run_today_skips_the_scan(db_session, safe_scan):
    inst = instrument(db_session, "M18SHE", 918203)
    candle(db_session, inst, DAY, 101.0)
    strategy = brain_strategy(db_session, symbols=["M18SHE"])
    result = shadow.run_brain_strategy(db_session)
    assert "no brain run today" in result.errors[0]
    assert db_session.query(Signal).filter_by(strategy_id=strategy.id).count() == 0


def test_brain_buy_signals_are_scored_by_version_1s_signal_evaluator(db_session):
    from swing_trade_ml.ml.predict import evaluate_pending_signals

    strategy = brain_strategy(db_session)
    inst = instrument(db_session, "M18SCR", 918201)
    sig = signal(db_session, strategy, inst, DAY)
    candle(db_session, inst, DAY + timedelta(days=1), 105.0, high=109.0, low=101.0)
    evaluate_pending_signals(db_session, now=at(DAY + timedelta(days=3)))
    db_session.refresh(sig)
    assert sig.outcome == "TARGET_HIT" and sig.outcome_pct == pytest.approx(0.08)


@contextmanager
def _fake_scope():
    yield MagicMock()


def test_the_brain_strategy_runs_after_a_nightly_run_only(monkeypatch):
    from swing_trade_ml.brain import service as brain_service
    from swing_trade_ml.workers import jobs

    monkeypatch.setattr(jobs, "session_scope", _fake_scope)
    monkeypatch.setattr(brain_service, "run_brain", lambda db, kind, book: (None, f"rid-{kind}"))
    calls: list[str] = []
    monkeypatch.setattr(jobs, "job_brain_strategy", lambda: calls.append("ran"))
    jobs._run_brain_job("intraday")
    assert calls == []
    jobs._run_brain_job("nightly")
    assert calls == ["ran"]


def test_a_failed_nightly_run_does_not_run_the_brain_strategy(monkeypatch):
    from swing_trade_ml.brain import service as brain_service
    from swing_trade_ml.workers import jobs

    def boom(db, kind, book):
        raise RuntimeError("no data")

    monkeypatch.setattr(jobs, "session_scope", _fake_scope)
    monkeypatch.setattr(brain_service, "run_brain", boom)
    monkeypatch.setattr(jobs, "_report_error", lambda *a, **k: None)
    calls: list[str] = []
    monkeypatch.setattr(jobs, "job_brain_strategy", lambda: calls.append("ran"))
    jobs._run_brain_job("nightly")
    assert calls == []


def test_a_failing_brain_strategy_job_is_reported_not_raised(monkeypatch):
    from swing_trade_ml.workers import jobs

    reported = []
    monkeypatch.setattr(jobs, "session_scope", _fake_scope)
    monkeypatch.setattr(shadow, "run_brain_strategy", MagicMock(side_effect=RuntimeError("x")))
    monkeypatch.setattr(jobs, "_report_error", lambda what, exc: reported.append(what))
    jobs.job_brain_strategy()
    assert reported == ["brain strategy scan"]


def test_brain_strategy_commands_parse():
    assert build_parser().parse_args(["brain", "strategy-create"]).brain_command == "strategy-create"
    assert build_parser().parse_args(["brain", "shadow-scan"]).brain_command == "shadow-scan"
