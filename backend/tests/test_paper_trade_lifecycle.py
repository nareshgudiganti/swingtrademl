"""One paper trade followed from buy to report, checking that every number agrees at each step.

The parts are tested one by one elsewhere (sizing, risk, exits, the cash ledger, reports). This file is
the end-to-end check the owner asked for on 2026-10-14 (tracker task tv2): buy -> half out at +5% ->
rest out at target (or stop) -> cash, positions, trade history and the summary report must all agree.
A wrong number anywhere along the chain fails it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import SignalType
from swing_trade_ml.db.models.market import Instrument, Quote
from swing_trade_ml.db.models.trading import Order, Position, Strategy, Trade
from swing_trade_ml.services import deployable, execution, portfolio
from swing_trade_ml.strategies.base import SignalDecision

HEADERS = {"X-API-Key": "test-api-key"}
START = settings.PAPER_STARTING_CAPITAL
CENT = 0.01


@pytest.fixture
def market(db_session, monkeypatch):
    """A paper account with one large-cap stock, a calm market and a price we move by hand."""
    from swing_trade_ml.brokers.paper import PaperBroker

    monkeypatch.setattr(
        deployable,
        "current_deployable",
        lambda db: deployable.DeployableCapital(regime="strong", fraction=1.0, context_available=True),
    )
    monkeypatch.setattr(execution.notifier, "send_sync", lambda *a, **kw: None)
    price = {"now": 1000.0}
    monkeypatch.setattr(PaperBroker, "get_ltp", lambda self, keys, db: dict.fromkeys(keys, price["now"]))

    inst = Instrument(instrument_token=738561, tradingsymbol="RELIANCE", exchange="NSE", is_watchlisted=True)
    strat = Strategy(
        name="lifecycle_strategy",
        strategy_type="ml_swing",
        mode="paper",
        params={"scale_out_at_pct": 0.05, "scale_out_fraction": 0.5},
    )
    db_session.add_all([inst, strat])
    db_session.flush()

    def move_to(p: float) -> None:
        # The paper broker fills against its own stored quote; the exit sweep reads get_ltp. Keep both equal.
        price["now"] = p
        quote = db_session.execute(select(Quote).where(Quote.instrument_id == inst.id)).scalar_one_or_none()
        if quote is None:
            db_session.add(Quote(instrument_id=inst.id, last_price=p, ts=datetime.now(UTC)))
        else:
            quote.last_price, quote.ts = p, datetime.now(UTC)
        db_session.flush()

    move_to(1000.0)
    db_session.commit()
    return db_session, strat, inst, move_to


def _buy(db, strat, inst) -> Position:
    execution.process_decision(
        db,
        strat,
        inst,
        SignalDecision(
            signal=SignalType.BUY,
            price=1000.0,
            confidence=0.8,
            stop_loss=960.0,
            take_profit=1080.0,
            reason="lifecycle test",
        ),
    )
    pos = db.execute(select(Position).where(Position.instrument_id == inst.id)).scalar_one()
    assert pos.status == "OPEN" and pos.quantity > 0
    return pos


def _cash(db) -> float:
    return portfolio.portfolio_value_and_cash(db, "paper")[1]


def _trades(db, inst) -> list[Trade]:
    return list(db.execute(select(Trade).where(Trade.instrument_id == inst.id).order_by(Trade.id)).scalars())


def _orders(db, inst) -> list[tuple[str, str, int]]:
    rows = db.execute(select(Order).where(Order.instrument_id == inst.id).order_by(Order.id)).scalars()
    return [(o.transaction_type, o.status, o.quantity) for o in rows]


def _assert_trade_adds_up(t: Trade) -> None:
    assert t.gross_pnl == pytest.approx((t.exit_price - t.entry_price) * t.quantity, abs=CENT)
    assert t.net_pnl == pytest.approx(t.gross_pnl - t.charges, abs=CENT)
    assert t.charges >= 0


def test_buy_half_out_at_five_percent_then_target_and_every_number_agrees(market, client):
    db, strat, inst, move_to = market

    # 1. Buy: one filled order, one open position, cash down by exactly what the position cost.
    pos = _buy(db, strat, inst)
    bought = pos.quantity
    assert _orders(db, inst) == [("BUY", "COMPLETE", bought)]
    assert pos.entry_price == pytest.approx(1000.0, rel=0.002)  # fill = price plus a little slippage
    assert pos.stop_loss == pytest.approx(960.0) and pos.take_profit == pytest.approx(1080.0)
    assert _cash(db) == pytest.approx(START - pos.entry_price * bought - pos.total_charges, abs=CENT)

    # 2. Just under +5% from the real fill (slippage included): nothing is sold yet.
    move_to(round(pos.entry_price * 1.049, 2))
    assert execution.check_exits(db) == []

    # +5% from the fill: half is sold, the rest stays open, and the sale's profit is already in cash.
    move_to(round(pos.entry_price * 1.05 + 0.05, 2))
    closed = execution.check_exits(db)
    assert [t.exit_reason for t in closed] == ["SCALE_OUT"]
    half = closed[0]
    db.refresh(pos)
    assert half.quantity == bought // 2 or half.quantity == bought - bought // 2
    assert pos.status == "OPEN" and pos.quantity == bought - half.quantity
    assert pos.scaled_out_at is not None
    _assert_trade_adds_up(half)
    assert half.net_pnl > 0
    assert _cash(db) == pytest.approx(
        START + half.net_pnl - (pos.entry_price * pos.quantity + pos.total_charges), abs=CENT
    )

    # A second tick at the same price must not sell another half.
    assert execution.check_exits(db) == []

    # 3. Target: the rest is sold and the position is closed.
    move_to(1080.0)
    closed = execution.check_exits(db)
    assert [t.exit_reason for t in closed] == ["TARGET_HIT"]
    db.refresh(pos)
    assert pos.status == "CLOSED"
    trades = _trades(db, inst)
    assert [t.exit_reason for t in trades] == ["SCALE_OUT", "TARGET_HIT"]
    assert sum(t.quantity for t in trades) == bought
    assert _orders(db, inst) == [
        ("BUY", "COMPLETE", bought),
        ("SELL", "COMPLETE", trades[0].quantity),
        ("SELL", "COMPLETE", trades[1].quantity),
    ]
    for t in trades:
        _assert_trade_adds_up(t)
    realized = sum(t.net_pnl for t in trades)

    # 4. Reports: the ledger, the summary and the API all say the same thing.
    assert _cash(db) == pytest.approx(START + realized, abs=CENT)
    stats = portfolio.performance_stats(db, "paper")
    assert stats["total_trades"] == 2
    assert stats["winning_trades"] == 2 and stats["win_rate"] == pytest.approx(1.0)
    assert stats["open_positions"] == 0
    assert stats["realized_pnl"] == pytest.approx(realized, abs=CENT)
    assert stats["unrealized_pnl"] == pytest.approx(0.0, abs=CENT)
    assert stats["total_value"] == pytest.approx(START + realized, abs=CENT)
    assert stats["total_charges"] == pytest.approx(sum(t.charges for t in trades), abs=CENT)

    api = client.get("/api/v1/portfolio/summary?mode=paper", headers=HEADERS)
    assert api.status_code == 200
    assert api.json()["realized_pnl"] == pytest.approx(realized, abs=CENT)
    listed = client.get("/api/v1/portfolio/trades?mode=paper", headers=HEADERS)
    assert listed.status_code == 200
    mine = [r for r in listed.json() if r.get("instrument_id") == inst.id or r.get("symbol") == "RELIANCE"]
    assert len(mine) == 2


def test_buy_then_stop_loss_and_every_number_agrees(market):
    db, strat, inst, move_to = market

    pos = _buy(db, strat, inst)
    bought = pos.quantity

    move_to(955.0)  # through the 960 stop
    closed = execution.check_exits(db)
    assert [t.exit_reason for t in closed] == ["STOP_LOSS_HIT"]
    db.refresh(pos)
    assert pos.status == "CLOSED"
    (loss,) = _trades(db, inst)
    assert loss.quantity == bought
    _assert_trade_adds_up(loss)
    assert loss.net_pnl < 0
    # About -4.5% on the stock, plus slippage and charges; never a gain.
    assert -0.06 < loss.net_pnl / (pos.entry_price * bought) < -0.04

    assert _cash(db) == pytest.approx(START + loss.net_pnl, abs=CENT)
    stats = portfolio.performance_stats(db, "paper")
    assert stats["total_trades"] == 1 and stats["losing_trades"] == 1
    assert stats["realized_pnl"] == pytest.approx(loss.net_pnl, abs=CENT)
    assert stats["total_value"] == pytest.approx(START + loss.net_pnl, abs=CENT)
