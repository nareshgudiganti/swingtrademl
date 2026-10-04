"""One market clock for the whole app (one-app technical design, step 2):
trading days, the session state, the next open/close, the last finished
trading day, and a warning when a year's holiday list is missing."""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from swing_trade_ml.core import market_session as ms

IST = ZoneInfo("Asia/Kolkata")


def at(y, m, d, hh=12, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=IST)


# --- trading days ---------------------------------------------------------------


@pytest.mark.parametrize(
    "day,expected",
    [
        (date(2026, 10, 5), True),  # Monday
        (date(2026, 10, 3), False),  # Saturday
        (date(2026, 10, 4), False),  # Sunday
        (date(2026, 10, 2), False),  # Gandhi Jayanti (Friday holiday)
        (date(2026, 10, 20), False),  # Dussehra
    ],
)
def test_trading_days_follow_weekends_and_the_nse_calendar(day, expected):
    assert ms.is_trading_day(day) is expected


def test_next_and_previous_trading_day_skip_weekends_and_holidays():
    assert ms.next_trading_day(date(2026, 10, 1)) == date(2026, 10, 5)  # Thu → skips Fri holiday + weekend
    assert ms.previous_trading_day(date(2026, 10, 5)) == date(2026, 10, 1)


def test_trading_days_between_counts_after_the_first_up_to_the_last():
    assert ms.trading_days_between(date(2026, 10, 1), date(2026, 10, 6)) == 2  # Mon 5, Tue 6


# --- session state ----------------------------------------------------------------


@pytest.mark.parametrize(
    "now,state",
    [
        (at(2026, 10, 5, 8, 0), ms.SessionState.PRE_OPEN),
        (at(2026, 10, 5, 9, 15), ms.SessionState.OPEN),
        (at(2026, 10, 5, 15, 29), ms.SessionState.OPEN),
        (at(2026, 10, 5, 15, 30), ms.SessionState.CLOSED),
        (at(2026, 10, 4, 11, 0), ms.SessionState.WEEKEND),
        (at(2026, 10, 2, 11, 0), ms.SessionState.HOLIDAY),
    ],
)
def test_the_session_state_at_each_moment(now, state):
    assert ms.session(now).state is state


def test_open_never_includes_the_closing_minute_for_orders():
    assert ms.is_open(at(2026, 10, 5, 15, 30)) is False
    assert ms.is_open(at(2026, 10, 5, 15, 30), include_close=True) is True  # ingestion's old rule


def test_the_session_says_when_it_next_opens_and_closes():
    s = ms.session(at(2026, 10, 3, 11, 0))  # Saturday
    assert s.next_open == datetime.combine(date(2026, 10, 5), time(9, 15), tzinfo=IST)
    assert s.next_close == datetime.combine(date(2026, 10, 5), time(15, 30), tzinfo=IST)
    s = ms.session(at(2026, 10, 5, 10, 0))  # open now
    assert s.closes_at == datetime.combine(date(2026, 10, 5), time(15, 30), tzinfo=IST)
    assert s.next_open == datetime.combine(date(2026, 10, 6), time(9, 15), tzinfo=IST)


def test_the_session_has_one_plain_line():
    assert ms.session(at(2026, 10, 5, 10, 0)).plain == "Market open · closes 3:30 pm"
    assert ms.session(at(2026, 10, 4, 11, 0)).plain == "Market closed · opens Mon 05 Oct, 9:15 am"
    assert ms.session(at(2026, 10, 5, 8, 0)).plain == "Market opens at 9:15 am"


# --- last finished trading day ------------------------------------------------------


def test_last_closed_trading_day_waits_for_the_days_bar_to_be_final():
    assert ms.last_closed_trading_day(at(2026, 10, 5, 15, 39)) == date(2026, 10, 1)
    assert ms.last_closed_trading_day(at(2026, 10, 5, 15, 40)) == date(2026, 10, 5)


def test_last_closed_trading_day_skips_holidays_not_only_weekends():
    # Fri 2 Oct 2026 is a holiday: after 15:40 that day the last finished day is Thu 1 Oct.
    assert ms.last_closed_trading_day(at(2026, 10, 2, 16, 0)) == date(2026, 10, 1)


# --- holiday calendar coverage ---------------------------------------------------------


def test_a_missing_holiday_year_is_flagged_from_november(monkeypatch):
    monkeypatch.setattr(ms, "NSE_HOLIDAYS", {2026: {date(2026, 12, 25)}})
    assert ms.calendar_warning(date(2026, 10, 31)) is None
    warning = ms.calendar_warning(date(2026, 11, 1))
    assert warning and "2027" in warning


def test_a_year_with_no_holiday_list_at_all_is_flagged(monkeypatch):
    monkeypatch.setattr(ms, "NSE_HOLIDAYS", {2026: {date(2026, 12, 25)}})
    assert "2027" in ms.calendar_warning(date(2027, 1, 4))


def test_an_unknown_year_still_counts_weekdays_as_trading_days(monkeypatch):
    """Never stop version 1 over a missing list: warn, and keep the old rule."""
    monkeypatch.setattr(ms, "NSE_HOLIDAYS", {2026: set()})
    assert ms.is_trading_day(date(2027, 1, 4)) is True


# --- the rest of the app uses this one clock ---------------------------------------------


def test_the_old_helpers_now_answer_from_the_shared_clock():
    from swing_trade_ml.brain.modules.m01_quality import quality
    from swing_trade_ml.brain.modules.m09_learn import scoring
    from swing_trade_ml.services import ingestion
    from swing_trade_ml.services.brain_golive import approvals

    assert quality.is_trading_day is ms.is_trading_day
    assert scoring.last_closed_trading_day is ms.last_closed_trading_day
    assert ingestion.is_market_open(at(2026, 10, 5, 15, 30)) is True  # inclusive, as before
    assert ingestion.is_market_open(at(2026, 10, 2, 11, 0)) is False  # holiday
    assert approvals.valid_until(date(2026, 10, 1)) == datetime.combine(
        date(2026, 10, 5), time(15, 30), tzinfo=IST
    )


# --- API -----------------------------------------------------------------------------------

HEADERS = {"X-API-Key": "test-api-key"}


def test_the_market_session_endpoint(client, monkeypatch):
    monkeypatch.setattr(ms, "_now", lambda: at(2026, 10, 4, 11, 0))
    body = client.get("/api/v1/market/session", headers=HEADERS).json()
    assert body["state"] == "weekend"
    assert body["plain"] == "Market closed · opens Mon 05 Oct, 9:15 am"
    assert body["next_open"].startswith("2026-10-05T09:15")
    assert "calendar_warning" in body


def test_status_warns_when_next_years_holidays_are_missing():
    from swing_trade_ml.api.v1.endpoints.system import _plain_status

    level, message = _plain_status(
        broker_authenticated=True,
        scheduler_running=True,
        latest_candle_date=date(2026, 11, 2),
        last_scan_at=at(2026, 11, 2, 15, 45),
        now_ist=at(2026, 11, 3, 11, 0),
        calendar_warning="Add the 2027 NSE holiday list.",
    )
    assert level == "warning" and "2027" in message


# --- a real-money sale by hand only while the market is open ---------------------------------


def _open_position(db, mode: str):
    from swing_trade_ml.db.models.market import Instrument
    from swing_trade_ml.db.models.trading import Position

    inst = Instrument(instrument_token=995001, tradingsymbol="SESSIONX", exchange="NSE", is_active=True)
    db.add(inst)
    db.flush()
    pos = Position(
        instrument_id=inst.id, mode=mode, quantity=3, entry_price=100.0, entry_at=at(2026, 9, 30, 10, 0)
    )
    db.add(pos)
    db.commit()
    return pos


def test_a_real_money_close_outside_market_hours_is_refused_in_plain_words(client, db_session, monkeypatch):
    from swing_trade_ml.api.v1.endpoints import portfolio

    pos = _open_position(db_session, "live")
    monkeypatch.setattr(ms, "_now", lambda: at(2026, 10, 4, 11, 0))  # Sunday
    sent = []
    monkeypatch.setattr(portfolio, "close_position", lambda *a, **k: sent.append(a))
    r = client.post(f"/api/v1/portfolio/positions/{pos.id}/close", json={}, headers=HEADERS)
    assert r.status_code == 409
    assert "market is closed" in r.json()["detail"].lower() and "Mon 05 Oct" in r.json()["detail"]
    assert sent == []


def test_a_practice_close_outside_market_hours_still_goes_through(client, db_session, monkeypatch):
    from types import SimpleNamespace

    from swing_trade_ml.api.v1.endpoints import portfolio

    pos = _open_position(db_session, "paper")
    monkeypatch.setattr(ms, "_now", lambda: at(2026, 10, 4, 11, 0))
    trade = SimpleNamespace(exit_price=101.0, net_pnl=3.0, return_pct=0.01)
    monkeypatch.setattr(portfolio, "close_position", lambda *a, **k: trade)
    r = client.post(f"/api/v1/portfolio/positions/{pos.id}/close", json={}, headers=HEADERS)
    assert r.status_code == 200
