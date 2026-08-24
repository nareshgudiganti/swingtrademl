"""Signal history — the record of what the bot recommended and why."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query
from sqlalchemy import select

from swing_trade_ml.api.deps import DbSession
from swing_trade_ml.brokers import get_broker
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Signal
from swing_trade_ml.schemas import SignalOut

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("", response_model=list[SignalOut])
def list_signals(
    db: DbSession,
    signal_type: str | None = Query(None, description="BUY | SELL | HOLD | EXIT"),
    executed_only: bool = False,
    days: int = Query(30, le=365),
    limit: int = Query(100, le=1000),
) -> list[dict]:
    since = datetime.now(UTC) - timedelta(days=days)
    stmt = (
        select(Signal, Instrument.tradingsymbol, Instrument.name)
        .join(Instrument, Instrument.id == Signal.instrument_id)
        .where(Signal.mode == get_broker().mode, Signal.generated_at >= since)
        .order_by(Signal.generated_at.desc())
        .limit(limit)
    )
    if signal_type:
        stmt = stmt.where(Signal.signal_type == signal_type.upper())
    if executed_only:
        stmt = stmt.where(Signal.was_executed.is_(True))
    return [
        {
            "id": signal.id,
            "strategy_id": signal.strategy_id,
            "instrument_id": signal.instrument_id,
            "tradingsymbol": tradingsymbol,
            "name": name,
            "signal_type": signal.signal_type,
            "mode": signal.mode,
            "price": signal.price,
            "confidence": signal.confidence,
            "suggested_quantity": signal.suggested_quantity,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
            "reason": signal.reason,
            "features": signal.features,
            "was_executed": signal.was_executed,
            "rejection_reason": signal.rejection_reason,
            "advisory_only": signal.advisory_only,
            "generated_at": signal.generated_at,
        }
        for signal, tradingsymbol, name in db.execute(stmt).all()
    ]


@router.get("/latest", response_model=list[dict])
def latest_actionable(db: DbSession, limit: int = Query(20, le=100)) -> list[dict]:
    """The most recent BUY/EXIT signals, symbol-resolved for the dashboard.

    HOLD signals are excluded — there is one per instrument per scan and they
    would bury the actionable ones.
    """
    rows = db.execute(
        select(Signal, Instrument.tradingsymbol, Instrument.name)
        .join(Instrument, Instrument.id == Signal.instrument_id)
        .where(
            Signal.mode == get_broker().mode,
            Signal.signal_type.in_(["BUY", "SELL", "EXIT"]),
        )
        .order_by(Signal.generated_at.desc())
        .limit(limit)
    ).all()

    return [
        {
            "id": signal.id,
            "symbol": symbol,
            "name": name,
            "signal": signal.signal_type,
            "price": signal.price,
            "confidence": signal.confidence,
            "quantity": signal.suggested_quantity,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
            "reason": signal.reason,
            "executed": signal.was_executed,
            "advisory_only": signal.advisory_only,
            "rejection_reason": signal.rejection_reason,
            "generated_at": signal.generated_at,
        }
        for signal, symbol, name in rows
    ]
