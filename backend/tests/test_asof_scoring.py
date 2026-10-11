"""As-of scoring needs features that only use data up to and including each day."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.ml import market_context
from swing_trade_ml.ml.dataset import load_candles
from swing_trade_ml.ml.features import FEATURE_COLUMNS, build_features
from swing_trade_ml.ml.market_context import (
    load_index_candles,
    load_market_breadth,
    load_sector_candles,
    load_vix_candles,
)
from swing_trade_ml.ml.sector_map import get_sector_index

IST = ZoneInfo("Asia/Kolkata")
LAST = date(2026, 9, 25)


def _ts(day: date) -> datetime:
    return datetime.combine(day, time(0, 0), tzinfo=IST).astimezone(UTC)


def _series(db, symbol, token, start_price, seed, *, watch=True, bars=420):
    inst = Instrument(
        instrument_token=token, tradingsymbol=symbol, exchange="NSE", is_watchlisted=watch, is_active=True
    )
    db.add(inst)
    db.flush()
    rng = np.random.default_rng(seed)
    price, day, out = start_price, LAST - timedelta(days=int(bars * 1.5)), []
    while day <= LAST:
        if day.weekday() < 5:
            price *= 1 + rng.normal(0.0005, 0.012)
            out.append((day, price))
        day += timedelta(days=1)
    for d, p in out:
        db.add(
            Candle(
                instrument_id=inst.id,
                interval="day",
                ts=_ts(d),
                open=p * 0.998,
                high=p * 1.01,
                low=p * 0.99,
                close=p,
                volume=int(100000 + rng.integers(0, 50000)),
            )
        )
    db.commit()
    return inst, [d for d, _ in out]


@pytest.fixture()
def market(db_session):
    market_context.clear_cache()
    inst, days = _series(db_session, "ASOFA", 996001, 100.0, 1)
    _series(db_session, "ASOFB", 996002, 250.0, 2)
    _series(db_session, settings.BENCHMARK_INDEX_SYMBOL, 996099, 20000.0, 3, watch=False)
    _series(db_session, "INDIA VIX", 996098, 15.0, 4, watch=False)
    yield inst, days
    market_context.clear_cache()


def _features(db, inst, upto: pd.Timestamp | None):
    raw = load_candles(db, inst.id, "day")
    if upto is not None:
        raw = raw[raw["ts"] <= upto].reset_index(drop=True)
    return build_features(
        raw,
        load_index_candles(db, "day", upto),
        load_sector_candles(db, get_sector_index(inst.tradingsymbol), "day", upto),
        load_vix_candles(db, "day", upto),
        load_market_breadth(db, "day", upto),
    )


def test_features_for_a_day_do_not_depend_on_later_data(db_session, market):
    """The row for day D built from everything must equal the row built from data cut at D."""
    inst, days = market
    full = _features(db_session, inst, None)
    for d in (days[-40], days[-25], days[-10]):
        cut_ts = pd.Timestamp(_ts(d))
        cut = _features(db_session, inst, cut_ts)
        a = full[full["ts"] == cut_ts][FEATURE_COLUMNS].to_numpy(dtype=float)
        b = cut.iloc[[-1]][FEATURE_COLUMNS].to_numpy(dtype=float)
        assert a.shape == b.shape == (1, len(FEATURE_COLUMNS))
        assert not np.isnan(a).all(), "the row is all NaN, so comparing it proves nothing"
        assert np.allclose(a, b, equal_nan=True), f"features for {d} changed when later bars were added"


class _FakeEstimator:
    def predict_proba(self, x):
        p = np.full(len(x), 0.5)
        return np.column_stack([1 - p, p])


class _FakeScaler:
    def transform(self, x):
        return x


def _fake_model(monkeypatch, model_id=991):
    from swing_trade_ml.ml import asof

    class M:
        id = model_id
        name = "m"
        version = "1"

        def __init__(self):
            self.metrics = {"asof_cutoff": "2026-01-01"}

    monkeypatch.setattr(
        asof,
        "_get_bundle",
        lambda m: {"feature_names": FEATURE_COLUMNS, "scaler": _FakeScaler(), "estimator": _FakeEstimator()},
    )
    asof.clear_cache()
    return M()


def test_score_series_gives_one_score_per_day_after_the_cutoff_only(db_session, market, monkeypatch):
    from swing_trade_ml.ml.asof import score_series

    inst, days = market
    scores = score_series(db_session, inst, _fake_model(monkeypatch), after=days[-6])
    assert set(scores) == set(days[-5:])
    assert all(0.0 <= p <= 1.0 for p in scores.values())


def test_a_stock_with_too_little_history_gets_no_score(db_session, market, monkeypatch):
    from swing_trade_ml.ml.asof import score_series

    inst, _ = _series(db_session, "ASOFSHORT", 996003, 50.0, 5, bars=120)
    assert score_series(db_session, inst, _fake_model(monkeypatch, 992), after=date(2026, 1, 1)) == {}


def test_scores_are_cached_per_model_and_stock(db_session, market, monkeypatch):
    from swing_trade_ml.ml import asof

    inst, days = market
    model = _fake_model(monkeypatch)
    first = asof.score_series(db_session, inst, model, after=days[-6])

    def boom(*a, **k):
        raise AssertionError("recomputed")

    monkeypatch.setattr(asof, "load_candles", boom)
    assert asof.score_series(db_session, inst, model, after=days[-6]) == first  # served from the cache
    other = _fake_model(monkeypatch, 993)  # a different model never shares it
    with pytest.raises(AssertionError):
        asof.score_series(db_session, inst, other, after=days[-6])
