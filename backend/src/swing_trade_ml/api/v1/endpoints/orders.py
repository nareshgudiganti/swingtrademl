"""Order history, cancel and broker sync.

There is deliberately NO endpoint that places an order here (Codex audit finding 2): the old
`POST /orders` skipped the entry risk checks, the kill switch, sizing and stop-loss. Every order is
placed by the scan / Brain approval path (`services/execution.py`) or, for the owner's real account,
by the separate My Holdings endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from swing_trade_ml.api.deps import DbSession
from swing_trade_ml.brokers import get_broker
from swing_trade_ml.core.enums import OrderStatus
from swing_trade_ml.db.models.trading import Order
from swing_trade_ml.schemas import MessageResponse, OrderOut

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

    Live orders fill asynchronously, so the local status can lag — and until
    this runs, a newly-COMPLETE entry/exit order has no Position/Trade yet
    either (see execution.reconcile_pending_orders). Paper orders are already
    terminal on placement, so this is effectively a no-op for them. Also runs
    automatically every tick during market hours (job_reconcile_orders) —
    this endpoint exists for an on-demand check in between.
    """
    from swing_trade_ml.services.execution import reconcile_pending_orders

    counts = reconcile_pending_orders(db)
    return MessageResponse(
        message=f"Checked {counts['checked']} pending order(s)",
        detail=f"{counts['filled']} filled, {counts['failed']} failed, {counts['unchanged']} unchanged",
    )
