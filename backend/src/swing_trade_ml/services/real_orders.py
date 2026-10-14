"""The owner's own real buys and sells from My Holdings, by hand, while the bot stays on paper.

Spec: docs/superpowers/specs/2026-10-14-real-holdings-orders-design.md. Every check here runs before
anything is sent; a refusal raises RealOrderRefusedError with one plain sentence and Zerodha is never called.
Only services/execution.place_real_holding_buy/sell write the Order and send it (with the reserved tag
the narrow gate in brokers/kite.py accepts). The bot, the brain and the testing book never come here.
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.core import market_session
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import OrderStatus, PositionStatus, TransactionType
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Order, Position, Strategy
from swing_trade_ml.services import execution, system_state
from swing_trade_ml.services.portfolio import REAL_TRADING_STRATEGY_NAME

IST = ZoneInfo("Asia/Kolkata")
OFF = "Real orders are switched off."


class RealOrderRefusedError(ValueError):
    """Shown to the owner as-is. Nothing was sent to Zerodha."""


def _real_strategy(db: Session) -> Strategy:
    from swing_trade_ml.api.v1.endpoints.portfolio import _get_or_create_real_trading_strategy

    return _get_or_create_real_trading_strategy(db)


def _today_real_buys(db: Session, now: datetime) -> list[Order]:
    start = datetime.combine(now.astimezone(IST).date(), time.min, tzinfo=IST)
    real = select(Strategy.id).where(Strategy.name == REAL_TRADING_STRATEGY_NAME)
    return list(
        db.execute(
            select(Order).where(
                Order.mode == "live",
                Order.strategy_id.in_(real),
                Order.transaction_type == TransactionType.BUY,
                Order.placed_at >= start,
                Order.status.not_in([OrderStatus.REJECTED, OrderStatus.CANCELLED]),
            )
        ).scalars()
    )


def spent_today(db: Session, now: datetime | None = None) -> float:
    """Rupees of real buys today (IST), filled ones at their fill price, pending ones at the price seen
    when they were placed. Pending orders count: the limit is on what was sent, not what has settled."""
    total = 0.0
    for o in _today_real_buys(db, now or datetime.now(UTC)):
        price = o.average_price or o.price or 0.0
        qty = o.filled_quantity or o.quantity
        total += price * qty
    return round(total, 2)


def status(db: Session, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    spent = spent_today(db, now)
    enabled = settings.ALLOW_REAL_HOLDINGS_ORDERS
    open_now = market_session.is_open(now)
    halted = system_state.is_entries_halted(db)
    if not enabled:
        plain = OFF
    elif not open_now:
        plain = f"Market is closed. {market_session.session(now).plain}"
    elif halted:
        plain = "New trades are stopped (kill switch): real buys are paused; sells still work."
    else:
        plain = "Real orders are on."
    return {
        "enabled": enabled,
        "market_open": open_now,
        "halted": halted,
        "max_order_inr": settings.REAL_HOLDINGS_MAX_ORDER_INR,
        "max_day_inr": settings.REAL_HOLDINGS_MAX_DAY_INR,
        "spent_today_inr": spent,
        "left_today_inr": max(round(settings.REAL_HOLDINGS_MAX_DAY_INR - spent, 2), 0.0),
        "plain": plain,
    }


def _common_checks(db: Session, instrument: Instrument, now: datetime) -> None:
    if not settings.ALLOW_REAL_HOLDINGS_ORDERS:
        raise RealOrderRefusedError(OFF)
    if not market_session.is_open(now):
        raise RealOrderRefusedError(f"Market is closed. {market_session.session(now).plain}")
    real = select(Strategy.id).where(Strategy.name == REAL_TRADING_STRATEGY_NAME)
    waiting = db.execute(
        select(Order.id).where(
            Order.mode == "live",
            Order.strategy_id.in_(real),
            Order.instrument_id == instrument.id,
            Order.status.in_([OrderStatus.PENDING, OrderStatus.OPEN]),
        )
    ).first()
    if waiting is not None:
        raise RealOrderRefusedError(
            f"A real order for {instrument.tradingsymbol} is still waiting at Zerodha. "
            "Wait for it to finish before placing another."
        )


def buy(
    db: Session, symbol: str, exchange: str, quantity: int, by: str, now: datetime | None = None
) -> Order:
    from swing_trade_ml.brokers.kite import KiteAuthError, kite_broker

    now = now or datetime.now(UTC)
    if not settings.ALLOW_REAL_HOLDINGS_ORDERS:
        raise RealOrderRefusedError(OFF)
    if quantity < 1:
        raise RealOrderRefusedError("Buy at least 1 share.")
    instrument = db.execute(
        select(Instrument).where(
            Instrument.tradingsymbol == symbol.strip().upper(), Instrument.exchange == exchange
        )
    ).scalar_one_or_none()
    if instrument is None:
        raise RealOrderRefusedError(f"{symbol} on {exchange} is not a stock this app knows.")
    _common_checks(db, instrument, now)
    if system_state.is_entries_halted(db):
        raise RealOrderRefusedError(
            "New trades are stopped (kill switch), so real buys are paused. Sells still work."
        )

    try:
        price = kite_broker.get_ltp([instrument.symbol_key], db).get(instrument.symbol_key)
    except KiteAuthError as exc:
        raise RealOrderRefusedError("Zerodha is not connected, so no real order can be placed.") from exc
    if not price or price <= 0:
        raise RealOrderRefusedError(
            f"Zerodha gave no live price for {instrument.tradingsymbol}; nothing was sent."
        )

    value = price * quantity
    if value > settings.REAL_HOLDINGS_MAX_ORDER_INR:
        raise RealOrderRefusedError(
            f"{quantity} shares at ₹{price:,.2f} = ₹{value:,.0f}, above the "
            f"₹{settings.REAL_HOLDINGS_MAX_ORDER_INR:,.0f} limit for one real buy."
        )
    spent = spent_today(db, now)
    if spent + value > settings.REAL_HOLDINGS_MAX_DAY_INR:
        raise RealOrderRefusedError(
            f"Real buys today would reach ₹{spent + value:,.0f} (₹{spent:,.0f} already), above the "
            f"₹{settings.REAL_HOLDINGS_MAX_DAY_INR:,.0f} daily limit."
        )
    return execution.place_real_holding_buy(db, _real_strategy(db), instrument, quantity, price, by)


def sell(db: Session, position_id: int, quantity: int | None, by: str, now: datetime | None = None) -> Order:
    from swing_trade_ml.brokers.kite import KiteAuthError, kite_broker

    now = now or datetime.now(UTC)
    if not settings.ALLOW_REAL_HOLDINGS_ORDERS:
        raise RealOrderRefusedError(OFF)
    position = db.get(Position, position_id)
    strategy = db.get(Strategy, position.strategy_id) if position and position.strategy_id else None
    if (
        position is None
        or strategy is None
        or strategy.name != REAL_TRADING_STRATEGY_NAME
        or position.mode != "live"
        or position.status != PositionStatus.OPEN
    ):
        raise RealOrderRefusedError("That is not an open holding in My Holdings.")
    instrument = db.get(Instrument, position.instrument_id)
    _common_checks(db, instrument, now)
    if position.exit_in_progress_at is not None:
        raise RealOrderRefusedError(f"A sell of {instrument.tradingsymbol} is already waiting.")

    qty = position.quantity if quantity is None else quantity
    if not 1 <= qty <= position.quantity:
        raise RealOrderRefusedError(f"Sell between 1 and {position.quantity} shares.")
    try:
        owned = kite_broker.owned_quantity(instrument.tradingsymbol, db)
    except KiteAuthError as exc:
        raise RealOrderRefusedError("Zerodha is not connected, so no real order can be placed.") from exc
    if owned < qty:
        raise RealOrderRefusedError(
            f"Zerodha shows you own {owned} {instrument.tradingsymbol} shares, fewer than the {qty} to sell. "
            "Nothing was sent. If you sold some in the Kite app, use “I sold this” to update My Holdings."
        )
    return execution.place_real_holding_sell(db, position, instrument, qty, by)
