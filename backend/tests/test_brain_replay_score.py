# backend/tests/test_brain_replay_score.py
"""Replay-score orchestrator against the test database. The replay itself is stubbed:
the runs and decisions are written by hand so the test controls exactly what the
brain 'said', and the candles decide what happened next."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from swing_trade_ml.brain.replay_score import collect_ideas, load_bars, run_replay_score, v1_buys
from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.trading import Signal, Strategy

IST = ZoneInfo("Asia/Kolkata")
DAY1, DAY2 = date(2026, 8, 3), date(2026, 8, 4)  # Mon, Tue
UPTO = date(2026, 9, 30)


def _inst(db, symbol, token):
    inst = Instrument(
        instrument_token=token, tradingsymbol=symbol, exchange="NSE", is_watchlisted=True, is_active=True
    )
    db.add(inst)
    db.flush()
    return inst


def _bars(db, inst, start: date, closes_ohlc):
    d = start
    for o, h, lo, c in closes_ohlc:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        ts = datetime.combine(d, time(0, 0), tzinfo=IST).astimezone(UTC)
        db.add(
            Candle(instrument_id=inst.id, interval="day", ts=ts, open=o, high=h, low=lo, close=c, volume=1000)
        )
        d += timedelta(days=1)


def _run(db, run_id, day):
    as_of = datetime.combine(day, time(23, 59), tzinfo=IST).astimezone(UTC)
    db.add(BrainRun(id=run_id, kind="nightly", as_of=as_of, book="paper", live=False, status="done"))
    db.flush()


def _decision(
    db, run_id, symbol, word, *, downgraded_from=None, reason=None, confidence=0.7, stop=96.0, target=108.0
):
    db.add(
        BrainDecision(
            run_id=run_id,
            symbol=symbol,
            kind="idea",
            word=word,
            reasons=[reason or "because"],
            entry_low=100.0,
            entry_high=100.0,
            target=target,
            stop=stop,
            confidence=confidence,
            downgraded_from=downgraded_from,
            downgrade_reason=reason,
        )
    )


RISK_NO = "Good idea, but the risk check said no: slots are full."


@pytest.fixture()
def world(db_session):
    win = _inst(db_session, "RSWIN", 995001)  # rises 9% on the day after DAY1
    lose = _inst(db_session, "RSLOSE", 995002)  # falls 5% on the day after DAY1
    quiet = _inst(db_session, "RSQUIET", 995003)
    _inst(db_session, "RSGONE", 995004)  # no candles at all
    flat = (100.0, 100.5, 99.5, 100.0)
    _bars(db_session, win, DAY1, [flat, (100, 109, 100, 108), *[(108, 109, 107, 108)] * 20])
    _bars(db_session, lose, DAY1, [flat, (100, 100, 94, 95), *[(95, 96, 94, 95)] * 20])
    _bars(db_session, quiet, DAY1, [flat] * 22)
    _run(db_session, "rs-run-1", DAY1)
    _decision(db_session, "rs-run-1", "RSWIN", "TRADE")
    _decision(db_session, "rs-run-1", "RSLOSE", "WATCH", downgraded_from="TRADE", reason=RISK_NO)
    _decision(db_session, "rs-run-1", "RSQUIET", "WAIT", confidence=0.4)
    _decision(db_session, "rs-run-1", "RSGONE", "TRADE")
    db_session.commit()
    return SimpleNamespace(day=DAY1, run_id="rs-run-1")


def test_collect_ideas_splits_the_two_tracks(db_session, world):
    rows, symbols = collect_ideas(db_session, world.run_id, world.day)
    by = {r["symbol"]: r for r in rows}
    assert set(symbols) == {"RSWIN", "RSLOSE", "RSQUIET", "RSGONE"}
    assert set(by) == {"RSWIN", "RSLOSE", "RSGONE"}  # the WAIT is not an idea
    assert by["RSWIN"]["track_b"] and not by["RSWIN"]["blocked"]
    assert by["RSLOSE"]["blocked"] and not by["RSLOSE"]["track_b"]


def test_load_bars_is_in_ist_days_and_bounded(db_session, world):
    bars = load_bars(db_session, ["RSWIN", "RSGONE"], UPTO)
    assert "RSGONE" not in bars or bars["RSGONE"].empty
    first = bars["RSWIN"].iloc[0]
    assert first["day"] == DAY1  # not the 18:30 UTC date before it
    capped = load_bars(db_session, ["RSWIN"], DAY1)
    assert len(capped["RSWIN"]) == 1


def test_full_run_scores_each_idea_and_never_touches_live_outcomes(db_session, world):

    def stub(db, **kw):
        return [
            SimpleNamespace(day=DAY1, run_id=world.run_id, banner="DEFENSIVE", counts={}, universe_size=4)
        ]

    report = run_replay_score(db_session, start=DAY1, end=DAY1, upto=UPTO, replay=stub, draws=20)

    by = {i["symbol"]: i for i in report["ideas"]}
    assert by["RSWIN"]["strict_status"] == "target"
    assert by["RSLOSE"]["strict_status"] == "stop"
    assert by["RSGONE"]["strict_status"] == "no_price_data"
    assert report["track_a"]["ideas"] == 3 and report["track_b"]["ideas"] == 2
    assert report["track_a"]["no_price_data"] == 1
    assert report["baselines"]["all_eligible"]["ideas"] == 4
    assert report["window"]["days_replayed"] == 1 and report["window"]["failed_days"] == []

    # the live learning columns are untouched
    outcomes = db_session.execute(select(BrainDecision.outcome)).scalars().all()
    assert all(o is None for o in outcomes)


def test_a_failed_replay_day_is_listed_not_hidden(db_session, world):
    def stub(db, **kw):
        raise RuntimeError("boom")

    report = run_replay_score(db_session, start=DAY1, end=DAY1, upto=UPTO, replay=stub, draws=5)
    assert report["window"]["failed_days"] and report["track_a"]["ideas"] == 0


def test_a_window_with_no_ideas_reports_cleanly(db_session):

    def stub(db, **kw):
        return []

    report = run_replay_score(db_session, start=DAY1, end=DAY1, upto=UPTO, replay=stub, draws=5)
    assert report["track_a"]["ideas"] == 0 and report["track_a"]["hit_rate"] is None


def test_v1_buys_reads_ml_swing_buy_signals_per_ist_day(db_session, world):
    strat = Strategy(name="rs-v1", strategy_type="ml_swing", params={}, is_active=True, mode="paper")
    db_session.add(strat)
    db_session.flush()
    inst = db_session.execute(select(Instrument).where(Instrument.tradingsymbol == "RSWIN")).scalar_one()
    when = datetime.combine(DAY2, time(10, 0), tzinfo=IST).astimezone(UTC)
    db_session.add(
        Signal(
            strategy_id=strat.id,
            instrument_id=inst.id,
            signal_type="BUY",
            mode="paper",
            price=100.0,
            generated_at=when,
        )
    )
    db_session.add(
        Signal(
            strategy_id=strat.id,
            instrument_id=inst.id,
            signal_type="HOLD",
            mode="paper",
            price=100.0,
            generated_at=when,
        )
    )
    db_session.commit()
    assert v1_buys(db_session, DAY1, DAY2) == {DAY2: ["RSWIN"]}
