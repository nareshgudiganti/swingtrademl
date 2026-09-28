"""The shadow strategies' evidence has to be visible where it is compared.

The three barrier models run as advisory shadow strategies: they write Signal
rows and place no orders. /strategies/performance measured win rate from Trade
rows only, so every one of them reported "0 trades, 0% win rate" — the one
screen that looks like the promotion comparison could not see the only
evidence the promotion decision rests on.

Resolved signals are that evidence. A signal is resolved once
ml/predict.py::evaluate_pending_signals has scored it against real prices,
and only a target hit counts as a win — a stop is a loss and so is an expiry,
because that is the question the confidence answers.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Signal, Strategy
from swing_trade_ml.ml.calibration import signal_evidence

HEADERS = {"X-API-Key": "test-api-key"}


def _shadow_with_signals(db_session, outcomes: list[str | None]) -> Strategy:
    """An advisory strategy that has never traded, carrying scored signals."""
    strategy = Strategy(
        name="ml_swing_main_barrier",
        strategy_type="ml_swing",
        mode="paper",
        is_active=True,
        execution_mode="advisory",
        params={"model_name": "swing_classifier_barrier"},
    )
    instrument = Instrument(
        instrument_token=771001, tradingsymbol="SHADOWCO", exchange="NSE", is_watchlisted=True
    )
    db_session.add_all([strategy, instrument])
    db_session.flush()

    now = datetime.now(UTC)
    for i, outcome in enumerate(outcomes):
        db_session.add(
            Signal(
                strategy_id=strategy.id,
                instrument_id=instrument.id,
                signal_type="BUY",
                mode="paper",
                price=100.0,
                confidence=0.65,
                stop_loss=96.0,
                take_profit=108.0,
                horizon_days=15,
                outcome=outcome,
                outcome_pct=0.08 if outcome == "TARGET_HIT" else -0.04,
                advisory_only=True,
                generated_at=now - timedelta(days=40 - i),
            )
        )
    db_session.flush()
    return strategy


def test_resolved_signals_are_counted_for_a_strategy_that_never_traded(db_session):
    outcomes = ["TARGET_HIT"] * 3 + ["STOP_LOSS_HIT"] * 2 + ["EXPIRED_NO_HIT"]
    strategy = _shadow_with_signals(db_session, outcomes)

    evidence = signal_evidence(db_session, strategy_id=strategy.id, mode="paper")

    assert evidence["resolved"] == 6
    assert evidence["target_hit"] == 3
    assert evidence["stopped"] == 2
    assert evidence["expired"] == 1
    assert evidence["win_rate"] == 0.5


def test_unresolved_signals_are_counted_separately_not_as_losses(db_session):
    """A signal still inside its horizon is not evidence of anything yet.
    Folding it in as a non-win would make every young strategy look bad."""
    strategy = _shadow_with_signals(db_session, ["TARGET_HIT", None, None])

    evidence = signal_evidence(db_session, strategy_id=strategy.id, mode="paper")

    assert evidence["resolved"] == 1
    assert evidence["pending"] == 2
    assert evidence["win_rate"] == 1.0


def test_evidence_says_when_there_is_not_enough_to_judge(db_session):
    """Below the promotion bar the endpoint must not hand out a win rate that
    reads like a verdict — 1 of 1 is not a 100% strategy."""
    strategy = _shadow_with_signals(db_session, ["TARGET_HIT"])

    evidence = signal_evidence(db_session, strategy_id=strategy.id, mode="paper")

    assert evidence["resolved"] == 1
    assert evidence["enough_to_judge"] is False


def test_a_strategy_with_no_signals_reports_zero_rather_than_failing(db_session):
    strategy = _shadow_with_signals(db_session, [])

    evidence = signal_evidence(db_session, strategy_id=strategy.id, mode="paper")

    assert evidence == {
        "resolved": 0, "pending": 0, "target_hit": 0, "stopped": 0,
        "expired": 0, "win_rate": 0.0, "enough_to_judge": False,
    }


def test_the_performance_endpoint_shows_shadow_evidence(client, db_session):
    """The regression that matters: a shadow strategy on the Strategies tab
    no longer reads as an untried idea."""
    outcomes = ["TARGET_HIT"] * 20 + ["STOP_LOSS_HIT"] * 15
    _shadow_with_signals(db_session, outcomes)
    db_session.commit()

    response = client.get("/api/v1/strategies/performance", headers=HEADERS)
    assert response.status_code == 200

    shadow = next(r for r in response.json()["strategies"] if r["name"] == "ml_swing_main_barrier")
    assert shadow["windows"]["all_time"]["trades"] == 0
    assert shadow["signal_evidence"]["resolved"] == 35
    assert shadow["signal_evidence"]["enough_to_judge"] is True
    assert shadow["signal_evidence"]["win_rate"] == 20 / 35
