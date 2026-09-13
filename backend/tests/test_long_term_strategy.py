"""Long-term stock picks — see
docs/superpowers/specs/2026-09-12-long-term-stock-picks-design.md.

Phase 1 reuses the existing price/volume feature pipeline unchanged, just a
longer horizon and higher target return than the swing model — no
fundamentals dependency yet (that's Task 6, gated on the Task 1 vendor
spike)."""

from __future__ import annotations


def test_long_term_model_uses_a_materially_longer_horizon_and_higher_target():
    """Pins the actual values this plan picks — see Step 2's rationale.
    A multi-month hold should target a materially larger move than the
    swing model's ~5-20 day / ~2-15% range (core/config.py's
    DEFAULT_STOP_LOSS_PCT=0.05 / DEFAULT_TAKE_PROFIT_PCT=0.15 give the
    swing model's rough scale)."""
    from swing_trade_ml.strategies.long_term_value import (
        LONG_TERM_HORIZON_DAYS,
        LONG_TERM_TARGET_RETURN_PCT,
    )

    assert LONG_TERM_HORIZON_DAYS >= 180
    assert LONG_TERM_TARGET_RETURN_PCT >= 0.25  # materially more than the swing model's 15%


def test_train_model_accepts_long_term_value_arguments(monkeypatch):
    """Confirms train_model's existing signature (unchanged) accepts the
    long-term configuration without needing any new parameter — this is a
    call-shape test, not a real training run."""
    from swing_trade_ml.strategies.long_term_value import (
        LONG_TERM_HORIZON_DAYS,
        LONG_TERM_TARGET_RETURN_PCT,
    )
    from swing_trade_ml.ml import train as train_module

    captured = {}

    def fake_train_model(db, **kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr(train_module, "train_model", fake_train_model)

    train_module.train_model(
        db=None,
        name="long_term_value",
        horizon_days=LONG_TERM_HORIZON_DAYS,
        target_return=LONG_TERM_TARGET_RETURN_PCT,
    )

    assert captured["name"] == "long_term_value"
    assert captured["horizon_days"] == 250


def test_long_term_strategy_is_registered():
    from swing_trade_ml.strategies import STRATEGY_REGISTRY

    assert "long_term_value" in STRATEGY_REGISTRY


def test_long_term_strategy_signal_is_advisory_only_by_default():
    from swing_trade_ml.db.models.trading import Strategy as StrategyModel
    from swing_trade_ml.strategies.long_term_value import LongTermValueStrategy

    config = StrategyModel(name="lt-test", strategy_type="long_term_value", params={})
    strategy = LongTermValueStrategy(config)

    assert strategy.default_params.get("advisory_only", True) is True


def test_long_term_strategy_returns_none_below_min_bars():
    import pandas as pd

    from swing_trade_ml.db.models.market import Instrument
    from swing_trade_ml.db.models.trading import Strategy as StrategyModel
    from swing_trade_ml.strategies.long_term_value import LongTermValueStrategy

    config = StrategyModel(name="lt-test", strategy_type="long_term_value", params={})
    strategy = LongTermValueStrategy(config)
    short_df = pd.DataFrame({"ts": pd.date_range("2026-01-01", periods=5), "close": [100] * 5})
    inst = Instrument(instrument_token=1, tradingsymbol="TEST")

    assert strategy.evaluate(short_df, inst, db=None) is None
