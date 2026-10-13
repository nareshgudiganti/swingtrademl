"""The silent-failure watch: a brain run that produces no counted idea must be visible, and an idea
that is produced must reach the practice counter end to end (run -> decision -> signal -> compare)."""

from __future__ import annotations

import pytest

from brain_m18_fixtures import DAY, at, brain_strategy, candle, decision, instrument, no_broker, run
from swing_trade_ml.db.models.trading import Signal
from swing_trade_ml.services import engine, execution
from swing_trade_ml.services.brain_golive import compare, idea_watch, shadow
from swing_trade_ml.services.risk import RiskDecision
from swing_trade_ml.strategies import brain as brain_mod


@pytest.fixture()
def safe_scan(monkeypatch):
    no_broker(monkeypatch)
    monkeypatch.setattr(brain_mod, "today_ist", lambda: DAY)
    monkeypatch.setattr(engine, "_buy_slot_budget", lambda db, strategy, mode: 5)
    monkeypatch.setattr(execution, "portfolio_value_and_cash", lambda db, mode: (1_000_000.0, 1_000_000.0))
    monkeypatch.setattr(execution.risk, "check_entry", lambda **kw: RiskDecision(True, 10))


def _scan(db):
    """Run the brain strategy, then date its signals to the test day (the scan stamps real time)."""
    shadow.run_brain_strategy(db)
    for sig in db.query(Signal).all():
        sig.generated_at = at(DAY)
    db.flush()


def _brain_rows(db):
    rows, _ = compare.load(db)
    return [r for r in rows if r.is_brain]


def test_an_idea_reaches_the_counter_end_to_end(db_session, safe_scan):
    inst = instrument(db_session, "WATCHA", 920001)
    candle(db_session, inst, DAY, 101.0)
    brain_strategy(db_session, symbols=["WATCHA"])
    run(db_session, "watch-a")
    decision(db_session, "watch-a", "WATCHA", "TRADE")
    _scan(db_session)

    rows = _brain_rows(db_session)
    assert [(r.symbol, r.day, r.blocked) for r in rows] == [("WATCHA", DAY, False)]
    assert compare.report(db_session)["brain"]["ideas"] == 1
    result = idea_watch.check(db_session, DAY)
    assert result["ok"] and result["level"] == "ok"


def test_a_risk_blocked_idea_still_counts_as_recorded(db_session, safe_scan, monkeypatch):
    monkeypatch.setattr(
        execution.risk, "check_entry", lambda **kw: RiskDecision(False, 0, "stress cap", rule="DEPLOYABLE")
    )
    inst = instrument(db_session, "WATCHB", 920002)
    candle(db_session, inst, DAY, 101.0)
    brain_strategy(db_session, symbols=["WATCHB"])
    run(db_session, "watch-b")
    decision(db_session, "watch-b", "WATCHB", "TRADE")
    _scan(db_session)

    result = idea_watch.check(db_session, DAY)
    assert result["ok"] and "1 blocked" in result["detail"]


def test_a_finished_run_with_no_recorded_idea_fails_the_check(db_session, safe_scan):
    inst = instrument(db_session, "WATCHC", 920003)
    candle(db_session, inst, DAY, 101.0)
    brain_strategy(db_session, symbols=["WATCHC"])
    run(db_session, "watch-c")  # the brain ran, produced no idea decision
    _scan(db_session)

    result = idea_watch.check(db_session, DAY)
    assert not result["ok"] and result["level"] == "fail"
    assert "no idea reached the practice counter" in result["detail"]


def test_no_finished_nightly_is_left_to_the_nightly_check(db_session):
    result = idea_watch.check(db_session, DAY)
    assert result["ok"] and result["level"] == "info"


def test_a_failed_run_does_not_count_as_a_finished_run(db_session):
    run(db_session, "watch-d", status="failed")
    assert idea_watch.check(db_session, DAY)["level"] == "info"
