"""The "real question" calibrated-model switch is OFF by default and reversible.

No database: the model lookup and the market loaders are stubbed. The point is
(1) with the switch off nothing about model choice, buy bar or weakness line
changes, (2) with it on strategies are scored by `<model_name><suffix>` with
their own calibrated bar, (3) a missing calibrated model means no signal at all
(never a quiet fall-back to the old model), and (4) turning it off again fully
restores the old behaviour. Order placement, sizing, stops and limits are not
touched by the switch: the BUY levels stay the ML_* settings.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from swing_trade_ml.core.config import Settings, settings
from swing_trade_ml.core.enums import SignalType
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Strategy as StrategyModel
from swing_trade_ml.ml import predict, real_question
from swing_trade_ml.services.execution import confidence_decay_status
from swing_trade_ml.services.exit_policy import exit_confidence_for
from swing_trade_ml.services.score_history import score_band
from swing_trade_ml.strategies import ml_swing
from swing_trade_ml.strategies.ml_swing import MLSwingStrategy


def _candles(bars: int = 280, last_close: float = 1_000.0) -> pd.DataFrame:
    """Same calm, gently rising series as test_barrier_aligned_trade. Copied,
    not imported: `tests` is not a package, so `from tests...` breaks in CI."""
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


def _on(monkeypatch, suffix="_barrier_cal"):
    monkeypatch.setattr(settings, "ML_REAL_QUESTION_SUFFIX", suffix)


def test_default_is_off():
    assert Settings.model_fields["ML_REAL_QUESTION_SUFFIX"].default == ""
    assert settings.ML_REAL_QUESTION_SUFFIX == ""
    assert real_question.enabled() is False


def test_off_changes_nothing(monkeypatch):
    assert real_question.resolve_model_name("swing_classifier") == "swing_classifier"
    assert real_question.resolve_model_name(None) is None
    assert real_question.min_confidence() == settings.ML_MIN_CONFIDENCE == 0.60
    assert real_question.exit_confidence() == settings.ML_EXIT_CONFIDENCE == 0.35
    assert exit_confidence_for(None) == settings.ML_EXIT_CONFIDENCE
    assert score_band(0.62, 0.35) == "strong"


def test_on_names_and_bars_follow_the_calibrated_model(monkeypatch):
    _on(monkeypatch)
    assert real_question.resolve_model_name("swing_classifier") == "swing_classifier_barrier_cal"
    assert real_question.resolve_model_name("swing_classifier_midcap") == (
        "swing_classifier_midcap_barrier_cal"
    )
    # Idempotent: an already-suffixed name is not suffixed twice.
    assert real_question.resolve_model_name("swing_classifier_barrier_cal") == (
        "swing_classifier_barrier_cal"
    )
    assert real_question.min_confidence() == settings.ML_REAL_QUESTION_MIN_CONFIDENCE
    assert exit_confidence_for(None) == settings.ML_REAL_QUESTION_EXIT_CONFIDENCE
    # A calibrated 0.45 is a "strong" idea; under the old 0.60 bar it would not be.
    assert score_band(0.45, exit_confidence_for(None)) == "strong"
    # An explicit per-strategy override still wins.
    row = SimpleNamespace(params={"exit_confidence": 0.2})
    assert exit_confidence_for(row) == 0.2


def test_turning_it_off_again_restores_old_behaviour(monkeypatch):
    _on(monkeypatch)
    assert real_question.enabled()
    monkeypatch.setattr(settings, "ML_REAL_QUESTION_SUFFIX", "")
    assert real_question.resolve_model_name("swing_classifier") == "swing_classifier"
    assert real_question.min_confidence() == 0.60
    assert exit_confidence_for(None) == 0.35


def test_decay_alert_uses_the_active_bar(monkeypatch):
    # Old bar: entry 0.70 -> now 0.45 is inside the weak zone (<0.475) and a 0.25 drop.
    args = dict(entry_confidence=0.70, current_confidence=0.45, exit_confidence=0.35,
                already_alerted=False)
    assert confidence_decay_status(**args) == "alert"
    # Calibrated mode: a 0.45 score is healthy (bar 0.40, weak zone < 0.25), no alert.
    _on(monkeypatch)
    assert confidence_decay_status(**{**args, "exit_confidence": 0.10}) == "none"


def _strategy():
    return MLSwingStrategy(
        StrategyModel(name="t", strategy_type="ml_swing", mode="paper", params={})
    )


def _stub_market(monkeypatch, probability, seen):
    def fake_get_active_model(db, name=None):
        seen.append(name)
        if name == "swing_classifier_barrier_cal" or name == "swing_classifier":
            return SimpleNamespace(
                name=name, version="1", label_kind="barrier",
                target_return_pct=0.08, stop_return_pct=0.04, prediction_horizon_days=15,
            )
        return None

    monkeypatch.setattr(ml_swing, "get_active_model", fake_get_active_model)
    for loader in ("load_index_candles", "load_sector_candles", "load_vix_candles",
                   "load_market_breadth"):
        monkeypatch.setattr(ml_swing, loader, lambda *a, **k: pd.DataFrame())

    def fake_features(d, *a, **k):
        f = d.copy()
        f["nifty_trend_regime"] = 1.0
        f["f1"] = 0.5
        return f

    monkeypatch.setattr(ml_swing, "build_features", fake_features)
    monkeypatch.setattr(
        ml_swing, "_get_bundle",
        lambda m: {
            "feature_names": ["f1"],
            "scaler": SimpleNamespace(transform=lambda x: x),
            "estimator": SimpleNamespace(
                predict_proba=lambda x: np.array([[1 - probability, probability]])
            ),
        },
    )


def _decide(probability):
    return _strategy().evaluate(
        _candles(), Instrument(instrument_token=1, tradingsymbol="TITAN"), db=None
    )


def test_strategy_off_uses_old_model_and_old_bar(monkeypatch):
    seen: list = []
    _stub_market(monkeypatch, 0.45, seen)
    d = _decide(0.45)
    assert seen == ["swing_classifier"]
    assert d.signal == SignalType.HOLD  # 0.45 < 0.60


def test_strategy_on_uses_calibrated_model_and_bar_but_same_levels(monkeypatch):
    _on(monkeypatch)
    seen: list = []
    _stub_market(monkeypatch, 0.45, seen)
    d = _decide(0.45)
    assert seen == ["swing_classifier_barrier_cal"]
    assert d.signal == SignalType.BUY
    close = float(_candles()["close"].iloc[-1])
    # Stops/targets are untouched by the switch: still -4% / +8%.
    assert d.stop_loss == pytest.approx(round(close * (1 - settings.ML_STOP_RETURN_PCT), 2))
    assert d.take_profit == pytest.approx(round(close * (1 + settings.ML_TARGET_RETURN_PCT), 2))
    assert d.horizon_days == 15


def test_strategy_on_below_calibrated_bar_holds(monkeypatch):
    _on(monkeypatch)
    _stub_market(monkeypatch, 0.30, [])
    assert _decide(0.30).signal == SignalType.HOLD


def test_strategy_on_weak_score_exits_only_at_the_calibrated_line(monkeypatch):
    _on(monkeypatch)
    _stub_market(monkeypatch, 0.08, [])
    assert _decide(0.08).signal == SignalType.EXIT
    _stub_market(monkeypatch, 0.20, [])
    assert _decide(0.20).signal == SignalType.HOLD  # 0.20 would be an EXIT under the old 0.35 line


def test_strategy_on_with_missing_calibrated_model_gives_no_signal(monkeypatch):
    # Only the OLD model exists: the strategy must not silently fall back to it.
    seen: list = []
    _stub_market(monkeypatch, 0.9, seen)
    monkeypatch.setattr(
        ml_swing, "get_active_model",
        lambda db, name=None: (seen.append(name), None)[1],
    )
    _on(monkeypatch, "_barrier_cal")
    assert _decide(0.9) is None
    assert seen == ["swing_classifier_barrier_cal"]


def test_train_cli_accepts_calibrate_and_tier_symbol_options():
    from swing_trade_ml.cli import build_parser

    args = build_parser().parse_args(
        ["train", "--name", "swing_classifier_midcap_barrier_cal", "--calibrate",
         "--symbols-from-model", "swing_classifier_midcap", "--walk-forward-folds", "5"]
    )
    assert args.calibrate is True and args.activate is False  # never auto-activates
    assert args.symbols_from_model == "swing_classifier_midcap"
    plain = build_parser().parse_args(["train"])
    assert plain.calibrate is False and plain.symbols is None and plain.symbols_from_model is None


def test_batch_prediction_resolves_the_same_way(monkeypatch):
    seen: list = []
    monkeypatch.setattr(
        predict, "get_active_model", lambda db, name=None: (seen.append(name), None)[1]
    )
    assert predict.predict_watchlist(None, "swing_classifier") == []
    _on(monkeypatch)
    assert predict.predict_watchlist(None, "swing_classifier") == []
    assert seen == ["swing_classifier", "swing_classifier_barrier_cal"]
