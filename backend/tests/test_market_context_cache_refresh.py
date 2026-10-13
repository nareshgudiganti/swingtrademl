"""The market-context caches must expire. The worker clears them after its own ingest, but the API
process never sees that call, so without an expiry it keeps serving the index, VIX and breadth it
loaded at start-up."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.ml import market_context


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture()
def clock(monkeypatch):
    c = _Clock()
    monkeypatch.setattr(market_context, "_now", c)
    market_context.clear_cache()
    yield c
    market_context.clear_cache()


def _inst(db, symbol, watchlisted=False) -> Instrument:
    inst = Instrument(
        instrument_token=abs(hash(symbol)) % 1_000_000, tradingsymbol=symbol, exchange="NSE",
        is_watchlisted=watchlisted,
    )
    db.add(inst)
    db.flush()
    return inst


def _bar(db, inst, day: int, close: float) -> None:
    db.add(
        Candle(
            instrument_id=inst.id, interval="day", ts=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=day),
            open=close, high=close, low=close, close=close, volume=1,
        )
    )
    db.flush()


def test_index_cache_is_kept_inside_the_time_limit_then_reloaded(db_session, clock):
    nifty = _inst(db_session, "NIFTY 50")
    _bar(db_session, nifty, 0, 100)
    assert len(market_context.load_index_candles(db_session)) == 1

    _bar(db_session, nifty, 1, 101)  # a new bar is ingested by another process
    clock.t += market_context.CACHE_TTL_SECONDS - 1
    assert len(market_context.load_index_candles(db_session)) == 1  # still cached

    clock.t += 2
    assert len(market_context.load_index_candles(db_session)) == 2  # expired, reloaded


def test_breadth_cache_is_reloaded_after_the_time_limit(db_session, clock):
    a = _inst(db_session, "AAA", watchlisted=True)
    for d in range(60):
        _bar(db_session, a, d, 100 + d)
    assert len(market_context.load_market_breadth(db_session)) == 60

    _bar(db_session, a, 60, 200)
    assert len(market_context.load_market_breadth(db_session)) == 60
    clock.t += market_context.CACHE_TTL_SECONDS + 1
    assert len(market_context.load_market_breadth(db_session)) == 61


def test_clear_cache_still_forces_a_reload(db_session, clock):
    nifty = _inst(db_session, "NIFTY 50")
    _bar(db_session, nifty, 0, 100)
    market_context.load_index_candles(db_session)
    _bar(db_session, nifty, 1, 101)
    market_context.clear_cache()
    assert len(market_context.load_index_candles(db_session)) == 2
