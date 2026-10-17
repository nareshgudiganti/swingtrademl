"""bx8: upcoming results / corporate actions, counted in trading days, read-only."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from swing_trade_ml.api.v1.endpoints import beginner
from swing_trade_ml.brain.modules.m13_news.calendar import trading_days_until
from swing_trade_ml.core.enums import PositionStatus
from swing_trade_ml.core.market_session import IST
from swing_trade_ml.db.models.feeds import UpcomingEvent
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Position, Strategy
from swing_trade_ml.services.beginner_views import (
    held_symbols,
    upcoming_events,
    watchlist_symbols,
)

HEADERS = {"X-API-Key": "test-api-key"}


@pytest.fixture(autouse=True)
def _read_only_db_is_the_test_session(db_session):
    """/beginner reads through the read-only dependency; point it at the rolled-back test session."""
    from swing_trade_ml.main import app
    from swing_trade_ml.services.brain_observatory.db import get_readonly_db

    app.dependency_overrides[get_readonly_db] = lambda: db_session
    yield
    app.dependency_overrides.pop(get_readonly_db, None)


TODAY = date(2026, 10, 19)  # Monday; Tue 20 Oct is a market holiday


def _ev(db, symbol, kind, day, detail=""):
    db.add(UpcomingEvent(symbol=symbol, kind=kind, event_date=day, detail=detail))


def test_window_is_counted_in_trading_days_and_sorted(db_session):
    _ev(db_session, "TODAYCO", "results", TODAY)
    _ev(db_session, "ZHOLI", "results", date(2026, 10, 21))  # 20 Oct holiday skipped
    _ev(db_session, "AHOLI", "results", date(2026, 10, 21))
    _ev(db_session, "THREEDAY", "results", date(2026, 10, 23))
    _ev(db_session, "SPLITCO", "corporate_action", date(2026, 10, 24), "Split / bonus")
    _ev(db_session, "FARAWAY", "results", TODAY + timedelta(days=30))
    _ev(db_session, "PASTCO", "results", TODAY - timedelta(days=3))
    db_session.flush()

    mine = ["TODAYCO", "ZHOLI", "AHOLI", "THREEDAY", "SPLITCO", "FARAWAY", "PASTCO"]
    rows = upcoming_events(db_session, mine, TODAY)
    by = {r["symbol"]: r for r in rows}

    assert "FARAWAY" not in by and "PASTCO" not in by
    assert by["TODAYCO"]["trading_days_away"] == 0
    assert by["TODAYCO"]["plain"] == "Results today — prices can jump either way"
    assert by["AHOLI"]["trading_days_away"] == 1  # holiday not counted
    # Wed 21 Oct is 1 trading day away but 2 calendar days: never "tomorrow".
    assert by["AHOLI"]["plain"] == "Results on Wed 21 Oct (1 trading day away) — prices can jump either way"
    assert by["THREEDAY"]["trading_days_away"] == 3
    assert (
        by["THREEDAY"]["plain"] == "Results on Fri 23 Oct (3 trading days away) — prices can jump either way"
    )
    assert by["SPLITCO"]["plain"] == "Split / bonus on Sat 24 Oct (3 trading days away)"
    assert by["SPLITCO"]["date"] == "2026-10-24"
    keys = [(r["date"], r["symbol"]) for r in rows]
    assert keys == sorted(keys)
    assert [r["symbol"] for r in rows if r["date"] == "2026-10-21"] == ["AHOLI", "ZHOLI"]


def test_event_wording_uses_calendar_facts(db_session):
    """F4: a weekend/holiday event seen the trading day before is not "today"."""
    fri = date(2026, 10, 16)
    _ev(db_session, "SATCO", "results", date(2026, 10, 17))
    _ev(db_session, "SATCA", "corporate_action", date(2026, 10, 17), "Dividend")
    _ev(db_session, "MONCO", "results", date(2026, 10, 19))
    _ev(db_session, "FRICO", "corporate_action", fri, "Dividend")
    db_session.flush()
    rows = upcoming_events(db_session, ["SATCO", "SATCA", "MONCO", "FRICO"], fri)
    by = {r["symbol"]: r for r in rows}
    assert by["SATCO"]["trading_days_away"] == 0
    assert by["SATCO"]["plain"] == (
        "Results on Sat 17 Oct (before the next market day) — prices can jump either way"
    )
    assert by["SATCA"]["plain"] == "Dividend on Sat 17 Oct (before the next market day)"
    assert by["MONCO"]["plain"] == "Results on Mon 19 Oct (1 trading day away) — prices can jump either way"
    assert by["FRICO"]["plain"] == "Dividend today"
    assert not any("tomorrow" in r["plain"] for r in rows)


def test_window_edge_is_trading_days_not_calendar_days(db_session):
    d = TODAY
    while trading_days_until(TODAY, d) < 15:
        d += timedelta(days=1)
    nxt = d + timedelta(days=1)
    while trading_days_until(TODAY, nxt) == 15:
        nxt += timedelta(days=1)  # first calendar day that is trading day 16
    _ev(db_session, "EDGEIN", "results", d)
    _ev(db_session, "EDGEOUT", "results", nxt)
    db_session.flush()
    syms = {r["symbol"] for r in upcoming_events(db_session, ["EDGEIN", "EDGEOUT"], TODAY)}
    assert syms == {"EDGEIN"}


def test_symbol_filter(db_session):
    _ev(db_session, "AAA", "results", TODAY)
    _ev(db_session, "BBB", "results", TODAY)
    db_session.flush()
    assert [r["symbol"] for r in upcoming_events(db_session, ["BBB"], TODAY)] == ["BBB"]
    assert upcoming_events(db_session, [], TODAY) == []


def test_held_uses_open_paper_bot_positions_only(db_session):
    bot = Strategy(name="bx8_bot", strategy_type="ml_swing", mode="paper", is_active=True)
    real = Strategy(name="real_trading", strategy_type="ml_swing", mode="live", is_active=True)
    db_session.add_all([bot, real])
    db_session.flush()
    insts = {}
    for i, s in enumerate(["BXHELD", "BXCLOSED", "BXREAL", "BXLIVEMODE"]):
        inst = Instrument(instrument_token=880_000 + i, tradingsymbol=s, exchange="NSE")
        db_session.add(inst)
        insts[s] = inst
    db_session.flush()

    def pos(sym, strat, mode, status):
        db_session.add(
            Position(
                strategy_id=strat.id,
                instrument_id=insts[sym].id,
                mode=mode,
                quantity=1,
                entry_price=10.0,
                entry_at=datetime.now(UTC),
                status=status,
            )
        )

    pos("BXHELD", bot, "paper", PositionStatus.OPEN)
    pos("BXCLOSED", bot, "paper", PositionStatus.CLOSED)
    pos("BXREAL", real, "paper", PositionStatus.OPEN)
    pos("BXLIVEMODE", bot, "live", PositionStatus.OPEN)
    db_session.flush()

    held = set(held_symbols(db_session))
    assert "BXHELD" in held
    assert not held & {"BXCLOSED", "BXREAL", "BXLIVEMODE"}


def test_watchlist_symbols(db_session):
    db_session.add_all(
        [
            Instrument(instrument_token=881_001, tradingsymbol="BXWL", exchange="NSE", is_watchlisted=True),
            Instrument(instrument_token=881_002, tradingsymbol="BXNOTWL", exchange="NSE"),
        ]
    )
    db_session.flush()
    wl = set(watchlist_symbols(db_session))
    assert "BXWL" in wl and "BXNOTWL" not in wl


def _counts(db):
    return {
        t.__name__: db.scalar(select(func.count()).select_from(t))
        for t in (UpcomingEvent, Position, Strategy, Instrument)
    }


def test_endpoint_is_get_only_read_only_and_needs_auth(client, db_session):
    today = datetime.now(IST).date()
    _ev(db_session, "BXENDPT", "results", today, "x")
    db_session.commit()
    before = _counts(db_session)

    assert client.get("/api/v1/beginner/events").status_code == 401

    r = client.get("/api/v1/beginner/events?scope=all", headers=HEADERS)
    assert r.status_code == 200
    item = next(i for i in r.json() if i["symbol"] == "BXENDPT")
    assert item["trading_days_away"] == 0
    r2 = client.get("/api/v1/beginner/events?symbol=BXENDPT&scope=held", headers=HEADERS)
    assert [i["symbol"] for i in r2.json()] == ["BXENDPT"]  # symbol overrides scope
    assert client.get("/api/v1/beginner/events?scope=bogus", headers=HEADERS).status_code == 422

    assert _counts(db_session) == before
    methods = {m for route in beginner.router.routes for m in route.methods}
    assert methods == {"GET"}
