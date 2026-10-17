"""bx4: evidence summary for the paper bot; brain trial sealed to a count."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest
from sqlalchemy import delete, func, select

from swing_trade_ml.api.v1.endpoints import beginner
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import PositionStatus
from swing_trade_ml.core.market_session import IST
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.trading import PortfolioSnapshot, Position, Strategy, Trade
from swing_trade_ml.services import beginner_views
from swing_trade_ml.services.beginner_views import evidence_summary

HEADERS = {"X-API-Key": "test-api-key"}


@pytest.fixture(autouse=True)
def _read_only_db_is_the_test_session(db_session):
    """/beginner reads through the read-only dependency; point it at the rolled-back test session."""
    from swing_trade_ml.main import app
    from swing_trade_ml.services.brain_observatory.db import get_readonly_db

    app.dependency_overrides[get_readonly_db] = lambda: db_session
    yield
    app.dependency_overrides.pop(get_readonly_db, None)


def _since() -> datetime:
    return datetime.combine(settings.PAPER_TRIAL_START_DATE, time.min, tzinfo=IST)


def _strategy(db, name):
    s = Strategy(name=name, strategy_type="ml_swing", mode="paper", is_active=True)
    db.add(s)
    db.flush()
    return s


def _inst(db, token, sym, **kw):
    i = Instrument(instrument_token=token, tradingsymbol=sym, exchange="NSE", **kw)
    db.add(i)
    db.flush()
    return i


def _trade(db, strat, inst, net, charges, when, win):
    db.add(
        Trade(
            strategy_id=strat.id,
            instrument_id=inst.id,
            symbol=inst.tradingsymbol,
            mode="paper",
            quantity=1,
            entry_price=100.0,
            exit_price=100.0 + net,
            entry_at=when,
            exit_at=when,
            gross_pnl=net + charges,
            charges=charges,
            net_pnl=net,
            return_pct=net / 100.0,
            is_win=win,
        )
    )


def _day_candle(db, inst, day: date, close: float):
    ts = datetime.combine(day, time.min, tzinfo=IST)
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


def test_counts_only_paper_bot_trades_and_sums_charges(db_session, monkeypatch):
    monkeypatch.setattr(beginner_views, "finished_brain_ideas", lambda db: 4)
    base = evidence_summary(db_session)["bot"]  # whatever the test DB already holds
    bot = _strategy(db_session, "bx4_bot")
    real = _strategy(db_session, "real_trading")
    tester = _strategy(db_session, "tester_paper")
    inst = _inst(db_session, 890_001, "BX4A")
    now = _since() + timedelta(days=2)
    _trade(db_session, bot, inst, 100.0, 5.0, now, True)
    _trade(db_session, bot, inst, -40.0, 3.0, now, False)
    _trade(db_session, real, inst, 5000.0, 50.0, now, True)
    _trade(db_session, tester, inst, 7000.0, 70.0, now, True)
    _trade(db_session, bot, inst, 999.0, 9.0, _since() - timedelta(days=3), True)  # before trial
    db_session.add(
        Position(
            strategy_id=bot.id,
            instrument_id=inst.id,
            mode="paper",
            quantity=10,
            entry_price=100.0,
            current_price=103.0,
            unrealized_pnl=30.0,
            entry_at=datetime.now(UTC),
            status=PositionStatus.OPEN,
        )
    )
    for strat, sym in ((real, "BX4R"), (tester, "BX4T")):
        db_session.add(
            Position(
                strategy_id=strat.id,
                instrument_id=inst.id,
                mode="paper",
                quantity=10,
                entry_price=100.0,
                current_price=150.0,
                unrealized_pnl=500.0,
                entry_at=datetime.now(UTC),
                status=PositionStatus.OPEN,
            )
        )
    db_session.flush()

    b = evidence_summary(db_session)["bot"]
    assert evidence_summary(db_session)["paper_label"] == "Practice money (paper)"
    assert b["since"] == settings.PAPER_TRIAL_START_DATE.isoformat()
    assert b["finished_trades"] - base["finished_trades"] == 2
    assert round(b["profit_booked"] - base["profit_booked"], 6) == 60.0
    assert round(b["costs_paid"] - base["costs_paid"], 6) == 8.0
    assert round(b["profit_open"] - base["profit_open"], 6) == 30.0


def test_few_trades_note_and_win_rate_unconditionally(db_session, monkeypatch):
    real_stats = beginner_views.performance_stats

    def fake(db, **kw):
        return {**real_stats(db, **kw), "total_trades": 2, "win_rate": 0.5}

    monkeypatch.setattr(beginner_views, "performance_stats", fake)
    b = evidence_summary(db_session)["bot"]
    assert b["win_rate_pct"] == 50.0
    assert b["enough_trades"] is False
    assert b["note"] == "Too few finished trades to judge — this could be luck."


def test_enough_trades_clears_note(db_session):
    bot = _strategy(db_session, "bx4_bot2")
    inst = _inst(db_session, 890_002, "BX4B")
    for _ in range(30):
        _trade(db_session, bot, inst, 10.0, 1.0, _since() + timedelta(days=1), True)
    db_session.flush()
    b = evidence_summary(db_session)["bot"]
    assert b["finished_trades"] >= 30
    assert b["enough_trades"] is True
    assert b["note"] == ""


def _snap(db, day, value):
    ts = datetime.combine(day, time.min, tzinfo=IST)
    db.add(
        PortfolioSnapshot(
            mode="paper",
            ts=ts,
            cash=value,
            holdings_value=0.0,
            total_value=value,
            peak_value=value,
            drawdown_pct=0.0,
        )
    )


def test_worst_fall_concrete_and_null_without_snapshots(db_session):
    db_session.execute(delete(PortfolioSnapshot))  # rolled back with the test
    db_session.flush()
    assert evidence_summary(db_session)["bot"]["worst_fall_from_peak_pct"] is None
    d = settings.PAPER_TRIAL_START_DATE
    _snap(db_session, d + timedelta(days=1), 100000.0)
    db_session.flush()
    assert evidence_summary(db_session)["bot"]["worst_fall_from_peak_pct"] is None  # one point
    _snap(db_session, d + timedelta(days=2), 90000.0)
    db_session.flush()
    assert evidence_summary(db_session)["bot"]["worst_fall_from_peak_pct"] == 10.0


def test_benchmarks_from_candles_and_null_when_missing(db_session):
    since_day = settings.PAPER_TRIAL_START_DATE
    d0, d1 = since_day + timedelta(days=1), since_day + timedelta(days=8)
    nifty = _inst(db_session, 890_010, "BX4NIFTY")
    w1 = _inst(db_session, 890_011, "BX4W1", is_watchlisted=True)
    w2 = _inst(db_session, 890_012, "BX4W2", is_watchlisted=True)
    w3 = _inst(db_session, 890_013, "BX4W3", is_watchlisted=True)  # one end only -> skipped
    for inst, a, z in ((nifty, 100.0, 110.0), (w1, 100.0, 120.0), (w2, 200.0, 200.0)):
        _day_candle(db_session, inst, d0, a)
        _day_candle(db_session, inst, d1, z)
    _day_candle(db_session, w3, d1, 50.0)
    db_session.flush()

    change = beginner_views.period_change_pct
    assert change(db_session, [nifty.id], _since()) == 10.0
    assert change(db_session, [w1.id, w2.id, w3.id], _since()) == 10.0  # (20% + 0%) / 2
    assert change(db_session, [], _since()) is None
    assert change(db_session, [w3.id], _since()) is None  # single day: no period


def test_brain_trial_is_sealed_to_a_count(db_session, monkeypatch):
    monkeypatch.setattr(beginner_views, "finished_brain_ideas", lambda db: 7)
    bt = evidence_summary(db_session)["brain_trial"]
    assert set(bt) == {"since", "finished", "needed", "sealed", "sealed_note"}
    assert bt["since"] == "2026-10-14"
    assert bt["finished"] == 7 and bt["needed"] == 30 and bt["sealed"] is True
    assert bt["sealed_note"] == "Results stay hidden until the planned review so the test stays fair."
    assert not [k for k in bt if any(w in k for w in ("win", "profit", "return", "pnl"))]


def test_endpoint_is_get_only_read_only_and_needs_auth(client, db_session):
    tables = (Trade, Position, Strategy, Instrument, Candle)

    def counts():
        return {t.__name__: db_session.scalar(select(func.count()).select_from(t)) for t in tables}

    db_session.commit()
    before = counts()
    assert client.get("/api/v1/beginner/evidence").status_code == 401
    r = client.get("/api/v1/beginner/evidence", headers=HEADERS)
    assert r.status_code == 200
    assert set(r.json()) == {"paper_label", "bot", "brain_trial"}
    assert counts() == before
    methods = {m for route in beginner.router.routes for m in route.methods}
    assert methods == {"GET"}
