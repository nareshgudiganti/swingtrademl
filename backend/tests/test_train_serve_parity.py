"""#247: the same stock on the same day gets identical model inputs from training and from scoring.

Training (`ml.dataset.build_training_dataset`) builds every day of a stock's history in one go. Scoring
(`ml.predict.predict_instrument`) loads only the newest 400 bars and builds the newest day. If the two ever
disagree for the same day, the model is scored on inputs unlike those it learned from. Three things are
checked for four days near the end of the data:

- every named input is the same;
- the vector the model actually receives is the training row in the model's input ORDER (a model reads its
  inputs by position, so a reordering would silently feed every input to the wrong weight);
- on a day when the benchmark and VIX have no candle (the stock does), both paths join the previous day's
  market context, never a later day's (a forward join would look ahead).

Synthetic candles only; nothing here reads or writes a model, evidence or frozen file.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import delete

from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.ml import market_context, predict
from swing_trade_ml.ml.dataset import build_training_dataset
from swing_trade_ml.ml.features import FEATURE_COLUMNS
from test_features import _synthetic_ohlcv

SYMBOL = "ZZPARITY"  # not in the sector map, so its peer group is the benchmark itself
BARS = 900  # well over the 400 bars scoring loads
SERVING_WINDOW = 400
HORIZON = 15  # the label looks this far ahead, so the last days have no training row
FIRST_DAY = pd.Timestamp("2024-01-01", tz="UTC")  # first synthetic day (test_features._synthetic_ohlcv)
# One of the four compared days (position 878 of 900): the benchmark and VIX have no candle on it.
GAP_DAY = FIRST_DAY + pd.Timedelta(days=878)
# Inputs that come straight from the benchmark's or VIX's own series, merged onto the stock by date.
CONTEXT_INPUTS = ["nifty_volatility_20", "nifty_trend_regime", "vix_change_5d", "vix_percentile_rank"]


class _IdentityScaler:
    def transform(self, x):
        return x


class _RecordingModel:
    """Returns a constant and keeps every vector it was asked to score, so the vector can be compared."""

    def __init__(self) -> None:
        self.received: list[np.ndarray] = []

    def predict_proba(self, x):
        self.received.append(np.array(x, dtype=float))
        return np.array([[0.4, 0.6]])


class _FakeModel:
    id = 1
    name = "parity-test"
    version = 1
    artifact_path = "synthetic"


def _add_series(db, token: int, symbol: str, frame: pd.DataFrame, *, watchlisted: bool = False) -> Instrument:
    inst = Instrument(
        instrument_token=token,
        tradingsymbol=symbol,
        exchange="NSE",
        segment="NSE",
        instrument_type="EQ",
        is_active=True,
        is_watchlisted=watchlisted,
    )
    db.add(inst)
    db.flush()
    db.add_all(
        Candle(
            instrument_id=inst.id,
            interval="day",
            ts=row.ts.to_pydatetime(),
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            volume=int(row.volume),
        )
        for row in frame.itertuples()
    )
    db.flush()
    return inst


def _install_model(monkeypatch, estimator, feature_names) -> None:
    monkeypatch.setattr(
        predict,
        "_get_bundle",
        lambda model: {
            "feature_names": list(feature_names),
            "scaler": _IdentityScaler(),
            "estimator": estimator,
        },
    )


@pytest.fixture()
def world(db_session, monkeypatch):
    """A stock, the benchmark and INDIA VIX on the same 900 days, except that the benchmark and VIX have no
    candle on GAP_DAY while the stock does; and a stand-in model that records the vectors it is given."""
    market_context.clear_cache()
    stock = _add_series(db_session, 9_100_001, SYMBOL, _synthetic_ohlcv(11, BARS), watchlisted=True)
    benchmark = _add_series(
        db_session, 9_100_002, settings.BENCHMARK_INDEX_SYMBOL, _synthetic_ohlcv(12, BARS)
    )
    vix = _add_series(db_session, 9_100_003, "INDIA VIX", _synthetic_ohlcv(13, BARS))
    gap = GAP_DAY.to_pydatetime()
    db_session.execute(
        delete(Candle).where(Candle.instrument_id.in_([benchmark.id, vix.id]), Candle.ts == gap)
    )
    db_session.flush()
    estimator = _RecordingModel()
    _install_model(monkeypatch, estimator, FEATURE_COLUMNS)
    yield SimpleNamespace(stock=stock, estimator=estimator, monkeypatch=monkeypatch)
    market_context.clear_cache()


def _training_rows(db) -> pd.DataFrame:
    market_context.clear_cache()
    data = build_training_dataset(db, symbols=[SYMBOL], horizon_days=HORIZON, min_rows=300)
    assert not data.empty, "the synthetic stock produced no training rows"
    data["ts"] = pd.to_datetime(data["ts"], utc=True)
    return data.set_index("ts")


def _score_as_of(db, world, last_day: pd.Timestamp):
    """Scoring as it runs live on `last_day`: that day is the newest bar in the database."""
    cut = last_day.to_pydatetime()
    db.execute(delete(Candle).where(Candle.ts > cut))
    db.flush()
    kept = db.query(Candle).where(Candle.instrument_id == world.stock.id).count()
    assert kept > SERVING_WINDOW, "the day needs more history than scoring loads, or the window is untested"
    market_context.clear_cache()
    result = predict.predict_instrument(db, world.stock, _FakeModel())
    assert result is not None, "scoring refused a day that has full history"
    assert pd.Timestamp(result.ts) == last_day
    assert len(world.estimator.received) >= 1
    return result.features, world.estimator.received[-1][0]


def _days(training: pd.DataFrame) -> list[pd.Timestamp]:
    """Four days near the end of the data, newest first (the database is cut back to each in turn)."""
    days = list(training.index[-HORIZON::4])[::-1][:4]
    assert len(days) == 4
    assert GAP_DAY in days, "the day without benchmark and VIX candles must be one of the compared days"
    return days


def _compare(db, world):
    """Two dicts. First: {day: {input: (training, scoring)}} for named inputs that differ. Second:
    {day: positions} where the vector the model received differs from the training row in trained order."""
    training = _training_rows(db)
    by_name: dict[str, dict[str, tuple[float, float]]] = {}
    by_position: dict[str, list[int]] = {}
    for day in _days(training):
        row = training.loc[day, FEATURE_COLUMNS].astype(float)
        features, vector = _score_as_of(db, world, day)
        key = f"{day:%Y-%m-%d}"
        by_name[key] = {
            name: (float(row[name]), features[name])
            for name in FEATURE_COLUMNS
            if not np.isclose(row[name], features[name], rtol=1e-9, atol=1e-12)
        }
        assert vector.shape == (len(FEATURE_COLUMNS),)
        by_position[key] = [
            i
            for i, expected in enumerate(row.to_numpy(float))
            if not np.isclose(expected, vector[i], rtol=1e-9, atol=1e-12)
        ]
    return by_name, by_position


def _failures(db, world):
    by_name, by_position = _compare(db, world)
    return (
        {day: names for day, names in by_name.items() if names},
        {day: positions for day, positions in by_position.items() if positions},
    )


def test_the_same_stock_and_day_give_identical_model_inputs_in_training_and_in_scoring(db_session, world):
    named, ordered = _failures(db_session, world)
    assert not named, f"inputs differ between training and scoring: {named}"
    assert not ordered, f"the model's vector is not the training row in its input order: {ordered}"


def test_a_day_without_market_candles_joins_the_previous_days_context_not_a_later_one(db_session, world):
    """The stock has a candle on GAP_DAY but the benchmark and VIX do not. Both paths must use the previous
    day's market context (a backward join). The training row for that day then carries exactly the
    context of the day before."""
    training = _training_rows(db_session)
    before = GAP_DAY - pd.Timedelta(days=1)
    assert before in training.index
    for name in CONTEXT_INPUTS:
        on_gap, on_before = training.loc[GAP_DAY, name], training.loc[before, name]
        assert np.isclose(on_gap, on_before, rtol=1e-12, atol=1e-12), name
    named, ordered = _failures(db_session, world)
    assert not named and not ordered


def test_the_comparison_can_fail_when_an_input_is_built_differently(db_session, world):
    """One input nudged inside scoring, in memory only: the named and the positional check both notice."""
    real = predict.build_features

    def nudged(*args, **kwargs):
        frame = real(*args, **kwargs).copy()
        frame[FEATURE_COLUMNS[0]] = frame[FEATURE_COLUMNS[0]] * 1.01 + 0.001
        return frame

    world.monkeypatch.setattr(predict, "build_features", nudged)
    named, ordered = _failures(db_session, world)
    assert len(named) == 4 and all(set(names) == {FEATURE_COLUMNS[0]} for names in named.values())
    assert len(ordered) == 4 and all(positions == [0] for positions in ordered.values())


def test_reversed_input_order_is_caught(db_session, world):
    """A model whose stored input order is the reverse of the order it was trained in receives a reversed
    vector. Every name is still right, so only the positional check can see it."""
    _install_model(world.monkeypatch, world.estimator, list(reversed(FEATURE_COLUMNS)))
    named, ordered = _failures(db_session, world)
    assert not named, "the named inputs are all still correct"
    assert len(ordered) == 4
    assert all(len(positions) > len(FEATURE_COLUMNS) // 2 for positions in ordered.values())


def test_a_forward_join_of_the_market_context_is_caught(db_session, world):
    """If the market series were joined forward, the training row for GAP_DAY would take the NEXT day's
    benchmark and VIX, while scoring on GAP_DAY (when no later day exists yet) cannot. The comparison, made
    possible by the day without market candles, must fail."""
    real_merge = pd.merge_asof

    def forward(left, right, **kwargs):
        kwargs["direction"] = "forward"
        return real_merge(left, right, **kwargs)

    world.monkeypatch.setattr(pd, "merge_asof", forward)
    with pytest.raises(AssertionError, match="refused a day"):
        _failures(db_session, world)
