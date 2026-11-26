"""#227 / #281: boundary tests for the five-completed-session BUY window against the 5-day signal contract.

Contract (docs/superpowers/specs/2026-11-14-5d-paper-trial-protocol-v1.md lines 34, 79, 89, 302):
the signal is taken at the close of session D (session 0); entry is at the open of session 1; the trade
ends by the close of session 5; session 6 is never read. The daily scan runs 15:45 IST (after the 15:40
final candle), so a signal's own session is the IST date of its generated_at.

Pure tests, no database. "Age" = completed sessions between the signal's session and the last closed session.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from swing_trade_ml.api.v1.endpoints.signals import buy_fresh_since
from swing_trade_ml.core.market_session import IST


def _ist(y, m, d, hh=0, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=IST)


def _fresh(signal_at: datetime, now: datetime) -> bool:
    return signal_at >= buy_fresh_since(now)


# Calendar around the test: Tue 24 Nov 2026 is an NSE holiday. Now = Mon 30 Nov 10:00 IST, so the last closed
# session is Fri 27. Ages: Fri 27 = 0, Thu 26 = 1, Wed 25 = 2, Mon 23 = 3, Fri 20 = 4, Thu 19 = 5, Wed 18 = 6.
NOW = _ist(2026, 11, 30, 10, 0)
SCAN = (15, 45)  # the daily signal scan, IST


def test_the_last_closed_sessions_own_signal_is_fresh_age_zero():
    assert _fresh(_ist(2026, 11, 27, *SCAN), NOW)


def test_age_four_is_fresh_and_the_holiday_is_not_counted_as_a_session():
    # Fri 20 Nov is age 4 only because Tue 24 Nov (holiday) is skipped.
    assert _fresh(_ist(2026, 11, 20, *SCAN), NOW)


def test_age_five_is_included_and_age_six_is_excluded():
    # Pins today's inclusive boundary: six session dates (ages 0..5) are fresh.
    assert _fresh(_ist(2026, 11, 19, *SCAN), NOW)
    assert not _fresh(_ist(2026, 11, 18, *SCAN), NOW)


def test_the_cutoff_is_ist_midnight_of_the_oldest_fresh_session():
    cutoff = buy_fresh_since(NOW)
    assert cutoff == _ist(2026, 11, 19, 0, 0).astimezone(UTC)
    assert _fresh(_ist(2026, 11, 19, 0, 0), NOW)  # exactly the cutoff: included
    assert not _fresh(_ist(2026, 11, 18, 23, 59), NOW)  # a minute earlier: out


def test_a_calendar_window_would_disagree_the_holiday_changes_the_answer():
    # Thu 19 Nov is 11 calendar days before Mon 30 Nov but still fresh in sessions: unit is sessions.
    assert (NOW.date() - datetime(2026, 11, 19).date()).days == 11
    assert _fresh(_ist(2026, 11, 19, *SCAN), NOW)


@pytest.mark.parametrize(
    ("now", "last_closed_day"),
    [
        (
            _ist(2026, 11, 25, 15, 39),
            23,
        ),  # before the 15:40 final candle: Wed is not closed; Tue 24 is a holiday
        (_ist(2026, 11, 25, 15, 40), 25),  # at 15:40 the day is final
        (
            _ist(2026, 11, 25, 15, 35),
            23,
        ),  # 15:30 market close is NOT the cut: the bar is not final until 15:40
        (_ist(2026, 11, 24, 12, 0), 23),  # holiday: last closed is Monday
        (_ist(2026, 11, 28, 12, 0), 27),  # Saturday: Friday
        (_ist(2026, 11, 29, 20, 0), 27),  # Sunday: Friday
    ],
)
def test_which_session_is_the_last_closed_one_before_and_after_the_close(now, last_closed_day):
    # The signal of the last closed session is age 0 (fresh); the cutoff sits exactly five sessions earlier.
    assert _fresh(_ist(2026, 11, last_closed_day, *SCAN), now)
    cutoff = buy_fresh_since(now)
    sessions_back = {23: _ist(2026, 11, 16), 25: _ist(2026, 11, 17), 27: _ist(2026, 11, 19)}[last_closed_day]
    assert cutoff == sessions_back.astimezone(UTC)


def test_no_frontend_copy_of_the_window_exists():
    # The window is applied only in the backend: the frontend just renders the endpoints' rows.
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src"
    if not src.exists():
        pytest.skip("frontend sources not in this checkout")
    hits = [
        p.name
        for p in src.rglob("*.ts*")
        if "MAX_BUY_AGE" in p.read_text(encoding="utf-8", errors="ignore")
        or "buyFreshSince" in p.read_text(encoding="utf-8", errors="ignore")
    ]
    assert hits == []


@pytest.mark.xfail(
    strict=True,
    reason=(
        "#227/#281 contract gap, owner decision needed: the protocol ends a 5-day trade at the "
        "close of session 5 after the signal (entry = session 1 open; session 6 never read). "
        "Today a signal from session D is still listed once D+5 has closed (age 5), so a buyer "
        "could only enter at the session D+6 open, outside that window. "
        "Passing this test means the boundary was moved to ages 0..4."
    ),
)
def test_contract_reading_a_signal_whose_five_session_window_is_over_is_not_fresh():
    # Thu 19 Nov signal (session D). After D: Fri 20 (1), Mon 23 (2), Wed 25 (3), Thu 26 (4), Fri 27 (5).
    # After Fri 27 closes, session 5 is over; the next possible entry is Mon 30 = session 6.
    assert not _fresh(_ist(2026, 11, 19, *SCAN), NOW)
