"""Phase 2 audit: in PAPER mode (the only mode allowed, CLAUDE.md), the figures behind the Paper Overview page
never include real (My Holdings) or manual-testing money. The page makes four calls: summary, positions,
equity curve and risk limits. Each is read twice: with only the bot's paper rows, then with a real-book
position and trade and a testing-book position and trade added. Every figure must come out the same, and a
snapshot taken after the extra rows must value the account exactly as one taken before them.

Not covered, by design: TRADING_MODE=live. There, cash comes from the real Zerodha margins and the risk limits
and snapshots count real holdings, so the page would not be paper. Live is forbidden without the owner."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import PortfolioSnapshot, Position, Strategy, Trade
from swing_trade_ml.services import tester_paper

API_KEY = {"X-API-Key": "test-api-key"}
NOW = datetime.now(UTC) - timedelta(days=2)


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
    p = Position(
        strategy_id=strategy.id,
        instrument_id=inst.id,
        mode=mode,
        status="OPEN",
        quantity=qty,
        initial_quantity=qty,
        entry_price=price,
        current_price=price,
        entry_at=NOW,
        total_charges=5.0,
    )
    db.add(p)
    db.flush()
    return p


def _trade(db, position, strategy, sym, mode, pnl):
    db.add(
        Trade(
            position_id=position.id,
            strategy_id=strategy.id,
            instrument_id=position.instrument_id,
            mode=mode,
            symbol=sym,
            quantity=5,
            entry_price=100,
            exit_price=110,
            entry_at=NOW,
            exit_at=NOW,
            gross_pnl=pnl,
            charges=0,
            net_pnl=pnl,
            return_pct=0.1,
            is_win=pnl > 0,
        )
    )
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
        "limits": {
            k: limits[k] for k in ("portfolio_value", "cash", "open_positions", "invested_inr", "room_inr")
        },
    }


@pytest.fixture()
def bot_only(db_session):
    bot = _strategy(db_session, "p2_bot")
    pos = _position(db_session, bot, "P2BOT", "paper")
    _trade(db_session, pos, bot, "P2BOT", "paper", 40.0)
    db_session.add(
        PortfolioSnapshot(mode="paper", ts=NOW, cash=1000.0, holdings_value=1000.0, total_value=2000.0)
    )
    db_session.flush()
    return bot


def _snapshot_value(client):
    assert client.post("/api/v1/portfolio/snapshot", headers=API_KEY).status_code == 200
    curve = client.get("/api/v1/portfolio/equity-curve?days=180", headers=API_KEY).json()
    assert curve, "the equity curve must have points, or comparing it proves nothing"
    last = curve[-1]
    return (last["total_value"], last["cash"], last["holdings_value"], last["open_positions"])


def test_overview_figures_ignore_real_and_testing_books(client, db_session, bot_only):
    # A snapshot first, so both readings below share the same latest point (a snapshot moves "today's P&L").
    snap_before = _snapshot_value(client)
    before = _overview_figures(client)
    assert before["symbols"] == ["P2BOT"]  # the test is looking at real rows, not an empty page
    assert before["curve"], "the equity curve must have points, or comparing it proves nothing"

    real = _strategy(db_session, "real_trading", mode="live", stype="real_trading")
    real_pos = _position(db_session, real, "P2REAL", "live", price=500.0, qty=100)
    _trade(db_session, real_pos, real, "P2REAL", "live", 9999.0)
    tester = tester_paper.get_or_create_strategy(db_session)
    test_pos = _position(db_session, tester, "P2TEST", "paper", price=300.0, qty=20)
    _trade(
        db_session, test_pos, tester, "P2TEST", "paper", 777.0
    )  # testing-book profit must not reach paper cash

    assert _overview_figures(client) == before
    # A snapshot taken now values the paper account exactly as before the real and testing rows existed.
    assert _snapshot_value(client) == snap_before
