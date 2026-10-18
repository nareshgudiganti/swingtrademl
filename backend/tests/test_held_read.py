"""The daily read on held stocks for the Testing and My Holdings tabs:
day count, one suggestion word, and a daily score for Testing positions.

Motivating case (owner, 2026-10-17): "I bought Infosys 3 days back — I need
Infosys's model score every day, which day of the trade it is, and what to do."
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd
import pytest
from sqlalchemy import select

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import PositionStatus
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.trading import Position, PositionScore, Strategy
from swing_trade_ml.services import held_read, tester_paper
from swing_trade_ml.services.held_read import (
    HOLD,
    SELL,
    SELL_PARTIALLY,
    WATCH,
    day_number,
    suggestion,
)
from swing_trade_ml.strategies.base import SignalDecision

HEADERS = {"X-API-Key": "test-api-key"}

# Mon 2026-10-12 .. Fri 2026-10-16 are all trading days.
MON_10AM_IST = datetime(2026, 10, 12, 4, 30, tzinfo=UTC)


# --- day count -------------------------------------------------------------


def test_bought_monday_is_day_4_on_thursday():
    assert day_number(MON_10AM_IST, date(2026, 10, 15)) == 4


def test_the_buy_day_is_day_1():
    assert day_number(MON_10AM_IST, date(2026, 10, 12)) == 1


def test_weekends_are_not_counted():
    # Fri buy -> Mon is Day 2, not Day 4.
    fri = datetime(2026, 10, 16, 4, 30, tzinfo=UTC)
    assert day_number(fri, date(2026, 10, 19)) == 2


def test_a_weekend_import_starts_at_day_1_on_monday():
    sat = datetime(2026, 10, 17, 4, 30, tzinfo=UTC)
    assert day_number(sat, date(2026, 10, 19)) == 1
    assert day_number(sat, date(2026, 10, 17)) == 1


# --- suggestion --------------------------------------------------------------


def test_the_bots_sell_verdict_is_sell_even_when_up():
    code, reason = suggestion("exit", "Exit signal — model wants out", 0.07, False, 3, first_target=0.05)
    assert code == SELL and "model wants out" in reason


def test_up_past_first_target_and_not_yet_halved_is_sell_partially():
    code, reason = suggestion("bullish", "Still bullish", 0.051, False, 3, first_target=0.05)
    assert code == SELL_PARTIALLY and "half" in reason


def test_already_halved_is_not_told_to_halve_again():
    code, _ = suggestion("bullish", "Still bullish", 0.07, True, 3, first_target=0.05)
    assert code == HOLD


@pytest.mark.parametrize("action", ["alert", "weak", "dip"])
def test_a_fading_score_is_watch(action):
    code, _ = suggestion(action, "Losing conviction", 0.01, False, 3, first_target=0.05)
    assert code == WATCH


def test_past_the_15_day_plan_is_watch_not_hold():
    code, reason = suggestion("hold", "Neutral", 0.01, False, 16, first_target=0.05)
    assert code == WATCH and "15" in reason


def test_steady_is_hold():
    assert suggestion("bullish", "Still bullish", 0.01, False, 3, first_target=0.05)[0] == HOLD
    assert suggestion("hold", "Neutral", -0.02, False, 15, first_target=0.05)[0] == HOLD


# --- daily score for Testing positions ---------------------------------------


@pytest.fixture
def _tester_on(monkeypatch):
    monkeypatch.setattr(settings, "PAPER_TESTER_ENABLED", True)
    monkeypatch.setattr(settings, "PAPER_TESTER_STARTING_CAPITAL", 1_000_000.0)
    monkeypatch.setattr(settings, "TRADING_MODE", "paper")


class _FakeModel:
    """Stands in for ml_swing: returns a fixed probability for every stock."""

    def __init__(self, probability):
        self.probability = probability

    def min_bars_required(self):
        return 1

    def evaluate(self, df, instrument, db):
        if self.probability is None:
            return None
        return SignalDecision(
            signal="HOLD",
            price=100.0,
            confidence=self.probability,
            reason="test",
            features={"probability": self.probability, "model": "swing_classifier:test"},
        )


def _tester_position(db, symbol, token):
    inst = Instrument(instrument_token=token, tradingsymbol=symbol, exchange="NSE", is_active=True)
    db.add(inst)
    db.flush()
    db.add(
        Candle(
            instrument_id=inst.id,
            interval="day",
            ts=datetime(2026, 10, 1, 18, 30, tzinfo=UTC),
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.0,
            volume=100_000,
        )
    )
    db.flush()
    return tester_paper.paper_buy(db, symbol, 10, "large")


def _model_strategy(db):
    s = Strategy(
        name="ml_swing_test_ref",
        strategy_type="ml_swing",
        mode="paper",
        is_active=True,
        params={"model_name": "swing_classifier"},
    )
    db.add(s)
    db.flush()
    return s


def _patch(monkeypatch, probability):
    import swing_trade_ml.ml.dataset as dataset
    import swing_trade_ml.strategies as strategies

    monkeypatch.setattr(strategies, "get_strategy", lambda strategy: _FakeModel(probability))
    monkeypatch.setattr(dataset, "load_candles", lambda *a, **k: pd.DataFrame({"close": [100.0]}))


def test_a_testing_stock_gets_a_score_every_day(db_session, monkeypatch, _tester_on):
    pos = _tester_position(db_session, "HRTEST", 990_101)
    _model_strategy(db_session)

    _patch(monkeypatch, 0.72)
    assert held_read.score_tester_positions(db_session, today=date(2026, 10, 13)) == 1
    _patch(monkeypatch, 0.61)
    assert held_read.score_tester_positions(db_session, today=date(2026, 10, 14)) == 1

    trail = db_session.execute(
        select(PositionScore.as_of, PositionScore.score)
        .where(PositionScore.position_id == pos.id)
        .order_by(PositionScore.as_of)
    ).all()
    assert [(d, s) for d, s in trail] == [(date(2026, 10, 13), 0.72), (date(2026, 10, 14), 0.61)]
    db_session.refresh(pos)
    assert pos.entry_confidence == 0.72  # first read stands in as "where it started"
    assert pos.last_confidence == 0.61


def test_no_reading_today_is_a_gap_not_a_made_up_number(db_session, monkeypatch, _tester_on):
    pos = _tester_position(db_session, "HRGAP", 990_102)
    _model_strategy(db_session)
    _patch(monkeypatch, None)

    assert held_read.score_tester_positions(db_session, today=date(2026, 10, 13)) == 0
    assert (
        db_session.execute(select(PositionScore).where(PositionScore.position_id == pos.id)).first() is None
    )


def test_scoring_never_raises(db_session, monkeypatch, _tester_on):
    _tester_position(db_session, "HRBOOM", 990_103)
    _model_strategy(db_session)
    import swing_trade_ml.strategies as strategies

    def boom(strategy):
        raise RuntimeError("model file missing")

    monkeypatch.setattr(strategies, "get_strategy", boom)
    assert held_read.score_tester_positions(db_session, today=date(2026, 10, 13)) == 0
    still_open = (
        db_session.execute(select(Position).where(Position.status == PositionStatus.OPEN)).scalars().all()
    )
    assert still_open  # nothing about the position itself changed


def test_testing_tab_rows_carry_day_and_suggestion(client, db_session, _tester_on):
    _tester_position(db_session, "HRAPI", 990_104)
    resp = client.get("/api/v1/portfolio/positions/detailed?book=tester", headers=HEADERS)
    assert resp.status_code == 200
    row = next(r for r in resp.json() if r["symbol"] == "HRAPI")
    assert row["day_number"] >= 1
    assert row["trade_limit_days"] == 15
    assert row["suggestion"] in {SELL, SELL_PARTIALLY, WATCH, HOLD}
    assert row["suggestion_reason"]
