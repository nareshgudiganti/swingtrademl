"""Buying a stock already held grows one position (weighted-average price),
rather than adding a new row."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from swing_trade_ml.core.enums import PositionStatus
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Position, Strategy
from swing_trade_ml.services import execution


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr(execution.notifier, "send_sync", lambda text, event=None: True)


def _setup(db, symbol="MRGTEST"):
    inst = Instrument(instrument_token=987001, tradingsymbol=symbol, exchange="NSE", is_watchlisted=True)
    strat = Strategy(name=f"s_{symbol}", strategy_type="ml_swing", mode="paper", is_active=True,
                     execution_mode="advisory", params={})
    db.add_all([inst, strat])
    db.commit()
    return strat, inst


def test_second_buy_merges_into_one_row_with_average(db_session):
    strat, inst = _setup(db_session)
    p1 = execution.manual_open_position(db_session, strat, inst, 10, 100.0, stop_loss=90.0, take_profit=108.0,
                                        brokerage=0.0, taxes=1.0)
    p2 = execution.manual_open_position(db_session, strat, inst, 30, 120.0, stop_loss=110.0, take_profit=130.0,
                                        brokerage=0.0, taxes=3.0)

    assert p2.id == p1.id
    rows = db_session.execute(select(func.count()).select_from(Position).where(
        Position.instrument_id == inst.id, Position.status == PositionStatus.OPEN)).scalar_one()
    assert rows == 1
    assert p2.quantity == 40
    assert p2.initial_quantity == 40
    assert p2.entry_price == pytest.approx((10 * 100 + 30 * 120) / 40)  # 115.0
    assert p2.total_charges == pytest.approx(4.0)
    # protection is never loosened by an add
    assert p2.stop_loss == 90.0
    assert p2.take_profit == 108.0


def test_different_stock_still_gets_its_own_row(db_session):
    strat, a = _setup(db_session, "AAA")
    b = Instrument(instrument_token=987002, tradingsymbol="BBB", exchange="NSE", is_watchlisted=True)
    db_session.add(b)
    db_session.commit()
    p1 = execution.manual_open_position(db_session, strat, a, 5, 50.0)
    p2 = execution.manual_open_position(db_session, strat, b, 5, 60.0)
    assert p1.id != p2.id
