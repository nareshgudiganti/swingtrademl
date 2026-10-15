"""Real orders the owner places by hand from My Holdings.

The bot stays on paper for its trial; the owner's own Zerodha shares are real.
This module is every check in front of a real order — the latch, the market
clock, the money limits, what is actually owned, one waiting order per stock —
so a refusal is always a plain sentence and nothing reaches Zerodha.
Placement and bookkeeping stay in services/execution.py.
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from kiteconnect.exceptions import KiteException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from swing_trade_ml.core import market_session
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import OrderStatus, PositionStatus, TradingMode, TransactionType
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Order, Position, Strategy
from swing_trade_ml.services import execution, system_state
from swing_trade_ml.services.portfolio import REAL_TRADING_STRATEGY_NAME

IST = ZoneInfo("Asia/Kolkata")
_WAITING = (OrderStatus.PENDING, OrderStatus.OPEN)
_NOT_SPENT = (OrderStatus.REJECTED, OrderStatus.CANCELLED)


class RealOrderRefused(Exception):  # noqa: N818 - name fixed by the plan
    """Why a real order was not sent, in one plain sentence. Nothing reached Zerodha."""


def _require_switch_and_market() -> None:
    if not settings.ALLOW_REAL_HOLDINGS_ORDERS:
        raise RealOrderRefused("Real orders are switched off.")
    if not market_session.is_open():
        opens = market_session.when(market_session.session().next_open)
        raise RealOrderRefused(f"The market is closed right now. It opens {opens}.")


def _kite_ready(db: Session):
    from swing_trade_ml.brokers.kite import kite_broker

    if not kite_broker.load_session(db):
        raise RealOrderRefused("Zerodha is not logged in today. Log in to Zerodha first.")
    return kite_broker


def _waiting(db: Session, strategy_id: int, instrument_id: int) -> bool:
    return (
        db.execute(
            select(Order.id).where(
                Order.strategy_id == strategy_id,
                Order.instrument_id == instrument_id,
                Order.status.in_(_WAITING),
            )
        ).first()
        is not None
    )


def quote(db: Session, instrument: Instrument) -> float:
    kite = _kite_ready(db)
    key = f"{instrument.exchange}:{instrument.tradingsymbol}"
    try:
        price = kite.get_ltp([key], db).get(key)
    except KiteException:
        price = None
    if not price:
        raise RealOrderRefused("Could not get a live price from Zerodha, so nothing was sent.")
    return float(price)


def spent_today(db: Session, strategy_id: int, now: datetime | None = None) -> float:
    """Rupees of real buys placed today (IST), waiting or filled.

    A waiting market order has no fill price yet, so its reference price
    counts (Kite reports average_price 0 until it fills, so 0 means "none
    yet"); a refused or cancelled one does not."""
    local = (now or datetime.now(UTC)).astimezone(IST)
    start = datetime.combine(local.date(), time(0, 0), tzinfo=IST).astimezone(UTC)
    total = db.execute(
        select(
            func.coalesce(
                func.sum(Order.quantity * func.coalesce(func.nullif(Order.average_price, 0), Order.price)),
                0.0,
            )
        ).where(
            Order.strategy_id == strategy_id,
            Order.mode == TradingMode.LIVE,
            Order.transaction_type == TransactionType.BUY,
            Order.placed_at >= start,
            Order.status.notin_(_NOT_SPENT),
        )
    ).scalar_one()
    return float(total)


def buy(db: Session, strategy: Strategy, instrument: Instrument, quantity: int) -> Order:
    if quantity < 1:
        raise RealOrderRefused("Choose at least 1 share.")
    _require_switch_and_market()
    if system_state.is_entries_halted(db):
        # Owner decision 2026-10-14: the kill switch stops ALL new buying, real ones too. Sells still work.
        raise RealOrderRefused(
            "New trades are stopped (kill switch), so real buys are paused. Sells still work."
        )
    if _waiting(db, strategy.id, instrument.id):
        raise RealOrderRefused(
            f"An order for {instrument.tradingsymbol} is still waiting at Zerodha. Wait for it to finish."
        )
    price = quote(db, instrument)
    cost = price * quantity
    per_order = settings.REAL_HOLDINGS_MAX_ORDER_INR
    if cost > per_order:
        raise RealOrderRefused(f"This buy is about ₹{cost:,.0f}. The limit is ₹{per_order:,.0f} per order.")
    spent, per_day = spent_today(db, strategy.id), settings.REAL_HOLDINGS_MAX_DAY_INR
    if spent + cost > per_day:
        raise RealOrderRefused(
            f"You have already bought ₹{spent:,.0f} today. This buy (about ₹{cost:,.0f}) "
            f"would go over the ₹{per_day:,.0f} daily limit."
        )
    return execution.place_real_holding_buy(db, strategy, instrument, quantity, price)


def sell(db: Session, position: Position, quantity: int | None) -> Order:
    if position.strategy is None or position.strategy.name != REAL_TRADING_STRATEGY_NAME:
        raise RealOrderRefused("Only shares in My Holdings can be sold here.")
    if position.status != PositionStatus.OPEN:
        raise RealOrderRefused("This holding is already closed.")
    qty = position.quantity if quantity is None else int(quantity)
    if not 1 <= qty <= position.quantity:
        raise RealOrderRefused(
            f"You hold {position.quantity} shares. Choose between 1 and {position.quantity}."
        )
    _require_switch_and_market()
    if _waiting(db, position.strategy_id, position.instrument_id):
        raise RealOrderRefused("An order for this stock is still waiting at Zerodha. Wait for it to finish.")
    kite = _kite_ready(db)
    instrument = db.get(Instrument, position.instrument_id)
    try:
        owned = kite.owned_quantity(instrument.tradingsymbol, db)
    except KiteException as exc:
        raise RealOrderRefused("Could not read your Zerodha holdings, so nothing was sent.") from exc
    if owned < qty:
        raise RealOrderRefused(
            f"Zerodha shows you own {owned} {instrument.tradingsymbol} shares, fewer than the {qty} to sell. "
            "Nothing was sent. If you sold some in the Kite app, use “I sold this” to update My Holdings."
        )
    return execution.place_real_holding_sell(db, position, qty)


def status(db: Session, strategy: Strategy | None) -> dict[str, Any]:
    session = market_session.session()
    waiting: list[dict[str, Any]] = []
    spent = 0.0
    if strategy is not None:
        spent = spent_today(db, strategy.id)
        rows = db.execute(
            select(Order, Instrument.tradingsymbol)
            .join(Instrument, Instrument.id == Order.instrument_id)
            .where(Order.strategy_id == strategy.id, Order.status.in_(_WAITING))
            .order_by(Order.placed_at)
        ).all()
        waiting = [
            {
                "symbol": symbol,
                "side": str(order.transaction_type),
                "quantity": order.quantity,
                "placed_at": order.placed_at.isoformat() if order.placed_at else None,
            }
            for order, symbol in rows
        ]
    return {
        "enabled": bool(settings.ALLOW_REAL_HOLDINGS_ORDERS),
        "max_order_inr": settings.REAL_HOLDINGS_MAX_ORDER_INR,
        "max_day_inr": settings.REAL_HOLDINGS_MAX_DAY_INR,
        "spent_today_inr": spent,
        "market_open": market_session.is_open(),
        "halted": system_state.is_entries_halted(db),
        "market_text": session.plain,
        "waiting": waiting,
    }
