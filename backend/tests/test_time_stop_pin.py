"""Pins the time stop (30 calendar days) and the model horizon (15 trading days).

They are different units on purpose and the owner has asked for both to stay as they are. This test
does not say they are right; it makes changing either one a visible decision, and it records how far
apart they really are, because every replay and back-test simulates 15 trading days.
"""

from __future__ import annotations

from datetime import date, timedelta

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.market_session import trading_days_between
from swing_trade_ml.services.exit_policy import DEFAULT_TIME_STOP_DAYS, exit_policy_for


def test_the_settled_numbers_are_unchanged():
    assert settings.ML_PREDICTION_HORIZON_DAYS == 15  # trading days: labels, M09, replays
    assert DEFAULT_TIME_STOP_DAYS == 30  # calendar days: the live exit
    assert exit_policy_for(None).time_stop_days == 30


def test_the_live_time_stop_always_outlasts_the_validated_horizon():
    """Over every 2026 start day, 30 calendar days holds 16 to 22 sessions (about 20 on average)."""
    starts = [date(2026, 1, 5) + timedelta(days=i) for i in range(300)]
    counts = [
        trading_days_between(d, d + timedelta(days=DEFAULT_TIME_STOP_DAYS)) for d in starts if d.weekday() < 5
    ]
    assert min(counts) > settings.ML_PREDICTION_HORIZON_DAYS
    assert 19 <= sum(counts) / len(counts) <= 21
