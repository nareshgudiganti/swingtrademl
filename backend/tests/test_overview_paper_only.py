"""Phase 2 audit: the figures behind the Paper Overview page never include real (My Holdings) or
manual-testing money. The four calls the page makes are summary, positions, equity curve and risk
limits. Each is called twice: with only the bot's paper rows, then with a real-book position and
trade and a testing-book position added. Every figure must come out the same."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import PortfolioSnapshot, Position, Strategy, Trade
from swing_trade_ml.services import tester_paper

API_KEY = {"X-API-Key": "test-api-key"}
NOW = datetime(2026, 10, 1, 9, 30, tzinfo=UTC)


def _strategy(db, name, mode="paper", stype="ml_swing"):
    s = Strategy(name=name, strategy_type=stype, mode=mode, is_active=False)
    db.add(s)
    db.flush()
    return s


def _inst(db, sym):
    inst = Instrument(instrument_token=abs(hash(sym)) % 10_000_000, tradingsymbol=sym, exchange="NSE")
    db.add(inst)
    db.flush()
    return inst


def _position(db, strategy, sym, mode, price=100.0, qty=10):
    inst = _inst(db, sym)
    p = Position(strategy_id=strategy.id, instrument_id=inst.id, mode=mode, status="OPEN", quantity=qty,
                 initial_quantity=qty, entry_price=price, current_price=price, entry_at=NOW, total_charges=5.0)
    db.add(p)
    db.flush()
    return p


def _trade(db, position, strategy, sym, mode, pnl):
    db.add(Trade(position_id=position.id, strategy_id=strategy.id, instrument_id=position.instrument_id,
                 mode=mode, symbol=sym, quantity=5, entry_price=100, exit_price=110, entry_at=NOW, exit_at=NOW,
                 gross_pnl=pnl, charges=0, net_pnl=pnl, return_pct=0.1, is_win=pnl > 0))
    db.flush()


def _overview_figures(client):
    summary = client.get("/api/v1/portfolio/summary?book=bot", headers=API_KEY).json()
    positions = client.get("/api/v1/portfolio/positions/detailed?book=bot", headers=API_KEY).json()
    curve = client.get("/api/v1/portfolio/equity-curve?days=180", headers=API_KEY).json()
    limits = client.get("/api/v1/risk/limits", headers=API_KEY).json()
    return {
        "summary": summary,
        "symbols": sorted(p["symbol"] for p in positions),
        "curve": curve,
        "limits": {k: limits[k] for k in ("portfolio_value", "cash", "open_positions", "invested_inr", "room_inr")},
    }


@pytest.fixture()
def bot_only(db_session):
    bot = _strategy(db_session, "p2_bot")
    pos = _position(db_session, bot, "P2BOT", "paper")
    _trade(db_session, pos, bot, "P2BOT", "paper", 40.0)
    db_session.add(PortfolioSnapshot(mode="paper", ts=NOW, cash=1000.0, holdings_value=1000.0, total_value=2000.0))
    db_session.flush()
    return bot


def test_overview_figures_ignore_real_and_testing_books(client, db_session, bot_only):
    before = _overview_figures(client)
    assert before["symbols"] == ["P2BOT"]  # the test is looking at real rows, not an empty page

    real = _strategy(db_session, "real_trading", mode="live", stype="real_trading")
    real_pos = _position(db_session, real, "P2REAL", "live", price=500.0, qty=100)
    _trade(db_session, real_pos, real, "P2REAL", "live", 9999.0)
    tester = tester_paper.get_or_create_strategy(db_session)
    _position(db_session, tester, "P2TEST", "paper", price=300.0, qty=20)
    after = _overview_figures(client)

    assert after == before
