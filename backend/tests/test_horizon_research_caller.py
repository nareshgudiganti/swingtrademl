# ruff: noqa: E501 (long lines in test code)
"""The research-only gate in the decision itself (#387): 10D and 15D give no decision word to a non-research caller."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from swing_trade_ml.brain.horizons import NO_DECISION, ModelOutput, run_all_horizons, run_horizon

SESSION = date(2026, 1, 2)
SESSIONS = tuple(d for i in range(40) if (d := SESSION + timedelta(days=i)).weekday() < 5)


def out(horizon: int) -> ModelOutput:
    return ModelOutput(f"m{horizon}", "v1", horizon, "final", "DEMO", SESSION, 100.0, 0.95)


@pytest.mark.parametrize("horizon", [10, 15])
def test_a_default_caller_never_gets_a_decision_word_for_a_research_only_horizon(horizon):
    record = run_horizon(horizon, [out(horizon)], SESSION, SESSIONS)
    assert record.decision == NO_DECISION and "research-only" in record.reason
    assert record.score is None and record.model_name is None and record.target_pct is None


@pytest.mark.parametrize("horizon", [10, 15])
def test_a_research_caller_still_gets_the_decision(horizon):
    assert run_horizon(horizon, [out(horizon)], SESSION, SESSIONS, research_caller=True).decision == "TRADE"


def test_five_day_decides_for_everyone():
    assert run_horizon(5, [out(5)], SESSION, SESSIONS).decision == "TRADE"


def test_running_all_three_for_a_default_caller_keeps_three_results_and_only_five_decides():
    class Store:
        def __init__(self):
            self.rows = []

        def add(self, record):
            self.rows.append(record)

    store = Store()
    results = run_all_horizons(SESSION, [out(5), out(10), out(15)], SESSIONS, store, symbol="DEMO")
    assert [(h, r.decision) for h, r in results.items()] == [(5, "TRADE"), (10, NO_DECISION), (15, NO_DECISION)]
    assert len(store.rows) == 3
