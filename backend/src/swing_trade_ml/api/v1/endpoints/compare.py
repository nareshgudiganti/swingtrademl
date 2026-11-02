"""Stock Compare: price change over 1 week to 5 years for up to three stocks. Read-only."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from swing_trade_ml.api.deps import DbSession
from swing_trade_ml.services import stock_compare

router = APIRouter(prefix="/compare", tags=["compare"])


@router.get("")
def compare_stocks(
    db: DbSession, symbols: str = Query(..., description="Up to three symbols, comma separated")
) -> dict:
    """Each stock with a state (ok, no_history or unknown) and its percent change per period.
    Display only: it changes no pick, order, stop, size or limit."""
    wanted = stock_compare.parse_symbols(symbols)
    if not wanted:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Give at least one stock symbol.")
    if len(wanted) > stock_compare.MAX_STOCKS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Compare up to {stock_compare.MAX_STOCKS} stocks at a time."
        )
    return stock_compare.build_compare(db, wanted)
