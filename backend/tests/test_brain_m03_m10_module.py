"""M03 (state engine) and M10 (market brain) against the database."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import numpy as np
import pandas as pd
import pytest

from brain_fakes import registry
from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.module import REGISTRY, Step
from swing_trade_ml.brain.modules.m01_quality.quality import IST, is_trading_day
from swing_trade_ml.brain.modules.m03_state.module import StateEngine
from swing_trade_ml.brain.modules.m03_state.state import stock_state
from swing_trade_ml.brain.modules.m10_market.module import MarketBrain
from swing_trade_ml.brain.reader import DatedReader
from swing_trade_ml.brain.runner import execute
from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.feeds import InstitutionalFlow
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.safety import SystemState
from swing_trade_ml.ml import market_context

LAST = date(2026, 9, 25)
AS_OF = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


# --- pure stock state ------------------------------------------------------------


def test_stock_state_reads_trend_strength_and_distance_from_high():
    closes = pd.Series(np.linspace(100, 200, 300))
    index = pd.Series(np.linspace(100, 120, 300))
    s = stock_state("ABC", closes, index)
    assert s.trend == "up"
    assert s.rel_strength_vs_nifty > 0  # beat NIFTY over 60 days
    assert s.dist_from_52w_high_pct == pytest.approx(0.0)


def test_stock_state_with_little_history_is_unknown():
    s = stock_state("ABC", pd.Series(np.linspace(100, 110, 50)), pd.Series(np.linspace(1, 2, 50)))
    assert s.trend == "unknown" and s.rel_strength_vs_nifty is None


def test_a_falling_stock_reads_down():
    s = stock_state("ABC", pd.Series(np.linspace(200, 100, 300)), pd.Series(np.linspace(100, 120, 300)))
    assert s.trend == "down" and s.dist_from_52w_high_pct < -0.3


# --- database -----------------------------------------------------------------


def _series(db, symbol, token, *, watch, seed, start, drift=0.0008, n=420):
    inst = db.query(Instrument).filter_by(tradingsymbol=symbol).one_or_none()
    if inst is None:
        inst = Instrument(
            instrument_token=token, tradingsymbol=symbol, exchange="NSE", is_watchlisted=watch, is_active=True
        )
        db.add(inst)
        db.flush()
    rng = np.random.default_rng(seed)
    days, d = [], LAST
    while len(days) < n:
        if is_trading_day(d):
            days.append(d)
        d -= timedelta(days=1)
    closes = start * np.cumprod(1 + drift + rng.normal(0, 0.006, n))
    for day, close in zip(sorted(days), closes, strict=True):
        ts = datetime.combine(day, time(0, 0), tzinfo=IST).astimezone(UTC)
        db.add(
            Candle(
                instrument_id=inst.id,
                interval="day",
                ts=ts,
                open=close,
                high=close * 1.01,
                low=close * 0.99,
                close=close,
                volume=100_000,
            )
        )


@pytest.fixture()
def market(db_session):
    market_context.clear_cache()
    if db_session.get(SystemState, 1) is None:
        db_session.add(SystemState(id=1, new_entries_enabled=True, exits_enabled=True))
    _series(db_session, "M03STOCK", 997001, watch=True, seed=21, start=500.0)
    _series(db_session, settings.BENCHMARK_INDEX_SYMBOL, 997002, watch=False, seed=22, start=25_000.0)
    _series(db_session, "INDIA VIX", 997003, watch=False, seed=23, start=14.0, drift=0.0)
    db_session.commit()
    yield
    market_context.clear_cache()


def _run(db, *modules, as_of=AS_OF, live=True):
    req = c.RunRequest(run_id="t", kind="nightly", as_of=as_of, universe=("M03STOCK",), live=live)
    return execute(req, DatedReader(db, as_of=as_of, live=live), registry(*modules), {})


def test_both_modules_are_registered_in_the_state_step():
    import swing_trade_ml.brain.modules  # noqa: F401

    assert REGISTRY.get("M03") is StateEngine and REGISTRY.get("M10") is MarketBrain
    assert MarketBrain.manifest.step is Step.STATE and MarketBrain.manifest.kind == "plugin"


def test_market_brain_sets_the_mode_with_reasons_after_the_state_engine(db_session, market):
    ctx = _run(db_session, StateEngine, MarketBrain)
    assert ctx.market.trend == "up"
    assert ctx.market.mode is not None and ctx.market.reasons
    assert ctx.banner.headline == ctx.market.reasons[0] or ctx.banner.mode is c.MarketMode.NO_NEW_TRADES


def test_market_inputs_end_at_the_run_date(db_session, market):
    reader = DatedReader(db_session, as_of=datetime(2026, 9, 18, 12, 0, tzinfo=UTC), live=False)
    vix = reader.vix_closes()
    expected = (
        db_session.query(Candle.close)
        .join(Instrument)
        .filter(
            Instrument.tradingsymbol == "INDIA VIX", Candle.ts <= datetime(2026, 9, 18, 12, 0, tzinfo=UTC)
        )
        .order_by(Candle.ts.desc())
        .first()[0]
    )
    assert vix.iloc[-1] == pytest.approx(expected)


def test_fii_flows_are_read_up_to_the_run_date(db_session, market):
    for i in range(6):
        db_session.add(
            InstitutionalFlow(
                trade_date=LAST - timedelta(days=i),
                category="FII",
                buy_value=0,
                sell_value=100,
                net_value=-100.0 - i,
            )
        )
    db_session.add(
        InstitutionalFlow(trade_date=LAST, category="DII", buy_value=100, sell_value=0, net_value=100)
    )
    db_session.commit()
    flows = DatedReader(db_session, as_of=AS_OF, live=True).fii_net(20)
    assert flows[-1] == -100.0 and len(flows) == 6


def test_state_engine_reports_stock_portfolio_and_system(db_session, market):
    ctx = _run(db_session, StateEngine)
    assert ctx.stocks["M03STOCK"].trend in {"up", "down", "sideways"}
    assert ctx.portfolio.value is not None and ctx.portfolio.free_slots is not None
    assert ctx.system.entries_halted is False
    assert ctx.market.mode is not None  # filled by the fallback when M10 is off


def test_replays_do_not_report_todays_account(db_session, market):
    ctx = _run(db_session, StateEngine, live=False)
    assert ctx.portfolio.value is None
