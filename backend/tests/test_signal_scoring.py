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


def test_signal_decision_carries_horizon_days():
    """SignalDecision must be able to carry a horizon so strategies can set
    it — this is a shape test; per-strategy value tests are separate."""
    from swing_trade_ml.core.enums import SignalType
    from swing_trade_ml.strategies.base import SignalDecision

    decision = SignalDecision(
        signal=SignalType.BUY,
        price=100.0,
        stop_loss=90.0,
        take_profit=120.0,
        horizon_days=10,
    )
    assert decision.horizon_days == 10


from swing_trade_ml.db.models.market import Candle


def _candle(db_session, instrument_id, ts, o, h, l, c, v=100_000):
    db_session.add(
        Candle(
            instrument_id=instrument_id, interval="day", ts=ts,
            open=o, high=h, low=l, close=c, volume=v,
        )
    )


def _signal(db_session, strategy_id, instrument_id, generated_at, price, stop_loss, take_profit, horizon_days=5):
    sig = Signal(
        strategy_id=strategy_id, instrument_id=instrument_id,
        signal_type=SignalType.BUY, mode="paper",
        price=price, stop_loss=stop_loss, take_profit=take_profit,
        horizon_days=horizon_days, generated_at=generated_at,
    )
    db_session.add(sig)
    db_session.flush()
    return sig


def test_target_hit_before_stop(db_session):
    from swing_trade_ml.ml.predict import evaluate_pending_signals

    inst = _instrument(db_session)
    strat = _strategy(db_session)
    gen_at = datetime(2026, 1, 1, tzinfo=UTC)
    sig = _signal(db_session, strat.id, inst.id, gen_at, price=100.0, stop_loss=90.0, take_profit=110.0)
    # Day after generation: high crosses take_profit, low stays above stop.
    _candle(db_session, inst.id, datetime(2026, 1, 2, tzinfo=UTC), 101, 112, 100, 111)
    db_session.commit()

    count = evaluate_pending_signals(db_session, now=datetime(2026, 1, 10, tzinfo=UTC))

    assert count == 1
    db_session.refresh(sig)
    assert sig.outcome == "TARGET_HIT"
    assert sig.outcome_pct == 0.10  # (110 - 100) / 100


def test_stop_hit_before_target(db_session):
    from swing_trade_ml.ml.predict import evaluate_pending_signals

    inst = _instrument(db_session)
    strat = _strategy(db_session)
    gen_at = datetime(2026, 1, 1, tzinfo=UTC)
    sig = _signal(db_session, strat.id, inst.id, gen_at, price=100.0, stop_loss=90.0, take_profit=110.0)
    _candle(db_session, inst.id, datetime(2026, 1, 2, tzinfo=UTC), 99, 101, 88, 89)
    db_session.commit()

    evaluate_pending_signals(db_session, now=datetime(2026, 1, 10, tzinfo=UTC))

    db_session.refresh(sig)
    assert sig.outcome == "STOP_LOSS_HIT"
    assert sig.outcome_pct == -0.10  # (90 - 100) / 100


def test_same_day_double_touch_favours_stop(db_session):
    from swing_trade_ml.ml.predict import evaluate_pending_signals

    inst = _instrument(db_session)
    strat = _strategy(db_session)
    gen_at = datetime(2026, 1, 1, tzinfo=UTC)
    sig = _signal(db_session, strat.id, inst.id, gen_at, price=100.0, stop_loss=90.0, take_profit=110.0)
    # One wide-range candle crosses both levels.
    _candle(db_session, inst.id, datetime(2026, 1, 2, tzinfo=UTC), 100, 115, 85, 105)
    db_session.commit()

    evaluate_pending_signals(db_session, now=datetime(2026, 1, 10, tzinfo=UTC))

    db_session.refresh(sig)
    assert sig.outcome == "STOP_LOSS_HIT"


def test_expires_with_no_hit_within_horizon(db_session):
    from swing_trade_ml.ml.predict import evaluate_pending_signals

    inst = _instrument(db_session)
    strat = _strategy(db_session)
    gen_at = datetime(2026, 1, 1, tzinfo=UTC)
    sig = _signal(
        db_session, strat.id, inst.id, gen_at, price=100.0, stop_loss=90.0,
        take_profit=110.0, horizon_days=3,
    )
    # Every candle stays inside the band, past the 3-day horizon.
    for day, close in [(2, 102), (3, 103), (4, 104), (5, 105)]:
        _candle(db_session, inst.id, datetime(2026, 1, day, tzinfo=UTC), close - 1, close + 1, close - 2, close)
    db_session.commit()

    evaluate_pending_signals(db_session, now=datetime(2026, 1, 10, tzinfo=UTC))

    db_session.refresh(sig)
    assert sig.outcome == "EXPIRED_NO_HIT"
    assert sig.outcome_pct is not None


def test_still_open_signal_is_not_scored(db_session):
    from swing_trade_ml.ml.predict import evaluate_pending_signals

    inst = _instrument(db_session)
    strat = _strategy(db_session)
    gen_at = datetime(2026, 1, 1, tzinfo=UTC)
    sig = _signal(
        db_session, strat.id, inst.id, gen_at, price=100.0, stop_loss=90.0,
        take_profit=110.0, horizon_days=30,
    )
    _candle(db_session, inst.id, datetime(2026, 1, 2, tzinfo=UTC), 100, 105, 98, 102)
    db_session.commit()

    count = evaluate_pending_signals(db_session, now=datetime(2026, 1, 5, tzinfo=UTC))

    assert count == 0
    db_session.refresh(sig)
    assert sig.outcome is None


def test_track_record_endpoint_returns_scored_and_open_signals(client, db_session):
    inst = _instrument(db_session, "TRKTEST")
    strat = _strategy(db_session)
    gen_at = datetime(2026, 1, 1, tzinfo=UTC)
    scored = _signal(db_session, strat.id, inst.id, gen_at, price=100.0, stop_loss=90.0, take_profit=110.0)
    scored.outcome = "TARGET_HIT"
    scored.outcome_pct = 0.10
    scored.outcome_at = datetime(2026, 1, 2, tzinfo=UTC)
    db_session.commit()

    resp = client.get("/api/v1/signals/track-record", headers={"X-API-Key": "test-api-key"})

    assert resp.status_code == 200
    rows = resp.json()
    matching = [r for r in rows if r["symbol"] == "TRKTEST"]
    assert len(matching) == 1
    assert matching[0]["outcome"] == "TARGET_HIT"
    assert matching[0]["cap_tier"] == "large"
    assert "current_price" in matching[0]
