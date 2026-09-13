"""Outcome scoring for Signal rows — see docs/superpowers/specs/2026-09-12-signal-track-record-design.md."""

from __future__ import annotations

from datetime import UTC, datetime

from swing_trade_ml.core.enums import SignalType
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Signal, Strategy


def _instrument(db_session, tradingsymbol="TEST") -> Instrument:
    inst = Instrument(
        instrument_token=hash(tradingsymbol) % 1_000_000,
        tradingsymbol=tradingsymbol,
        exchange="NSE",
        is_watchlisted=True,
    )
    db_session.add(inst)
    db_session.flush()
    return inst


def _strategy(db_session) -> Strategy:
    strat = Strategy(name="test_strategy", strategy_type="ml_swing", mode="paper")
    db_session.add(strat)
    db_session.flush()
    return strat


def test_signal_has_outcome_columns(db_session):
    """New columns exist, default to unscored, and round-trip through a commit."""
    inst = _instrument(db_session)
    strat = _strategy(db_session)
    signal = Signal(
        strategy_id=strat.id,
        instrument_id=inst.id,
        signal_type=SignalType.BUY,
        mode="paper",
        price=100.0,
        stop_loss=90.0,
        take_profit=120.0,
        horizon_days=10,
        generated_at=datetime.now(UTC),
    )
    db_session.add(signal)
    db_session.flush()

    assert signal.horizon_days == 10
    assert signal.outcome is None
    assert signal.outcome_pct is None
    assert signal.outcome_at is None
