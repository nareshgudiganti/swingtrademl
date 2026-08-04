"""Order placement and history.

Manual placement goes through the same broker abstraction as the automated
path, so a hand-placed order in paper mode is simulated and charged identically.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from swing_trade_ml.api.deps import DbSession
from swing_trade_ml.brokers import OrderRequest, get_broker
from swing_trade_ml.core.enums import OrderStatus, OrderType, ProductType, TransactionType
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Order
from swing_trade_ml.schemas import MessageResponse, OrderCreate, OrderOut

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("", response_model=list[OrderOut])
def list_orders(
    db: DbSession,
    order_status: str | None = Query(None, alias="status"),
    limit: int = Query(100, le=1000),
) -> list[Order]:
    stmt = (
        select(Order)
        .where(Order.mode == get_broker().mode)
        .order_by(Order.placed_at.desc())
        .limit(limit)
    )
    if order_status:
        stmt = stmt.where(Order.status == order_status.upper())
    return list(db.execute(stmt).scalars().all())


@router.post("", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def place_order(payload: OrderCreate, db: DbSession) -> Order:
    """Place a manual order in the current trading mode."""
    instrument = db.execute(
        select(Instrument).where(
            Instrument.tradingsymbol == payload.symbol.upper(),
            Instrument.exchange == payload.exchange,
        )
    ).scalar_one_or_none()
    if instrument is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Unknown instrument {payload.symbol.upper()}"
        )

    broker = get_broker()
    now = datetime.now(UTC)

    order = Order(
        instrument_id=instrument.id,
        mode=broker.mode,
        transaction_type=payload.transaction_type,
        order_type=payload.order_type,
        product=payload.product,
        quantity=payload.quantity,
        price=payload.price,
        trigger_price=payload.trigger_price,
        status=OrderStatus.PENDING,
        placed_at=now,
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    result = broker.place_order(
        OrderRequest(
            tradingsymbol=instrument.tradingsymbol,
            exchange=instrument.exchange,
            transaction_type=TransactionType(payload.transaction_type),
            quantity=payload.quantity,
            order_type=OrderType(payload.order_type),
            product=ProductType(payload.product),
            price=payload.price,
            trigger_price=payload.trigger_price,
            tag="manual",
        ),
        db,
    )

    order.broker_order_id = result.broker_order_id
    order.status = result.status
    order.filled_quantity = result.filled_quantity
    order.average_price = result.average_price
    order.brokerage = result.brokerage
    order.taxes = result.taxes
    order.slippage = result.slippage
    order.status_message = result.message
    if result.status == OrderStatus.COMPLETE:
        order.filled_at = now
    db.commit()
    db.refresh(order)

    # A rejection is a valid outcome that the caller must see, not a 500 — the
    # order row is persisted either way.
    return order


@router.get("/{order_id}", response_model=OrderOut)
def get_order(order_id: int, db: DbSession) -> Order:
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    return order


@router.post("/{order_id}/cancel", response_model=MessageResponse)
def cancel_order(order_id: int, db: DbSession) -> MessageResponse:
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    if not order.broker_order_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Order was never submitted")

    cancelled = get_broker().cancel_order(order.broker_order_id, db)
    if not cancelled:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Could not cancel — order is {order.status}",
        )
    order.status = OrderStatus.CANCELLED
    db.commit()
    return MessageResponse(message=f"Cancelled order {order.broker_order_id}")


@router.post("/sync", response_model=MessageResponse)
def sync_order_status(db: DbSession) -> MessageResponse:
    """Reconcile non-terminal orders against the broker.

    Live orders fill asynchronously, so the local status can lag. Paper orders
    are already terminal on placement and this is effectively a no-op for them.
    """
    broker = get_broker()
    pending = list(
        db.execute(
            select(Order).where(
                Order.mode == broker.mode,
                Order.status.in_([OrderStatus.PENDING, OrderStatus.OPEN]),
                Order.broker_order_id.isnot(None),
            )
        )
        .scalars()
        .all()
    )

    updated = 0
    for order in pending:
        result = broker.get_order_status(order.broker_order_id, db)
        if result is None or result.status == order.status:
            continue
        order.status = result.status
        order.filled_quantity = result.filled_quantity
        order.average_price = result.average_price
        order.status_message = result.message
        if result.status == OrderStatus.COMPLETE and order.filled_at is None:
            order.filled_at = datetime.now(UTC)
        updated += 1

    db.commit()
    return MessageResponse(message=f"Synced {updated} of {len(pending)} pending orders")
