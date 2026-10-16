"""Beginner-friendly, read-only views. GET only; nothing here writes or trades."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from swing_trade_ml.core.market_session import IST
from swing_trade_ml.db.session import get_db
from swing_trade_ml.services import beginner_views

router = APIRouter(prefix="/beginner", tags=["beginner"])


@router.get("/events")
def events(
    symbol: str | None = Query(default=None),
    scope: Literal["watchlist", "held", "all"] = "watchlist",
    db: Session = Depends(get_db),
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
