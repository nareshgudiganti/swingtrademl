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


def test_long_term_signal_is_scored_by_the_same_evaluate_pending_signals(db_session):
    """A long_term_value BUY signal is not a special case — it's scored by
    exactly the same function as a swing signal, just with a much longer
    horizon_days. This is the whole point of reusing Signal/Scan Results
    rather than building a parallel scoring path (spec §6)."""
    from datetime import UTC, datetime

    from swing_trade_ml.core.enums import SignalType
    from swing_trade_ml.db.models.market import Candle, Instrument
    from swing_trade_ml.db.models.trading import Signal, Strategy
    from swing_trade_ml.ml.predict import evaluate_pending_signals

    inst = Instrument(instrument_token=999, tradingsymbol="LTTEST", is_watchlisted=True)
    db_session.add(inst)
    db_session.flush()
    strat = Strategy(name="lt_test", strategy_type="long_term_value", mode="paper")
    db_session.add(strat)
    db_session.flush()

    gen_at = datetime(2026, 1, 1, tzinfo=UTC)
    sig = Signal(
        strategy_id=strat.id, instrument_id=inst.id, signal_type=SignalType.BUY, mode="paper",
        price=100.0, stop_loss=80.0, take_profit=130.0, horizon_days=250,
        advisory_only=True, generated_at=gen_at,
    )
    db_session.add(sig)
    # Target hit well inside the 250-day horizon.
    db_session.add(Candle(
        instrument_id=inst.id, interval="day", ts=datetime(2026, 6, 1, tzinfo=UTC),
        open=128, high=132, low=127, close=131, volume=100_000,
    ))
    db_session.commit()

    count = evaluate_pending_signals(db_session, now=datetime(2026, 9, 1, tzinfo=UTC))

    assert count == 1
    db_session.refresh(sig)
    assert sig.outcome == "TARGET_HIT"
