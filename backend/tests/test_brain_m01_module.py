"""M01 against the database: fresh data lets a trade through, stale data
does not, and market-wide stale data stops new trades."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest

from brain_fakes import make_module, registry
from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.module import REGISTRY, Step
from swing_trade_ml.brain.modules.m01_quality.module import DataGateway
from swing_trade_ml.brain.modules.m01_quality.quality import IST, is_trading_day
from swing_trade_ml.brain.modules.m07_risk.module import RiskGate
from swing_trade_ml.brain.reader import DatedReader
from swing_trade_ml.brain.runner import execute
from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.safety import SystemState
from swing_trade_ml.services import deployable

FRI = date(2026, 9, 25)
AS_OF = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)  # 17:30 IST, after the day's ingest


def _add_bars(db, symbol: str, token: int, last: date, n: int = 240, close: float = 1000.0):
    inst = Instrument(
        instrument_token=token,
        tradingsymbol=symbol,
        exchange="NSE",
        is_watchlisted=symbol != settings.BENCHMARK_INDEX_SYMBOL,
        is_active=True,
    )
    db.add(inst)
    db.flush()
    d, added = last, 0
    while added < n:
        if is_trading_day(d):
            ts = datetime.combine(d, time(0, 0), tzinfo=IST).astimezone(UTC)  # IST midnight, like Kite
            db.add(
                Candle(
                    instrument_id=inst.id,
                    interval="day",
                    ts=ts,
                    open=close,
                    high=close * 1.01,
                    low=close * 0.99,
                    close=close,
                    volume=1_000_000,
                )
            )
            added += 1
        d -= timedelta(days=1)
    return inst


@pytest.fixture()
def world(db_session, monkeypatch):
    monkeypatch.setattr(
        deployable,
        "current_deployable",
        lambda db: deployable.DeployableCapital(regime="strong", fraction=1.0, context_available=True),
    )
    if db_session.get(SystemState, 1) is None:
        db_session.add(SystemState(id=1, new_entries_enabled=True, exits_enabled=True))
    if not db_session.query(Instrument).filter_by(tradingsymbol=settings.BENCHMARK_INDEX_SYMBOL).count():
        _add_bars(db_session, settings.BENCHMARK_INDEX_SYMBOL, 994000, FRI, n=260, close=25_000.0)
    db_session.commit()
    return db_session


def _likes(symbol):
    def run(view):
        return c.Contribution(
            opinions=(
                c.Opinion(
                    source="model",
                    symbol=symbol,
                    stance=0.8,
                    confidence=0.8,
                    probability=0.9,
                    threshold=0.6,
                    reasons=("Liked",),
                ),
            )
        )

    return make_module("M90", Step.REASON, writes=("Opinion@1",), run=run, kind="plugin")


def _run(db, symbol, as_of=AS_OF):
    req = c.RunRequest(run_id="t", kind="nightly", as_of=as_of, universe=(symbol,), live=True)
    return execute(
        req, DatedReader(db, as_of=as_of, live=True), registry(DataGateway, RiskGate, _likes(symbol)), {}
    )


def test_m01_is_registered():
    import swing_trade_ml.brain.modules  # noqa: F401

    assert REGISTRY.get("M01") is DataGateway


def test_fresh_data_lets_an_approved_stock_become_a_trade(world):
    _add_bars(world, "M01FRESH", 994001, FRI)
    world.commit()
    ctx = _run(world, "M01FRESH")
    assert ctx.quality["M01FRESH"].fresh and ctx.quality["M01FRESH"].last_bar_date == "2026-09-25"
    assert ctx.quality["*"].fresh
    assert ctx.decisions["M01FRESH"].word is c.IdeaWord.TRADE


def test_stale_data_is_refused_and_stops_new_trades(world):
    _add_bars(world, "M01STALE", 994002, date(2026, 9, 18))
    world.commit()
    ctx = _run(world, "M01STALE")
    assert not ctx.quality["M01STALE"].fresh
    assert ctx.verdicts["M01STALE"].rule == "DATA"
    assert ctx.decisions["M01STALE"].word is c.IdeaWord.WATCH
    assert ctx.banner.mode is c.MarketMode.NO_NEW_TRADES
    assert "not reliable" in ctx.banner.headline


def test_a_replay_only_sees_bars_up_to_its_date(world):
    _add_bars(world, "M01PAST", 994003, FRI)
    world.commit()
    as_of = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)
    ctx = _run(world, "M01PAST", as_of=as_of)
    assert ctx.quality["M01PAST"].last_bar_date == "2026-09-18"
    assert ctx.quality["M01PAST"].fresh
