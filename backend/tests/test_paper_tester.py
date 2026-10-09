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


def test_tester_positions_are_not_the_bots_money(db_session):
    """Prod 2026-10-08: eight test buys filled all of the bot's position slots
    (room 0) and spent its paper cash. The testing book has its own capital."""
    from swing_trade_ml.brokers import paper_broker
    from swing_trade_ml.services import portfolio, risk

    cash_before = paper_broker.get_available_cash(db_session)
    value_before, _ = portfolio.portfolio_value_and_cash(db_session, TradingMode.PAPER)
    count_before = risk.open_position_count(db_session, TradingMode.PAPER)
    holdings_before = len(risk.open_holdings(db_session, TradingMode.PAPER))

    inst = _instrument(db_session, "PTSLOT", 880003)
    _price(db_session, inst, 100.0)
    tester_paper.paper_buy(db_session, "PTSLOT", 50, "large")

    assert paper_broker.get_available_cash(db_session) == pytest.approx(cash_before)
    value_after, _ = portfolio.portfolio_value_and_cash(db_session, TradingMode.PAPER)
    assert value_after == pytest.approx(value_before)
    assert risk.open_position_count(db_session, TradingMode.PAPER) == count_before
    assert len(risk.open_holdings(db_session, TradingMode.PAPER)) == holdings_before
    stats = portfolio.performance_stats(db_session, TradingMode.PAPER)
    assert stats["open_positions"] == 0
    # ...while the testing book still sees its own position.
    assert tester_paper.available_cash(db_session) < 1_000_000.0
