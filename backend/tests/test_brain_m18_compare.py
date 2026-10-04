"""M18 task 4: brain vs version 1 on the same days, from Signal outcomes."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from brain_m18_fixtures import brain_strategy, instrument, signal, v1_strategy
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import SignalType
from swing_trade_ml.services.brain_golive import compare as cmp

HEADERS = {"X-API-Key": "test-api-key"}
D1, D2, D3 = date(2031, 1, 6), date(2031, 1, 7), date(2031, 1, 14)


def _row(strategy, day, outcome=None, pct=None, symbol="A", is_brain=None, hour=10):
    return cmp.Row(
        strategy=strategy,
        is_brain=(strategy == "brain") if is_brain is None else is_brain,
        symbol=symbol,
        day=day,
        generated_at=datetime(day.year, day.month, day.day, hour, tzinfo=UTC),
        outcome=outcome,
        outcome_pct=pct,
    )


def test_only_days_the_brain_ran_count():
    rows = [
        _row("brain", D1, "TARGET_HIT", 0.08),
        _row("v1", D1, "STOP_LOSS_HIT", -0.04),
        _row("v1", D2, "TARGET_HIT", 0.08),
    ]
    out = cmp.compare(rows, {D1})
    assert out["version1"]["ideas"] == 1 and out["days"] == 1


def test_hit_rate_and_average_use_finished_ideas_only():
    rows = [
        _row("brain", D1, "TARGET_HIT", 0.08, symbol="A"),
        _row("brain", D1, "STOP_LOSS_HIT", -0.04, symbol="B"),
        _row("brain", D1, None, None, symbol="C"),
    ]
    s = cmp.compare(rows, {D1})["brain"]
    assert (s["ideas"], s["finished"]) == (3, 2)
    assert s["hit_rate"] == pytest.approx(0.5) and s["stopped"] == pytest.approx(0.5)
    assert s["avg_outcome_pct"] == pytest.approx(0.02)


def test_nothing_finished_gives_no_rates():
    s = cmp.summarise([_row("brain", D1)])
    assert s == {"ideas": 1, "finished": 0, "hit_rate": None, "stopped": None, "avg_outcome_pct": None}


def test_one_idea_per_stock_per_day():
    rows = [
        _row("brain", D1, "STOP_LOSS_HIT", -0.04, hour=10),
        _row("brain", D1, "TARGET_HIT", 0.08, hour=12),
    ]
    s = cmp.compare(rows, {D1})["brain"]
    assert s["ideas"] == 1 and s["hit_rate"] == 1.0  # the later scan of the day wins


def test_brain_first_then_version_1_strategies_and_weeks_ascending():
    rows = [_row("ml", D3), _row("brain", D3), _row("brain", D1), _row("sma", D1)]
    out = cmp.compare(rows, {D1, D3})
    assert [s["name"] for s in out["strategies"]] == ["brain", "ml", "sma"]
    assert [w["week"] for w in out["by_week"]] == ["2031-W02", "2031-W03"]


def test_notes_in_plain_words():
    assert cmp.compare([], set())["note"].startswith("The brain strategy has not run yet")
    few = cmp.compare([_row("brain", D1, "TARGET_HIT", 0.08)], {D1})["note"]
    assert "too few to compare yet" in few
    many = [_row("brain", D1, "TARGET_HIT", 0.08, symbol=f"B{i}") for i in range(10)]
    many += [_row("v1", D1, "STOP_LOSS_HIT", -0.04, symbol=f"V{i}") for i in range(10)]
    note = cmp.compare(many, {D1})["note"]
    assert note == (
        "On the same 1 day, the brain's ideas reached their target 100% of the time (average result +8.0%); "
        "version 1's reached it 0% of the time (average -4.0%)."
    )


def test_the_loader_reads_buy_signals_and_skips_long_term_ideas(db_session):
    brain = brain_strategy(db_session)
    ml = v1_strategy(db_session, name="m18-cmp-ml")
    ltv = v1_strategy(
        db_session, name="m18-cmp-ltv", strategy_type="long_term_value", execution_mode="advisory"
    )
    inst = instrument(db_session, "M18CMP", 918401)
    signal(db_session, brain, inst, D1, outcome="TARGET_HIT", outcome_pct=0.08)
    signal(db_session, brain, inst, D2, signal_type=SignalType.HOLD)  # the brain ran on D2 too
    signal(db_session, ml, inst, D2, outcome="STOP_LOSS_HIT", outcome_pct=-0.04)
    signal(db_session, ml, inst, D3)  # the brain did not run that day
    signal(db_session, ltv, inst, D1)
    rows, days = cmp.load(db_session)
    assert days == {D1, D2}
    assert {r.strategy for r in rows} == {brain.name, ml.name}  # HOLD and long-term rows left out
    out = cmp.compare(rows, days)
    assert out["version1"]["ideas"] == 1 and out["brain"]["finished"] == 1
    assert cmp.finished_brain_ideas(db_session) == 1


def test_compare_endpoint_on_an_empty_book(client):
    r = client.get("/api/v1/brain/compare", headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["strategies"] == [] and body["needed"] == 30 and body["brain_finished"] == 0
    assert body["note"].startswith("The brain strategy has not run yet")


def test_compare_is_hidden_while_the_brain_is_off(client, monkeypatch):
    monkeypatch.setattr(settings, "BRAIN_ENABLED", False)
    assert client.get("/api/v1/brain/compare", headers=HEADERS).status_code == 404
