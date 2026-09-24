"""The Portfolio tab shows the bot's own book; My Holdings shows the shares
bought by hand in Zerodha. The two are separated by strategy, not by mode —
hand-bought holdings are stored as mode="live" whatever the bot is doing, so
a mode filter alone would merge them into the bot's list the day the bot
goes live.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from swing_trade_ml.api.v1.endpoints import portfolio as portfolio_ep
from swing_trade_ml.core.enums import PositionStatus
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Position, Strategy, Trade
from swing_trade_ml.services.portfolio import REAL_TRADING_STRATEGY_NAME

HEADERS = {"X-API-Key": "test-api-key"}


def _books(db_session):
    """A live bot position and a hand-bought holding, both mode="live" —
    the arrangement that exists once the bot is switched to live."""
    bot = Strategy(
        name="ml_swing_live",
        strategy_type="ml_swing",
        mode="live",
        is_active=True,
        execution_mode="auto",
        params={},
    )
    real = Strategy(
        name=REAL_TRADING_STRATEGY_NAME,
        strategy_type="ml_swing",
        mode="live",
        is_active=True,
        execution_mode="advisory",
        params={},
    )
    db_session.add_all([bot, real])
    db_session.flush()

    bot_inst = Instrument(
        instrument_token=556001, tradingsymbol="BOTBOUGHT", exchange="NSE", is_watchlisted=True
    )
    mine_inst = Instrument(
        instrument_token=556002, tradingsymbol="IBOUGHTIT", exchange="NSE", is_watchlisted=True
    )
    db_session.add_all([bot_inst, mine_inst])
    db_session.flush()

    db_session.add_all(
        [
            Position(
                strategy_id=bot.id,
                instrument_id=bot_inst.id,
                mode="live",
                quantity=10,
                entry_price=100.0,
                current_price=110.0,
                entry_at=datetime.now(UTC),
                status=PositionStatus.OPEN,
            ),
            Position(
                strategy_id=real.id,
                instrument_id=mine_inst.id,
                mode="live",
                quantity=5,
                entry_price=200.0,
                current_price=220.0,
                entry_at=datetime.now(UTC),
                status=PositionStatus.OPEN,
            ),
        ]
    )
    db_session.commit()
    return bot, real


def _symbols(resp):
    return {row["symbol"] for row in resp.json()}


def test_bot_book_excludes_hand_bought_holdings(client, db_session):
    _books(db_session)

    resp = client.get(
        "/api/v1/portfolio/positions/detailed?mode=live&book=bot", headers=HEADERS
    )

    assert resp.status_code == 200
    symbols = _symbols(resp)
    assert "BOTBOUGHT" in symbols
    assert "IBOUGHTIT" not in symbols


def test_real_book_is_only_hand_bought_holdings(client, db_session):
    _books(db_session)

    resp = client.get("/api/v1/portfolio/positions/detailed?book=real", headers=HEADERS)

    assert resp.status_code == 200
    symbols = _symbols(resp)
    assert "IBOUGHTIT" in symbols
    assert "BOTBOUGHT" not in symbols


def test_book_defaults_to_both(client, db_session):
    _books(db_session)

    resp = client.get("/api/v1/portfolio/positions/detailed?mode=live", headers=HEADERS)

    assert resp.status_code == 200
    assert {"BOTBOUGHT", "IBOUGHTIT"} <= _symbols(resp)


def test_unknown_book_is_rejected(client, db_session):
    resp = client.get("/api/v1/portfolio/positions/detailed?book=nonsense", headers=HEADERS)

    assert resp.status_code == 422


def test_bot_trade_list_excludes_hand_recorded_sales(client, db_session, monkeypatch):
    # The tests run in paper mode, where the two books are already separated
    # by mode alone. Pretending the bot is live is the only way to exercise
    # the case this filter exists for: both books sharing mode="live".
    monkeypatch.setattr(portfolio_ep, "get_broker", lambda: SimpleNamespace(mode="live"))
    bot, real = _books(db_session)
    now = datetime.now(UTC)
    db_session.add_all(
        [
            Trade(
                strategy_id=bot.id,
                symbol="BOTSOLD",
                mode="live",
                quantity=10,
                entry_price=100.0,
                exit_price=115.0,
                entry_at=now,
                exit_at=now,
                gross_pnl=150.0,
                charges=0.0,
                net_pnl=150.0,
                return_pct=0.15,
                is_win=True,
            ),
            Trade(
                strategy_id=real.id,
                symbol="ISOLDIT",
                mode="live",
                quantity=5,
                entry_price=200.0,
                exit_price=190.0,
                entry_at=now,
                exit_at=now,
                gross_pnl=-50.0,
                charges=0.0,
                net_pnl=-50.0,
                return_pct=-0.05,
                is_win=False,
            ),
        ]
    )
    db_session.commit()

    bot_only = client.get("/api/v1/portfolio/trades?book=bot", headers=HEADERS)
    real_only = client.get("/api/v1/portfolio/trades?book=real", headers=HEADERS)

    assert bot_only.status_code == 200
    assert real_only.status_code == 200
    assert "BOTSOLD" in _symbols(bot_only)
    assert "ISOLDIT" not in _symbols(bot_only)
    assert _symbols(real_only) == {"ISOLDIT"}
