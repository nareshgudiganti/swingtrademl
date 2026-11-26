"""#239 gap f1 / #227: the buy list and top picks keep a BUY while it is at most 4 completed trading
sessions old (ages 0-4, owner decision 26 Nov 2026), so it can still be entered inside its 5-session window.

Pure function test (no database). Expected cutoffs are worked out by hand from the
calendar: weekends and listed NSE holidays are skipped, and a session's own signals
are age 0. The cutoff is IST midnight of the oldest fresh session.
"""

from __future__ import annotations

from datetime import UTC, datetime

from swing_trade_ml.api.v1.endpoints.signals import MAX_BUY_AGE_SESSIONS, buy_fresh_since
from swing_trade_ml.core.market_session import IST


def _ist(y, m, d, hh=10, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=IST)


def _cutoff_ist_midnight(y, m, d) -> datetime:
    return datetime(y, m, d, 0, 0, tzinfo=IST).astimezone(UTC)


def test_the_oldest_listed_buy_is_four_sessions_old():
    assert MAX_BUY_AGE_SESSIONS == 4


def test_during_a_session_the_last_closed_session_is_the_day_before():
    # Mon 23 Nov 2026 10:00 IST: last closed session is Fri 20 Nov.
    # Four sessions back from Fri 20: Thu 19, Wed 18, Tue 17, Mon 16.
    assert buy_fresh_since(_ist(2026, 11, 23, 10, 0)) == _cutoff_ist_midnight(2026, 11, 16)


def test_after_the_close_today_counts_as_the_last_closed_session():
    # Wed 25 Nov 2026 16:00 IST: today is closed. Tue 24 Nov is a listed NSE holiday,
    # so four sessions back from Wed 25 are: Mon 23, Fri 20, Thu 19, Wed 18.
    assert buy_fresh_since(_ist(2026, 11, 25, 16, 0)) == _cutoff_ist_midnight(2026, 11, 18)


def test_a_weekend_and_a_holiday_are_skipped_not_counted():
    # Sat 28 Nov 2026: last closed session is Fri 27 Nov. Four sessions back:
    # Thu 26, Wed 25, (Tue 24 is a holiday), Mon 23, Fri 20.
    assert buy_fresh_since(_ist(2026, 11, 28, 12, 0)) == _cutoff_ist_midnight(2026, 11, 20)


def test_the_cutoff_is_ist_midnight_in_utc():
    # 00:00 IST is the previous day 18:30 UTC.
    cutoff = buy_fresh_since(_ist(2026, 11, 25, 16, 0))
    assert cutoff.tzinfo is not None
    assert cutoff.astimezone(UTC).hour == 18 and cutoff.astimezone(UTC).minute == 30
