"""Positions, trades, equity curve, and performance statistics."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from swing_trade_ml.api.deps import DbSession
from swing_trade_ml.brokers import get_broker
from swing_trade_ml.core.enums import ExitReason, PositionStatus
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Position, Signal, Strategy, Trade
from swing_trade_ml.ml.registry import get_active_model
from swing_trade_ml.schemas import (
    ClosePositionRequest,
    EquityPoint,
    ManualEntryRequest,
    ManualExitRequest,
    MessageResponse,
    PositionOut,
    TradeOut,
)
from swing_trade_ml.services import portfolio as portfolio_service
from swing_trade_ml.services.execution import close_position, manual_close_position, manual_open_position

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("/summary", response_model=dict)
def summary(db: DbSession, mode: str | None = None) -> dict[str, Any]:
    """Headline performance figures — the dashboard's main panel.

    Pass `mode=paper` explicitly to review the paper track record after
    switching to live.
    """
    return portfolio_service.performance_stats(db, mode)


@router.get("/positions", response_model=list[PositionOut])
def list_positions(
    db: DbSession,
    open_only: bool = True,
    limit: int = Query(100, le=1000),
) -> list[Position]:
    stmt = (
        select(Position)
        .where(Position.mode == get_broker().mode)
        .order_by(Position.entry_at.desc())
        .limit(limit)
    )
    if open_only:
        stmt = stmt.where(Position.status == PositionStatus.OPEN)
    return list(db.execute(stmt).scalars().all())


@router.get("/positions/detailed", response_model=list[dict])
def detailed_positions(db: DbSession) -> list[dict[str, Any]]:
    """Open positions with symbols and computed P&L, ready to render."""
    rows = db.execute(
        select(Position, Instrument.tradingsymbol, Instrument.name)
        .join(Instrument, Instrument.id == Position.instrument_id)
        .where(Position.mode == get_broker().mode, Position.status == PositionStatus.OPEN)
        .order_by(Position.entry_at.desc())
    ).all()

    # The active model's own horizon — the "X days" a BUY signal was actually
    # judged against. Positions opened under an earlier model version are
    # shown against the CURRENT model's horizon as the best available
    # context, not a stored-forever value from whichever version bought it.
    active_model = get_active_model(db)
    horizon_days = active_model.prediction_horizon_days if active_model else None

    result = []
    for position, symbol, name in rows:
        current = position.current_price or position.entry_price
        invested = position.entry_price * position.quantity
        result.append(
            {
                "id": position.id,
                "symbol": symbol,
                "name": name,
                "quantity": position.quantity,
                "entry_price": position.entry_price,
                "current_price": current,
                "invested": invested,
                "current_value": current * position.quantity,
                "unrealized_pnl": position.unrealized_pnl,
                "unrealized_pnl_pct": (current / position.entry_price - 1) if position.entry_price else 0.0,
                "stop_loss": position.stop_loss,
                "take_profit": position.take_profit,
                "entry_at": position.entry_at,
                "holding_days": position.holding_days,
                "strategy_id": position.strategy_id,
                "entry_confidence": position.entry_confidence,
                "last_confidence": position.last_confidence,
                "horizon_days": horizon_days,
            }
        )
    return result


@router.post("/positions/manual", response_model=PositionOut, status_code=status.HTTP_201_CREATED)
def create_manual_position(payload: ManualEntryRequest, db: DbSession) -> Position:
    """Record a position filled outside the app — the counterpart to
    advisory-mode recommendations, which never place a real order."""
    strategy = db.get(Strategy, payload.strategy_id)
    if strategy is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Strategy not found")
    instrument = db.get(Instrument, payload.instrument_id)
    if instrument is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Instrument not found")

    signal = None
    if payload.signal_id is not None:
        signal = db.get(Signal, payload.signal_id)
        if signal is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Signal not found")

    return manual_open_position(
        db,
        strategy,
        instrument,
        payload.quantity,
        payload.entry_price,
        payload.stop_loss,
        payload.take_profit,
        payload.brokerage,
        payload.taxes,
        signal,
    )


@router.post("/positions/{position_id}/manual-close", response_model=TradeOut)
def close_manual_position(position_id: int, payload: ManualExitRequest, db: DbSession) -> Trade:
    """Record the exit fill for a position closed outside the app."""
    position = db.get(Position, position_id)
    if position is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Position not found")
    if position.status != PositionStatus.OPEN:
        raise HTTPException(status.HTTP_409_CONFLICT, "Position is already closed")

    try:
        reason = ExitReason(payload.exit_reason)
    except ValueError:
        reason = ExitReason.MANUAL

    return manual_close_position(
        db, position, payload.exit_price, reason, payload.brokerage, payload.taxes
    )


@router.post("/positions/{position_id}/close", response_model=MessageResponse)
def close(position_id: int, payload: ClosePositionRequest, db: DbSession) -> MessageResponse:
    """Manually exit a position at the current market price."""
    position = db.get(Position, position_id)
    if position is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Position not found")
    if position.status != PositionStatus.OPEN:
        raise HTTPException(status.HTTP_409_CONFLICT, "Position is already closed")

    try:
        reason = ExitReason(payload.reason)
    except ValueError:
        reason = ExitReason.MANUAL

    trade = close_position(db, position, None, reason, payload.note)
    if trade is None:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Exit order did not fill — check order history"
        )
    return MessageResponse(
        message=f"Closed position {position_id}",
        detail=f"Net P&L ₹{trade.net_pnl:,.2f} ({trade.return_pct:+.2%})",
    )


@router.get("/trades", response_model=list[TradeOut])
def list_trades(
    db: DbSession,
    wins_only: bool | None = None,
    limit: int = Query(100, le=1000),
) -> list[Trade]:
    stmt = (
        select(Trade)
        .where(Trade.mode == get_broker().mode)
        .order_by(Trade.exit_at.desc())
        .limit(limit)
    )
    if wins_only is not None:
        stmt = stmt.where(Trade.is_win.is_(wins_only))
    return list(db.execute(stmt).scalars().all())


@router.get("/equity-curve", response_model=list[EquityPoint])
def equity_curve(
    db: DbSession, days: int = Query(180, le=1825), mode: str | None = None
) -> list[dict[str, Any]]:
    return portfolio_service.equity_curve(db, mode, days)


@router.post("/snapshot", response_model=MessageResponse)
def snapshot(db: DbSession) -> MessageResponse:
    """Mark to market and record an equity-curve point immediately."""
    portfolio_service.mark_to_market(db)
    snap = portfolio_service.take_snapshot(db)
    return MessageResponse(
        message="Snapshot recorded",
        detail=f"Total value ₹{snap.total_value:,.2f}, drawdown {snap.drawdown_pct:.2%}",
    )
