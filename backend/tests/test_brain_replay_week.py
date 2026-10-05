"""Phase 1 gate: historical replay-week tooling."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from swing_trade_ml.brain import service
from swing_trade_ml.brain.replay_week import (
    iter_ist_trading_days,
    resolve_replay_range,
    run_replay_week,
)
from swing_trade_ml.db.models.brain import BrainRun
from swing_trade_ml.db.models.market import Candle, Instrument

IST = ZoneInfo("Asia/Kolkata")
AS_OF = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


def _instrument(db, symbol: str, token: int, *, watch: bool = True) -> Instrument:
    inst = Instrument(
        instrument_token=token, tradingsymbol=symbol, exchange="NSE", is_watchlisted=watch, is_active=True
    )
    db.add(inst)
    db.flush()
    return inst


def _candle(db, inst: Instrument, ts: datetime, close: float) -> None:
    db.add(
        Candle(
            instrument_id=inst.id,
            interval="day",
            ts=ts,
            open=close,
            high=close,
            low=close,
            close=close,
            volume=1000,
        )
    )


@pytest.fixture()
def replay_market(db_session):
    abc = _instrument(db_session, "REPLAY1", 992001)
    _candle(db_session, abc, AS_OF - timedelta(days=1), 100.0)
    db_session.commit()
    return abc


def test_iter_ist_trading_days_skips_weekends_and_holidays():
    # Mon 26 Jan 2026 is Republic Day; Fri 23 through Thu 29 span includes it.
    days = list(iter_ist_trading_days(date(2026, 1, 23), date(2026, 1, 29)))
    assert date(2026, 1, 26) not in days
    assert date(2026, 1, 24) not in days  # Saturday
    assert date(2026, 1, 25) not in days  # Sunday
    assert date(2026, 1, 23) in days
    assert date(2026, 1, 27) in days


def test_resolve_replay_range_days_counts_trading_days_only():
    # Freeze "now" to a Monday after the close so the window is deterministic.
    now = datetime(2026, 1, 27, 16, 0, tzinfo=IST)
    start, end = resolve_replay_range(from_day=None, to_day=None, days=3, now=now)
    assert end == date(2026, 1, 27)
    assert start == date(2026, 1, 22)  # Thu, Fri, Mon; skip weekend and Republic Day


def test_run_replay_week_one_day(db_session, replay_market):
    day = date(2026, 9, 25)
    results = run_replay_week(
        db_session,
        start=day,
        end=day,
        book="paper",
        symbols=["REPLAY1"],
    )
    assert len(results) == 1
    row = results[0]
    assert row.day == day
    assert row.universe_size == 1
    assert row.run_id
    run = db_session.get(BrainRun, row.run_id)
    assert run is not None
    assert run.live is False
    assert service.decisions_for(db_session, row.run_id)


def test_replay_week_skips_holiday_in_range(monkeypatch, db_session):
    calls: list[date] = []

    def fake_run_brain(db, *, kind="nightly", as_of=None, symbols=None, book="paper", **kwargs):
        calls.append(as_of.astimezone(IST).date())
        ctx = SimpleNamespace(
            request=SimpleNamespace(universe=tuple(symbols or ("REPLAY1",))),
            banner=SimpleNamespace(mode=SimpleNamespace(value="NORMAL")),
            decisions=(),
        )
        return ctx, "test-replay-id"

    monkeypatch.setattr("swing_trade_ml.brain.replay_week.service.run_brain", fake_run_brain)

    @contextmanager
    def noop_lock(kind, book, wait_seconds=0):
        yield

    monkeypatch.setattr("swing_trade_ml.brain.replay_week.brain_queue.run_lock", noop_lock)

    run_replay_week(
        db_session,
        start=date(2026, 1, 23),
        end=date(2026, 1, 27),
        symbols=["REPLAY1"],
    )
    assert date(2026, 1, 26) not in calls
    assert date(2026, 1, 23) in calls
    assert date(2026, 1, 27) in calls
