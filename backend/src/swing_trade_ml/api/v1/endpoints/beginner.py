"""Beginner-friendly, read-only views. GET only; nothing here writes or trades."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from swing_trade_ml.core.market_session import IST
from swing_trade_ml.services import beginner_views
from swing_trade_ml.services.brain_observatory.db import get_readonly_db

ReadOnlyDb = Annotated[Session, Depends(get_readonly_db)]

router = APIRouter(prefix="/beginner", tags=["beginner"])


@router.get("/events")
def events(
    db: ReadOnlyDb,
    symbol: str | None = Query(default=None),
    scope: Literal["watchlist", "held", "all"] = "watchlist",
) -> list[dict]:
    """Results and corporate actions coming up in the next 15 trading days."""
    if symbol:
        symbols: list[str] | None = [symbol.upper()]
    elif scope == "held":
        symbols = beginner_views.held_symbols(db)
    elif scope == "watchlist":
        symbols = beginner_views.watchlist_symbols(db)
    else:
        symbols = None
    return beginner_views.upcoming_events(db, symbols, datetime.now(IST).date())


@router.get("/evidence")
def evidence(db: ReadOnlyDb) -> dict:
    """How the practice-money bot is doing, in plain figures. Brain trial shows a count only."""
    return beginner_views.evidence_summary(db)


@router.get("/stock/{symbol}")
def stock(symbol: str, db: ReadOnlyDb) -> dict:
    """Six plain questions about one stock, from stored data only (the brain is never run)."""
    try:
        return beginner_views.stock_brief(db, symbol, datetime.now(IST).date())
    except LookupError:
        raise HTTPException(404, "Not a stock we follow") from None
