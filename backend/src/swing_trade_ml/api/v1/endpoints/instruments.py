"""Instrument master and watchlist management."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from sqlalchemy import select

from swing_trade_ml.api.deps import DbSession
from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.session import session_scope
from swing_trade_ml.schemas import InstrumentOut, MessageResponse, WatchlistRequest
from swing_trade_ml.services import ingestion

router = APIRouter(prefix="/instruments", tags=["instruments"])


@router.get("", response_model=list[InstrumentOut])
def list_instruments(
    db: DbSession,
    search: str | None = Query(None, description="Substring match on symbol or name"),
    watchlisted_only: bool = False,
    exchange: str = "NSE",
    limit: int = Query(100, le=1000),
) -> list[Instrument]:
    stmt = select(Instrument).where(Instrument.exchange == exchange, Instrument.is_active.is_(True))
    if watchlisted_only:
        stmt = stmt.where(Instrument.is_watchlisted.is_(True))
    if search:
        pattern = f"%{search.upper()}%"
        stmt = stmt.where(
            Instrument.tradingsymbol.ilike(pattern) | Instrument.name.ilike(pattern)
        )
    return list(db.execute(stmt.order_by(Instrument.tradingsymbol).limit(limit)).scalars().all())


@router.post("/sync", response_model=MessageResponse, status_code=status.HTTP_202_ACCEPTED)
def sync_instruments(background: BackgroundTasks) -> MessageResponse:
    """Refresh the instrument master from Kite.

    Runs in the background — the NSE dump is a few thousand rows and would
    otherwise hold the request open.
    """

    def _run() -> None:
        with session_scope() as db:
            ingestion.sync_instruments(db)

    background.add_task(_run)
    return MessageResponse(
        message="Instrument sync started",
        detail="Check GET /instruments in a few seconds",
    )


@router.get("/watchlist", response_model=list[InstrumentOut])
def get_watchlist(db: DbSession) -> list[Instrument]:
    return list(
        db.execute(
            select(Instrument)
            .where(Instrument.is_watchlisted.is_(True))
            .order_by(Instrument.tradingsymbol)
        )
        .scalars()
        .all()
    )


@router.put("/watchlist", response_model=list[InstrumentOut])
def set_watchlist(payload: WatchlistRequest, db: DbSession) -> list[Instrument]:
    """Replace the watchlist with exactly these symbols."""
    matched = ingestion.set_watchlist(db, payload.symbols, payload.exchange)
    if not matched:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "No symbols matched. Run POST /instruments/sync first, then check spelling.",
        )
    return list(
        db.execute(
            select(Instrument)
            .where(Instrument.is_watchlisted.is_(True))
            .order_by(Instrument.tradingsymbol)
        )
        .scalars()
        .all()
    )


@router.post("/watchlist/reset", response_model=MessageResponse)
def reset_watchlist(db: DbSession) -> MessageResponse:
    """Restore the watchlist to DEFAULT_WATCHLIST from .env."""
    matched = ingestion.set_watchlist(db, settings.watchlist)
    return MessageResponse(
        message=f"Watchlist reset to {len(matched)} symbols",
        detail=", ".join(matched),
    )
