# ruff: noqa: E501  (long plain-English test text)
"""#240 Verify quote freshness and chart states: the server side.

Tests only. Nothing here changes a screen, a price, a calendar or an order. The browser side is
frontend/src/trademind/verify240.test.tsx. The quote and snapshot rules themselves (stale quote, missing quote, future
quote, the raw quote route) were verified in #246 (docs/verification/246-data-freshness.md, tests b1-b7) and are cited, not
repeated. The findings note is docs/verification/240-quotes-charts.md. Needs the test database; every write rolls back.

A gap is a strict expected failure (`xfail(strict=True, raises=AssertionError)`) with one line saying what is missing.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from swing_trade_ml.api.v1.endpoints import system
from swing_trade_ml.core import market_session
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.trading import Position, Strategy

IST = ZoneInfo("Asia/Kolkata")
GAP = {"strict": True, "raises": AssertionError}
_tokens = iter(range(980_000, 980_900))


def at_ist(monkeypatch, year, month, day, hour, minute=0) -> datetime:
    now = datetime(year, month, day, hour, minute, tzinfo=IST)
    monkeypatch.setattr(market_session, "_now", lambda: now)
    return now


def add_bar(db, inst: Instrument, day: date, close: float = 100.0) -> None:
    ts = datetime.combine(day, time(0, 0), tzinfo=IST).astimezone(UTC)  # how Kite stamps a daily bar
    db.add(
        Candle(
            instrument_id=inst.id,
            interval="day",
            ts=ts,
            open=close,
            high=close,
            low=close,
            close=close,
            volume=1,
        )
    )
    db.flush()


def instrument(db, symbol: str) -> Instrument:
    row = Instrument(instrument_token=next(_tokens), tradingsymbol=symbol, exchange="NSE", is_active=True)
    db.add(row)
    db.flush()
    return row


def session_inputs(db) -> dict:
    """What GET /market/session sends the "Prices from ..." badge (the trading calendar the screens count days with)."""
    return system.market_session_now(db)


# =========================================================================== the calendar the price badge counts with


def test_a1_monday_morning_with_friday_close_in_hand_is_not_a_missing_day(db_session, monkeypatch):
    row = instrument(db_session, "V240MON")
    add_bar(db_session, row, date(2026, 11, 27))  # Friday
    at_ist(monkeypatch, 2026, 11, 30, 8, 0)  # Monday morning, before the open
    out = session_inputs(db_session)
    assert out["today"] == date(2026, 11, 30) and out["last_closed_trading_day"] == date(2026, 11, 27)
    assert out["latest_candle_date"] == date(
        2026, 11, 27
    )  # the IST date of the bar, not the UTC date (26 Nov)
    assert out["recent_closed_trading_days"][0] == date(2026, 11, 27)  # the weekend is not a trading day


def test_a2_a_market_holiday_is_skipped_by_the_calendar(db_session, monkeypatch):
    row = instrument(db_session, "V240HOL")
    add_bar(db_session, row, date(2026, 11, 23))  # Monday; Tuesday 24 Nov 2026 is an NSE holiday
    assert market_session.is_trading_day(date(2026, 11, 24)) is False
    at_ist(monkeypatch, 2026, 11, 25, 8, 0)
    out = session_inputs(db_session)
    assert out["last_closed_trading_day"] == date(2026, 11, 23)
    assert date(2026, 11, 24) not in out["recent_closed_trading_days"] and out["latest_candle_date"] == date(
        2026, 11, 23
    )


def test_a3_after_the_close_the_day_is_final_only_from_1540_and_its_candle_is_one_day_behind(
    db_session, monkeypatch
):
    row = instrument(db_session, "V240EVE")
    add_bar(db_session, row, date(2026, 11, 25))  # Wednesday's bar is the newest stored
    at_ist(monkeypatch, 2026, 11, 26, 15, 30)  # Thursday, market just closed, bar not final yet
    assert session_inputs(db_session)["last_closed_trading_day"] == date(2026, 11, 25)
    at_ist(monkeypatch, 2026, 11, 26, 16, 0)  # after 15:40 the day is final
    out = session_inputs(db_session)
    assert out["recent_closed_trading_days"][:2] == [date(2026, 11, 26), date(2026, 11, 25)]
    assert out["latest_candle_date"] == date(
        2026, 11, 25
    )  # one trading day behind: the screen allows this one day


def test_a4_no_stored_price_is_a_null_date_not_a_made_up_one(db_session, monkeypatch):
    from sqlalchemy import delete

    db_session.execute(delete(Candle).where(Candle.interval == "day"))
    at_ist(monkeypatch, 2026, 11, 30, 10, 0)
    assert session_inputs(db_session)["latest_candle_date"] is None


def test_a5_the_screens_calendar_is_the_market_session_route_not_the_trading_rules_route():
    """#416's /config/trading-rules carries the holiday list and trial count; the badge's day counting reads
    /market/session (`recent_closed_trading_days`). Both come from core/market_session.py and core/holidays.py."""
    from swing_trade_ml.core.holidays import NSE_HOLIDAYS

    assert all(not market_session.is_trading_day(d) for days in NSE_HOLIDAYS.values() for d in days)


# ======================================================================= what the API says about a candle's date (evidence)


def test_b1_a_daily_candle_is_served_as_a_utc_instant_so_its_date_must_be_taken_in_ist(db_session):
    """Evidence for gap c4 (browser side): the API serves a bar for 30 Nov as 29 Nov 18:30 UTC. A screen that cuts the
    first ten characters of the string shows 11-29."""
    from swing_trade_ml.schemas import CandleOut

    row = instrument(db_session, "V240TS")
    add_bar(db_session, row, date(2026, 11, 30))
    candle = db_session.query(Candle).filter(Candle.instrument_id == row.id).one()
    served = CandleOut.model_validate(candle).model_dump(mode="json")["ts"]
    assert served.startswith("2026-11-29T18:30:00")  # UTC, with the IST date one day later


# ================================================================================ positions: price shown without an age


def _real_book_position(db, *, current_price):
    strat = Strategy(
        name="v240_bot", strategy_type="ml_swing", mode="paper", execution_mode="auto", is_active=True
    )
    db.add(strat)
    db.flush()
    row = instrument(db, "V240POS")
    pos = Position(
        strategy_id=strat.id,
        instrument_id=row.id,
        mode="paper",
        status="OPEN",
        quantity=10,
        entry_price=100.0,
        entry_at=datetime.now(UTC) - timedelta(days=2),
        current_price=current_price,
        stop_loss=96.0,
        take_profit=108.0,
        total_charges=1.0,
    )
    db.add(pos)
    db.commit()
    return pos


def _rows(client):
    return client.get("/api/v1/portfolio/positions/detailed", headers={"X-API-Key": "test-api-key"}).json()


def test_c1_a_position_that_was_never_priced_says_its_exit_check_is_unavailable(client, db_session):
    _real_book_position(db_session, current_price=None)
    row = next(r for r in _rows(client) if r["symbol"] == "V240POS")
    assert row["sell_status"] == "Exit check unavailable"  # the honest words (services/sell_labels.py:51)


def test_c2_a_never_priced_position_is_shown_at_its_entry_price_as_a_flat_zero_percent(client, db_session):
    """OBSERVED: the row falls back to the entry price (api/v1/endpoints/portfolio.py:`current = current_price or entry_price`),
    so a position nobody has priced reads as exactly flat. The sell status above is the only warning on the row."""
    _real_book_position(db_session, current_price=None)
    row = next(r for r in _rows(client) if r["symbol"] == "V240POS")
    assert (
        row["current_price"] == 100.0 and row["unrealized_pnl_pct"] == 0.0 and row["current_value"] == 1000.0
    )


def test_c3_a_position_row_says_how_old_its_price_is_or_that_it_has_none(client, db_session):
    _real_book_position(db_session, current_price=None)
    row = next(r for r in _rows(client) if r["symbol"] == "V240POS")
    assert {"price_as_of", "price_status", "price_is_stale"} & set(row), sorted(row)  # none of these exists
