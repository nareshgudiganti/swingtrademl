"""Signal history — the record of what the bot recommended and why."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.orm import aliased

from swing_trade_ml.api.deps import DbSession
from swing_trade_ml.brokers import get_broker
from swing_trade_ml.core.enums import PositionStatus
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Position, Signal, Strategy
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
def latest_actionable(
    db: DbSession,
    limit: int = Query(20, le=100),
    symbol: str | None = Query(
        None, description="Look up one symbol's full score history instead of the cross-strategy feed"
    ),
) -> list[dict]:
    """The most recent BUY/EXIT signals, symbol-resolved for the dashboard.

    HOLD signals are excluded by default — there is one per instrument per
    scan and they would bury the actionable ones. But when `symbol` narrows
    this to one stock, HOLD *is* the useful history (most days for most
    stocks are HOLD, not BUY/EXIT) — so it's included, and the limit ceiling
    opens up, for a "search this stock, see every score, newest first" view.
    """
    stmt = (
        select(Signal, Instrument.tradingsymbol, Instrument.name)
        .join(Instrument, Instrument.id == Signal.instrument_id)
        .where(Signal.mode == get_broker().mode)
        .order_by(Signal.generated_at.desc())
    )
    if symbol:
        stmt = stmt.where(Instrument.tradingsymbol == symbol.strip().upper())
        limit = max(limit, 200)
    else:
        stmt = stmt.where(Signal.signal_type.in_(["BUY", "SELL", "EXIT"]))
    rows = db.execute(stmt.limit(limit)).all()

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


@router.get("/buy-list", response_model=list[dict])
def buy_list(db: DbSession) -> list[dict]:
    """Every symbol that is a fresh, still-current BUY right now — nothing else.

    Answers "the Signals page shows a BUY row for this stock, but is that
    still true today or from three days ago?" by construction: it's deduped
    to each instrument's single most recent signal (any strategy), then kept
    only if that latest signal is BUY. A stock that reconfirms BUY every day
    for a week stays on the list the whole week; the moment a later scan
    reads HOLD or weaker, it silently drops off next call — no manual
    dismissal needed for that case, since a stale row is structurally
    impossible here. Already-held symbols are excluded — this list is only
    for fresh entries, not stocks already bought (that's the Portfolio page).
    """
    latest_signal = (
        select(Signal)
        .where(Signal.mode == get_broker().mode)
        .distinct(Signal.strategy_id, Signal.instrument_id)
        .order_by(Signal.strategy_id, Signal.instrument_id, Signal.generated_at.desc())
    ).subquery()
    LatestSignal = aliased(Signal, latest_signal)

    held_instrument_ids = select(Position.instrument_id).where(
        Position.mode == get_broker().mode, Position.status == PositionStatus.OPEN
    )

    stmt = (
        select(LatestSignal, Instrument.tradingsymbol, Instrument.name, Strategy.name)
        .join(Instrument, Instrument.id == LatestSignal.instrument_id)
        .join(Strategy, Strategy.id == LatestSignal.strategy_id)
        .where(
            LatestSignal.signal_type == "BUY",
            LatestSignal.instrument_id.not_in(held_instrument_ids),
        )
        .order_by(LatestSignal.confidence.desc().nullslast())
    )
    rows = db.execute(stmt).all()

    return [
        {
            "symbol": symbol,
            "name": name,
            "strategy_name": strategy_name,
            "price": sig.price,
            "confidence": sig.confidence,
            "stop_loss": sig.stop_loss,
            "take_profit": sig.take_profit,
            "reason": sig.reason,
            "generated_at": sig.generated_at,
        }
        for sig, symbol, name, strategy_name in rows
    ]
