"""Manual paper-testing book — separate from the bot portfolio."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import PositionStatus, TradingMode
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Order, Position, Strategy
from swing_trade_ml.services import tester_paper
from swing_trade_ml.services.execution import close_position
from swing_trade_ml.core.enums import ExitReason


@pytest.fixture(autouse=True)
def _enable_paper_tester(monkeypatch):
    monkeypatch.setattr(settings, "PAPER_TESTER_ENABLED", True)
    monkeypatch.setattr(settings, "PAPER_TESTER_STARTING_CAPITAL", 1_000_000.0)
    monkeypatch.setattr(settings, "TRADING_MODE", "paper")


def _instrument(db, symbol: str, token: int) -> Instrument:
    row = Instrument(
        instrument_token=token,
        tradingsymbol=symbol,
        exchange="NSE",
        is_watchlisted=True,
        is_active=True,
    )
    db.add(row)
    db.flush()
    return row


def _price(db, instrument: Instrument, close: float) -> None:
    from swing_trade_ml.db.models.market import Candle

    db.add(
        Candle(
            instrument_id=instrument.id,
            interval="day",
            ts=datetime(2026, 10, 1, 18, 30, tzinfo=UTC),
            open=close,
            high=close * 1.01,
            low=close * 0.99,
            close=close,
            volume=100_000,
        )
    )
    db.flush()


def test_tester_buy_and_sell_stay_on_tester_strategy(db_session):
    inst = _instrument(db_session, "PTST", 880001)
    _price(db_session, inst, 100.0)

    pos = tester_paper.paper_buy(db_session, "PTST", 10, "large")
    strat = db_session.get(Strategy, pos.strategy_id)
    assert strat is not None and strat.name == tester_paper.TESTER_PAPER_STRATEGY_NAME

    bot = db_session.execute(
        select(Position).where(
            Position.status == PositionStatus.OPEN,
            Position.strategy_id != pos.strategy_id,
        )
    ).scalars().all()

    trade = close_position(db_session, pos, None, ExitReason.MANUAL)
    assert trade is not None
    assert trade.net_pnl is not None
    assert db_session.query(Order).filter_by(mode=TradingMode.PAPER).count() >= 2


def test_tester_buy_rejected_when_disabled(db_session, monkeypatch):
    monkeypatch.setattr(settings, "PAPER_TESTER_ENABLED", False)
    inst = _instrument(db_session, "PTOFF", 880002)
    _price(db_session, inst, 50.0)
    with pytest.raises(tester_paper.PaperTesterDisabled):
        tester_paper.paper_buy(db_session, "PTOFF", 1, "midcap")
