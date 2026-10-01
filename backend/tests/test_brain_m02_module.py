"""M02 against the database: model features from bars that end at the run's
date, nothing for intraday runs, and nightly snapshots stored once per day."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import numpy as np
import pytest

from brain_fakes import registry
from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain import service
from swing_trade_ml.brain.module import REGISTRY
from swing_trade_ml.brain.modules.m01_quality.quality import IST, is_trading_day
from swing_trade_ml.brain.modules.m02_perception.module import Perception
from swing_trade_ml.brain.reader import DatedReader
from swing_trade_ml.brain.runner import execute
from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.brain import FeatureSnapshot
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.ml import market_context
from swing_trade_ml.ml.features import FEATURE_COLUMNS

LAST = date(2026, 9, 25)
AS_OF = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)  # 17:30 IST


def _series(db, symbol: str, token: int, *, watch: bool, seed: int, start: float, n: int = 420):
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
    closes = start * np.cumprod(1 + rng.normal(0.0004, 0.014, n))
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
    return inst


@pytest.fixture()
def market(db_session):
    market_context.clear_cache()
    _series(db_session, "M02STOCK", 996001, watch=True, seed=11, start=500.0)
    _series(db_session, settings.BENCHMARK_INDEX_SYMBOL, 996002, watch=False, seed=12, start=25_000.0)
    _series(db_session, "INDIA VIX", 996003, watch=False, seed=13, start=14.0)
    db_session.commit()
    yield
    market_context.clear_cache()


def _run(db, kind="nightly", as_of=AS_OF, holdings=()):
    req = c.RunRequest(
        run_id="t", kind=kind, as_of=as_of, universe=() if kind == "intraday" else ("M02STOCK",), live=True
    )
    reader = DatedReader(db, as_of=as_of, live=True)
    if holdings:
        reader.holdings = lambda book: holdings  # type: ignore[method-assign]
    return execute(req, reader, registry(Perception), {})


def test_m02_is_registered():
    import swing_trade_ml.brain.modules  # noqa: F401

    assert REGISTRY.get("M02") is Perception


def test_a_nightly_run_gives_the_model_features(db_session, market):
    snap = _run(db_session).snapshots["M02STOCK"]
    assert [n for n, _ in snap.features] == list(FEATURE_COLUMNS)
    assert snap.as_of == "2026-09-25" and snap.feature_set_version


def test_a_replay_stops_at_its_own_date(db_session, market):
    as_of = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)
    snap = _run(db_session, as_of=as_of).snapshots["M02STOCK"]
    assert snap.as_of == "2026-09-18"


def test_intraday_runs_skip_features_and_keep_the_price(db_session, market):
    held = (c.Holding(symbol="M02STOCK", qty=5, avg_price=480.0),)
    snap = _run(db_session, kind="intraday", holdings=held).snapshots["M02STOCK"]
    assert snap.features == () and snap.close > 0


def test_m02_asks_the_reader_to_refresh_a_stale_market_cache(db_session, market, monkeypatch):
    """M02 must not clear v1's shared cache on every run (the 15:45 scan may be
    reading it); it asks the reader, which clears only when the cache is behind."""
    calls = []
    monkeypatch.setattr(DatedReader, "refresh_context_if_stale", lambda self: calls.append(1))
    _run(db_session)
    assert calls

# --- storage ---------------------------------------------------------------


def test_nightly_snapshots_are_stored_once_per_day(db_session, market, monkeypatch):
    monkeypatch.setattr(service, "REGISTRY", registry(Perception))
    for _ in range(2):
        service.run_brain(
            db_session, kind="nightly", as_of=AS_OF, symbols=["M02STOCK"], registry=service.REGISTRY
        )
    rows = db_session.query(FeatureSnapshot).filter_by(symbol="M02STOCK").all()
    assert len(rows) == 1
    assert rows[0].bar_date == LAST and len(rows[0].features) == len(FEATURE_COLUMNS)


def test_why_runs_do_not_store_snapshots(db_session, market):
    service.run_brain(db_session, kind="why", symbols=["M02STOCK"], registry=registry(Perception))
    assert db_session.query(FeatureSnapshot).filter_by(symbol="M02STOCK").count() == 0
