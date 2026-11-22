"""#247: the same stock on the same day gets identical model inputs from training and from scoring.

Training (`ml.dataset.build_training_dataset`) builds every day of a stock's history in one go. Scoring
(`ml.predict.predict_instrument`) loads only the newest 400 bars and builds the newest day. If the two ever
disagree for the same day, the model is scored on inputs unlike those it learned from. Synthetic candles only;
nothing here reads or writes a model, evidence or frozen file.
"""

from __future__ import annotations

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


class _IdentityScaler:
    def transform(self, x):
        return x


class _ConstantModel:
    def predict_proba(self, x):
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


@pytest.fixture()
def world(db_session, monkeypatch):
    """A stock, the benchmark and INDIA VIX on the same 900 days, and a stand-in model for scoring."""
    market_context.clear_cache()
    stock = _add_series(db_session, 9_100_001, SYMBOL, _synthetic_ohlcv(11, BARS), watchlisted=True)
    _add_series(db_session, 9_100_002, settings.BENCHMARK_INDEX_SYMBOL, _synthetic_ohlcv(12, BARS))
    _add_series(db_session, 9_100_003, "INDIA VIX", _synthetic_ohlcv(13, BARS))
    monkeypatch.setattr(
        predict,
        "_get_bundle",
        lambda model: {
            "feature_names": list(FEATURE_COLUMNS),
            "scaler": _IdentityScaler(),
            "estimator": _ConstantModel(),
        },
    )
    yield stock
    market_context.clear_cache()


def _training_rows(db) -> pd.DataFrame:
    market_context.clear_cache()
    data = build_training_dataset(db, symbols=[SYMBOL], horizon_days=HORIZON, min_rows=300)
    assert not data.empty, "the synthetic stock produced no training rows"
    data["ts"] = pd.to_datetime(data["ts"], utc=True)
    return data.set_index("ts")


def _scored_inputs_as_of(db, stock: Instrument, last_day: pd.Timestamp) -> dict[str, float]:
    """Scoring as it runs live on `last_day`: that day is the newest bar in the database."""
    cut = last_day.to_pydatetime()
    db.execute(delete(Candle).where(Candle.ts > cut))
    db.flush()
    kept = db.query(Candle).where(Candle.instrument_id == stock.id).count()
    assert kept > SERVING_WINDOW, "the day needs more history than scoring loads, or the window is untested"
    market_context.clear_cache()
    result = predict.predict_instrument(db, stock, _FakeModel())
    assert result is not None, "scoring refused a day that has full history"
    assert pd.Timestamp(result.ts) == last_day
    return result.features


def _differences(db, stock: Instrument) -> dict[str, dict[str, tuple[float, float]]]:
    """For four days near the end of the data: {day: {input: (training, scoring)}} for inputs that differ."""
    training = _training_rows(db)
    # Newest first, because the database is cut back to each day in turn for scoring.
    days = list(training.index[-HORIZON::4])[::-1][:4]
    assert len(days) == 4
    expected = {d: training.loc[d, FEATURE_COLUMNS].astype(float) for d in days}
    out: dict[str, dict[str, tuple[float, float]]] = {}
    for day in days:
        scored = _scored_inputs_as_of(db, stock, day)
        out[f"{day:%Y-%m-%d}"] = {
            name: (float(expected[day][name]), scored[name])
            for name in FEATURE_COLUMNS
            if not np.isclose(expected[day][name], scored[name], rtol=1e-9, atol=1e-12)
        }
    return out


def test_the_same_stock_and_day_give_identical_model_inputs_in_training_and_in_scoring(db_session, world):
    differing = {day: names for day, names in _differences(db_session, world).items() if names}
    assert not differing, f"inputs differ between training and scoring: {differing}"


def test_the_comparison_can_fail(db_session, world, monkeypatch):
    """The same check must notice when scoring builds an input differently (one input nudged in memory)."""
    real = predict.build_features

    def nudged(*args, **kwargs):
        frame = real(*args, **kwargs).copy()
        frame[FEATURE_COLUMNS[0]] = frame[FEATURE_COLUMNS[0]] * 1.01 + 0.001
        return frame

    monkeypatch.setattr(predict, "build_features", nudged)
    differing = {day: names for day, names in _differences(db_session, world).items() if names}
    assert len(differing) == 4
    assert all(set(names) == {FEATURE_COLUMNS[0]} for names in differing.values())
