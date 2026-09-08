"""Positions, trades, equity curve, and performance statistics."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from swing_trade_ml.api.deps import DbSession
from swing_trade_ml.brokers import get_broker
from swing_trade_ml.core.enums import ExitReason, PositionStatus, SignalType
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.trading import Position, Signal, Strategy, Trade

IST = ZoneInfo("Asia/Kolkata")
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
from swing_trade_ml.services.execution import (
    close_position,
    manual_close_position,
    manual_open_position,
    position_action,
)

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

    # A still-open position can only have an unactioned EXIT/SELL signal
    # against it under an "advisory" strategy — an "auto" one closes the
    # position the moment such a signal fires (see process_decision), so
    # this is otherwise always empty. Batched once rather than per-position:
    # position counts here are small, but there is no reason to N+1 anyway.
    latest_pending_exit: dict[tuple[int, int], object] = {}
    if rows:
        instrument_ids = {position.instrument_id for position, _, _ in rows}
        strategy_ids = {position.strategy_id for position, _, _ in rows}
        for inst_id, strat_id, generated_at in db.execute(
            select(Signal.instrument_id, Signal.strategy_id, Signal.generated_at).where(
                Signal.mode == get_broker().mode,
                Signal.instrument_id.in_(instrument_ids),
                Signal.strategy_id.in_(strategy_ids),
                Signal.signal_type.in_([SignalType.EXIT, SignalType.SELL]),
                Signal.was_executed.is_(False),
            )
        ):
            key = (inst_id, strat_id)
            if key not in latest_pending_exit or generated_at > latest_pending_exit[key]:
                latest_pending_exit[key] = generated_at

    # "Today's move" per position — current price vs. yesterday's close, or
    # vs. entry price for anything bought today (never held "yesterday", so
    # a previous close isn't the right reference — you can't have a day
    # change on a position that didn't exist yet). One batched query rather
    # than N+1: the most recent candle strictly before today, per instrument.
    today_start_ist = datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0)
    prev_close_by_instrument: dict[int, float] = {}
    if rows:
        instrument_ids = {position.instrument_id for position, _, _ in rows}
        latest_ts_per_instrument = (
            select(Candle.instrument_id, func.max(Candle.ts).label("ts"))
            .where(
                Candle.instrument_id.in_(instrument_ids),
                Candle.interval == "day",
                Candle.ts < today_start_ist.astimezone(UTC),
            )
            .group_by(Candle.instrument_id)
            .subquery()
        )
        for inst_id, close in db.execute(
            select(Candle.instrument_id, Candle.close).join(
                latest_ts_per_instrument,
                (Candle.instrument_id == latest_ts_per_instrument.c.instrument_id)
                & (Candle.ts == latest_ts_per_instrument.c.ts),
            )
        ):
            prev_close_by_instrument[inst_id] = float(close)

    result = []
    for position, symbol, name in rows:
        current = position.current_price or position.entry_price
        invested = position.entry_price * position.quantity

        entered_today = position.entry_at.astimezone(IST) >= today_start_ist
        day_reference = (
            position.entry_price if entered_today else prev_close_by_instrument.get(position.instrument_id)
        )
        day_pnl = (current - day_reference) * position.quantity if day_reference is not None else None

        pending_at = latest_pending_exit.get((position.instrument_id, position.strategy_id))
        exit_signal_pending = pending_at is not None and pending_at >= position.entry_at
        # Falls back to ml_swing's own default when the strategy doesn't
        # override it — same lookup _check_confidence_decay() uses.
        exit_confidence = float(
            (position.strategy.params.get("exit_confidence", 0.35)) if position.strategy else 0.35
        )
        action_code, action_label = position_action(
            position.entry_confidence,
            position.last_confidence,
            alert_sent=position.confidence_alert_sent_at is not None,
            holding_days=position.holding_days,
            horizon_days=horizon_days,
            exit_confidence=exit_confidence,
            exit_signal_pending=exit_signal_pending,
        )

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
                "day_pnl": day_pnl,
                "stop_loss": position.stop_loss,
                "take_profit": position.take_profit,
                "entry_at": position.entry_at,
                "holding_days": position.holding_days,
                "strategy_id": position.strategy_id,
                "entry_confidence": position.entry_confidence,
                "last_confidence": position.last_confidence,
                "horizon_days": horizon_days,
                "action_code": action_code,
                "action_label": action_label,
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
        detail=(
            f"Exited at ₹{trade.exit_price:,.2f} — "
            f"Net P&L ₹{trade.net_pnl:,.2f} ({trade.return_pct:+.2%})"
        ),
    )


EXIT_REASON_LABELS = {
    ExitReason.TARGET_HIT: "Target reached",
    ExitReason.STOP_LOSS_HIT: "Stop-loss hit",
    ExitReason.SIGNAL_EXIT: "Model changed its mind",
    ExitReason.MANUAL: "Closed manually",
    ExitReason.RISK_LIMIT: "Risk limit",
    ExitReason.TIME_STOP: "60-day time limit",
}


# Checkpoints for "was this exit actually right?" — a handful of trading days
# (not calendar days, since candles only exist for trading days) after we sold.
# 5 ≈ "next few days", 15 ≈ "next few weeks", matching how the user framed it.
POST_EXIT_CHECKPOINTS = {"5d": 5, "15d": 15}


def _post_exit_moves(db: DbSession, trades: list[Trade]) -> dict[int, dict[str, float | None]]:
    """For each closed trade, how the stock moved after we sold it.

    Lets you tell a validated exit (price kept falling) from a premature one
    (price kept rising after we sold — profit left on the table), the same
    question raised earlier about ITC/DIVISLAB but now answerable for every
    trade without asking me to check.
    """
    if not trades:
        return {}
    instrument_ids = {t.instrument_id for t in trades}
    earliest_exit = min(t.exit_at for t in trades)

    rows = db.execute(
        select(Candle.instrument_id, Candle.ts, Candle.close)
        .where(
            Candle.interval == "day",
            Candle.instrument_id.in_(instrument_ids),
            Candle.ts > earliest_exit,
        )
        .order_by(Candle.instrument_id, Candle.ts)
    ).all()
    candles_by_instrument: dict[int, list[tuple[datetime, float]]] = {}
    for instrument_id, ts, close in rows:
        candles_by_instrument.setdefault(instrument_id, []).append((ts, close))

    moves: dict[int, dict[str, float | None]] = {}
    for trade in trades:
        future = [c for c in candles_by_instrument.get(trade.instrument_id, []) if c[0] > trade.exit_at]
        entry: dict[str, float | None] = {}
        for label, n in POST_EXIT_CHECKPOINTS.items():
            if len(future) >= n and trade.exit_price:
                price = future[n - 1][1]
                entry[f"price_{label}_after_exit"] = price
                entry[f"return_{label}_after_exit"] = (price - trade.exit_price) / trade.exit_price
            else:
                entry[f"price_{label}_after_exit"] = None
                entry[f"return_{label}_after_exit"] = None
        moves[trade.id] = entry
    return moves


@router.get("/trades", response_model=list[TradeOut])
def list_trades(
    db: DbSession,
    wins_only: bool | None = None,
    limit: int = Query(100, le=1000),
) -> list[dict[str, Any]]:
    stmt = (
        select(Trade, Position)
        .outerjoin(Position, Position.id == Trade.position_id)
        .where(Trade.mode == get_broker().mode)
        .order_by(Trade.exit_at.desc())
        .limit(limit)
    )
    if wins_only is not None:
        stmt = stmt.where(Trade.is_win.is_(wins_only))

    pairs = db.execute(stmt).all()
    post_exit = _post_exit_moves(db, [trade for trade, _ in pairs])

    result = []
    for trade, position in pairs:
        result.append(
            {
                "id": trade.id,
                "symbol": trade.symbol,
                "mode": trade.mode,
                "quantity": trade.quantity,
                "entry_price": trade.entry_price,
                "exit_price": trade.exit_price,
                "entry_at": trade.entry_at,
                "exit_at": trade.exit_at,
                "holding_days": trade.holding_days,
                "gross_pnl": trade.gross_pnl,
                "charges": trade.charges,
                "net_pnl": trade.net_pnl,
                "return_pct": trade.return_pct,
                "exit_reason": trade.exit_reason,
                "exit_reason_label": EXIT_REASON_LABELS.get(trade.exit_reason, trade.exit_reason),
                "is_win": trade.is_win,
                "stop_loss": position.stop_loss if position else None,
                "take_profit": position.take_profit if position else None,
                "entry_confidence": position.entry_confidence if position else None,
                "last_confidence": position.last_confidence if position else None,
                **post_exit.get(trade.id, {}),
            }
        )
    return result


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
