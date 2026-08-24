"""run_all_active() is the daily scan's entry point and the one thing
standing between "the global TRADING_MODE env flag flipped to live" and "every
strategy created back in the paper-testing phase starts placing real orders."
A strategy's own `mode` is stamped once at creation and never changes
afterwards (see api/v1/endpoints/strategies.py::create_strategy) — so this
filter, not the global env flag, is what actually decides whether a given
strategy runs today. It has never had a test of its own.

These stub out run_strategy() itself: proving *which* strategies get selected
is the safety property in question, not what a full evaluation does with one
once selected (that needs real candles/models and belongs to a different
test).
"""

from __future__ import annotations

from swing_trade_ml.db.models.trading import Strategy
from swing_trade_ml.services import engine


def _make_strategy(db_session, *, name: str, mode: str, is_active: bool = True) -> Strategy:
    strategy = Strategy(name=name, strategy_type="ml_swing", mode=mode, is_active=is_active)
    db_session.add(strategy)
    db_session.commit()
    return strategy


def _recording_run_strategy(monkeypatch, ran: list[str]) -> None:
    def fake_run_strategy(db, strategy, interval="day"):
        ran.append(strategy.name)
        return engine.ScanResult()

    monkeypatch.setattr(engine, "run_strategy", fake_run_strategy)


def test_a_strategy_matching_the_current_broker_mode_is_selected(db_session, monkeypatch):
    # conftest pins TRADING_MODE=paper / ALLOW_LIVE_TRADING=false, so
    # get_broker().mode resolves to "paper" for the whole test run.
    _make_strategy(db_session, name="ml_swing_main", mode="paper")

    ran: list[str] = []
    _recording_run_strategy(monkeypatch, ran)

    engine.run_all_active(db_session)

    assert ran == ["ml_swing_main"]


def test_a_strategy_stamped_live_stays_dormant_while_the_broker_is_paper(db_session, monkeypatch):
    """The exact property a mismatched `mode` exists to guarantee: flipping
    the global TRADING_MODE env var alone does not arm a strategy created
    before that switch — it stays dormant until deliberately recreated under
    the new mode."""
    _make_strategy(db_session, name="ml_swing_live_labeled", mode="live")

    ran: list[str] = []
    _recording_run_strategy(monkeypatch, ran)

    result = engine.run_all_active(db_session)

    assert ran == []
    assert result.strategies_run == 0


def test_an_inactive_strategy_is_never_selected_regardless_of_mode(db_session, monkeypatch):
    _make_strategy(db_session, name="ml_swing_paused", mode="paper", is_active=False)

    ran: list[str] = []
    _recording_run_strategy(monkeypatch, ran)

    engine.run_all_active(db_session)

    assert ran == []


def test_mixed_modes_only_runs_the_matching_ones(db_session, monkeypatch):
    _make_strategy(db_session, name="ml_swing_main", mode="paper")
    _make_strategy(db_session, name="ml_swing_midcap", mode="paper")
    _make_strategy(db_session, name="ml_swing_smallcap", mode="live")

    ran: list[str] = []
    _recording_run_strategy(monkeypatch, ran)

    engine.run_all_active(db_session)

    assert sorted(ran) == ["ml_swing_main", "ml_swing_midcap"]
