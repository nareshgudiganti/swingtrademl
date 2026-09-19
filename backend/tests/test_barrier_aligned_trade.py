"""The traded trade must be the trade the model was scored on.

The model answers one question: "+8% before -4%, within 15 trading days".
Until this existed the position was then managed as something else entirely —
a 2xATR stop, a 4xATR target and a 60-day time stop — so every confidence
number in the app described a trade the system never took. These tests pin
the levels a fresh BUY signal carries to the ML_* settings the label is built
from, so the two can't drift apart again without a failure here.

evaluate() is exercised with the model, its bundle and the market-context
loaders stubbed out: the levels are the subject, not the estimator.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import SignalType
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Strategy as StrategyModel
from swing_trade_ml.strategies import ml_swing
from swing_trade_ml.strategies.ml_swing import MLSwingStrategy

LAST_CLOSE = 1_000.0


def _candles(bars: int = 280, last_close: float = LAST_CLOSE) -> pd.DataFrame:
    """A calm, gently rising series: liquid enough and quiet enough to clear
    every filter, so only the level arithmetic is under test. The ~2% daily
    swing keeps ATR14 well away from zero — an ATR-derived stop would land
    nowhere near -4%, which is the whole point."""
    closes = [last_close - (bars - 1 - i) * 0.5 for i in range(bars)]
    return pd.DataFrame(
        {
            "ts": pd.date_range("2025-01-01", periods=bars, freq="D"),
            "open": closes,
            "high": [c * 1.02 for c in closes],
            "low": [c * 0.98 for c in closes],
            "close": closes,
            "volume": [500_000] * bars,
        }
    )


@pytest.fixture
def buy_signal(monkeypatch):
    """A BUY decision from a confident model, with everything but the level
    arithmetic stubbed."""
    model = SimpleNamespace(
        name="swing_classifier",
        version="1",
        label_kind="barrier",
        target_return_pct=settings.ML_TARGET_RETURN_PCT,
        stop_return_pct=settings.ML_STOP_RETURN_PCT,
        prediction_horizon_days=settings.ML_PREDICTION_HORIZON_DAYS,
    )
    monkeypatch.setattr(ml_swing, "get_active_model", lambda db, name=None: model)
    for loader in ("load_index_candles", "load_sector_candles", "load_vix_candles",
                   "load_market_breadth"):
        monkeypatch.setattr(ml_swing, loader, lambda *a, **k: pd.DataFrame())

    def fake_build_features(d, *a, **k):
        featured = d.copy()
        featured["nifty_trend_regime"] = 1.0
        featured["f1"] = 0.5
        return featured

    monkeypatch.setattr(ml_swing, "build_features", fake_build_features)
    monkeypatch.setattr(
        ml_swing,
        "_get_bundle",
        lambda m: {
            "feature_names": ["f1"],
            "scaler": SimpleNamespace(transform=lambda x: x),
            "estimator": SimpleNamespace(predict_proba=lambda x: np.array([[0.1, 0.9]])),
        },
    )

    strategy = MLSwingStrategy(
        StrategyModel(name="barrier-test", strategy_type="ml_swing", mode="paper", params={})
    )
    decision = strategy.evaluate(
        _candles(), Instrument(instrument_token=1, tradingsymbol="TITAN"), db=None
    )
    assert decision is not None and decision.signal == SignalType.BUY
    return decision


def test_stop_is_the_models_own_minus_4_percent_not_an_atr_distance(buy_signal):
    """2xATR on this series is roughly 4% of price only by coincidence of the
    constants; the assertion is exact equality with ML_STOP_RETURN_PCT, which
    an ATR-derived stop cannot satisfy for an arbitrary instrument."""
    assert settings.ML_STOP_RETURN_PCT == 0.04
    assert buy_signal.stop_loss == pytest.approx(LAST_CLOSE * (1 - settings.ML_STOP_RETURN_PCT))


def test_final_target_is_the_models_own_plus_8_percent(buy_signal):
    assert settings.ML_TARGET_RETURN_PCT == 0.08
    assert buy_signal.take_profit == pytest.approx(LAST_CLOSE * (1 + settings.ML_TARGET_RETURN_PCT))


def test_the_levels_move_with_the_settings_not_with_the_atr(monkeypatch, buy_signal):
    """The numbers are configuration, not constants baked into the strategy."""
    monkeypatch.setattr(settings, "ML_STOP_RETURN_PCT", 0.06)
    monkeypatch.setattr(settings, "ML_TARGET_RETURN_PCT", 0.12)

    strategy = MLSwingStrategy(
        StrategyModel(name="barrier-test-2", strategy_type="ml_swing", mode="paper", params={})
    )
    decision = strategy.evaluate(
        _candles(), Instrument(instrument_token=1, tradingsymbol="TITAN"), db=None
    )

    assert decision.stop_loss == pytest.approx(LAST_CLOSE * 0.94)
    assert decision.take_profit == pytest.approx(LAST_CLOSE * 1.12)


def test_the_signal_carries_the_models_horizon(buy_signal):
    assert buy_signal.horizon_days == settings.ML_PREDICTION_HORIZON_DAYS


def test_first_target_sits_between_the_stop_and_the_final_target():
    """+5% is the level half the position is banked at; it has to be a real
    intermediate point, not at or past where the whole position exits."""
    assert settings.ML_FIRST_TARGET_PCT == 0.05
    assert 0 < settings.ML_FIRST_TARGET_PCT < settings.ML_TARGET_RETURN_PCT
