"""A signal's horizon must be counted in the same unit its label was trained in.

ml/features.py::build_label walks `horizon_days` *trading bars* forward. The
signal scorer walked `horizon_days` *calendar days*. Fifteen trading bars is
about twenty-one calendar days, so every signal was being judged on roughly
two-thirds of the window the model was actually trained to predict — and the
error only ever cuts winners short, because a trade that has not yet reached
its target is scored EXPIRED_NO_HIT rather than left open.

That bias lands on the barrier shadow strategies, whose resolved signals are
the entire evidence base for the promotion decision.

This is not the 30-calendar-day time stop, which is a separate exit rule and
already agrees with a 15-trading-bar horizon.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from swing_trade_ml.core.enums import SignalType
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.trading import Signal, Strategy
from swing_trade_ml.ml.predict import evaluate_pending_signals

# 2026-01-02 is a Friday, so a three-bar horizon spans a weekend: the third
# trading bar lands on Wednesday the 7th, six calendar days out.
GENERATED_AT = datetime(2026, 1, 2, 10, 0, tzinfo=UTC)
TRADING_DAYS = [
    datetime(2026, 1, 5, 10, 0, tzinfo=UTC),
    datetime(2026, 1, 6, 10, 0, tzinfo=UTC),
    datetime(2026, 1, 7, 10, 0, tzinfo=UTC),
    datetime(2026, 1, 8, 10, 0, tzinfo=UTC),
]
LATER = datetime(2026, 2, 1, tzinfo=UTC)


def _setup(db_session, bars: list[tuple[datetime, float, float, float]]) -> Signal:
    """`bars` is (ts, high, low, close). The signal is +8%/-4% over 3 bars."""
    instrument = Instrument(
        instrument_token=881001, tradingsymbol="HORIZONCO", exchange="NSE", is_watchlisted=True
    )
    strategy = Strategy(name="horizon_test", strategy_type="ml_swing", mode="paper")
    db_session.add_all([instrument, strategy])
    db_session.flush()

    for ts, high, low, close in bars:
        db_session.add(
            Candle(
                instrument_id=instrument.id, interval="day", ts=ts,
                open=close, high=high, low=low, close=close, volume=100_000,
            )
        )

    signal = Signal(
        strategy_id=strategy.id,
        instrument_id=instrument.id,
        signal_type=SignalType.BUY,
        mode="paper",
        price=100.0,
        stop_loss=96.0,
        take_profit=108.0,
        horizon_days=3,
        generated_at=GENERATED_AT,
    )
    db_session.add(signal)
    db_session.flush()
    return signal


def test_the_horizon_spans_trading_bars_across_a_weekend(db_session):
    """The target is hit on the third trading bar, which is six calendar days
    out. Counting calendar days stopped looking after the first bar and called
    a winner expired."""
    signal = _setup(
        db_session,
        [
            (TRADING_DAYS[0], 102.0, 99.0, 101.0),
            (TRADING_DAYS[1], 104.0, 100.0, 103.0),
            (TRADING_DAYS[2], 109.0, 102.0, 108.5),
            (TRADING_DAYS[3], 112.0, 107.0, 111.0),
        ],
    )

    assert evaluate_pending_signals(db_session, now=LATER) == 1
    assert signal.outcome == "TARGET_HIT"
    assert signal.outcome_at == TRADING_DAYS[2]


def test_a_bar_past_the_horizon_cannot_resolve_the_signal(db_session):
    """The fourth bar goes to the target, but the signal only ever promised
    three. It expires on the third bar's close, not on a later win."""
    signal = _setup(
        db_session,
        [
            (TRADING_DAYS[0], 102.0, 99.0, 101.0),
            (TRADING_DAYS[1], 103.0, 100.0, 102.0),
            (TRADING_DAYS[2], 104.0, 101.0, 103.0),
            (TRADING_DAYS[3], 115.0, 103.0, 114.0),
        ],
    )

    assert evaluate_pending_signals(db_session, now=LATER) == 1
    assert signal.outcome == "EXPIRED_NO_HIT"
    assert signal.outcome_at == TRADING_DAYS[2]
    assert signal.outcome_pct == pytest.approx(0.03)


def test_a_signal_whose_bars_have_not_arrived_yet_stays_open(db_session):
    """Two bars into a three-bar horizon is not an expiry. The old calendar
    arithmetic could close it simply because enough days had passed, even
    though the market had not traded."""
    signal = _setup(
        db_session,
        [
            (TRADING_DAYS[0], 102.0, 99.0, 101.0),
            (TRADING_DAYS[1], 103.0, 100.0, 102.0),
        ],
    )

    assert evaluate_pending_signals(db_session, now=LATER) == 0
    assert signal.outcome is None


def test_a_stop_still_wins_ties_against_the_target_on_the_same_bar(db_session):
    """Unchanged behaviour, asserted here because the rewrite touches the loop:
    build_label resolves a same-bar tie to the stop, and the ledger must agree
    or the two measure different trades."""
    signal = _setup(
        db_session,
        [(TRADING_DAYS[0], 109.0, 95.0, 100.0)] + [(t, 101.0, 99.0, 100.0) for t in TRADING_DAYS[1:]],
    )

    assert evaluate_pending_signals(db_session, now=LATER) == 1
    assert signal.outcome == "STOP_LOSS_HIT"
