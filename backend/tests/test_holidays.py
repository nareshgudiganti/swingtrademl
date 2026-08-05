"""NSE holiday-calendar tests."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from swing_trade_ml.core.holidays import is_trading_holiday
from swing_trade_ml.services.ingestion import is_market_open

IST = ZoneInfo("Asia/Kolkata")


def test_known_holiday_is_flagged():
    assert is_trading_holiday(date(2026, 1, 26))  # Republic Day


def test_ordinary_weekday_is_not_a_holiday():
    assert not is_trading_holiday(date(2026, 1, 27))


def test_unmodelled_year_degrades_to_not_a_holiday():
    """A year not yet compiled into the calendar must never raise."""
    assert not is_trading_holiday(date(2099, 1, 1))


def test_market_is_closed_on_a_holiday_even_during_session_hours():
    republic_day_at_noon = datetime(2026, 1, 26, 12, 0, tzinfo=IST)
    assert not is_market_open(republic_day_at_noon)


def test_market_is_open_on_an_ordinary_trading_day_at_noon():
    ordinary_tuesday_at_noon = datetime(2026, 1, 27, 12, 0, tzinfo=IST)
    assert is_market_open(ordinary_tuesday_at_noon)
