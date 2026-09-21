"""Buy & sell report and P&L for the real Zerodha account.

Read-only: nothing here places, changes or cancels an order.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from swing_trade_ml.api.deps import DbSession
from swing_trade_ml.api.v1.endpoints.portfolio import _load_kite_holdings
from swing_trade_ml.schemas import MessageResponse
from swing_trade_ml.services import fills as fills_service
from swing_trade_ml.services.real_report import build_report

router = APIRouter(prefix="/real-report", tags=["real-report"])

MAX_TRADEBOOK_BYTES = 5 * 1024 * 1024


@router.get("", response_model=dict)
def report(db: DbSession, start: date | None = None, end: date | None = None) -> dict[str, Any]:
    if start and end and start > end:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The start date is after the end date.")

    # Open holdings need a live Zerodha session, but the history does not — so
    # a logged-out session degrades the report instead of failing it.
    holdings: list[dict[str, Any]] | None
    holdings_note: str | None = None
    try:
        holdings = [
            {
                "symbol": h["tradingsymbol"],
                "quantity": h["quantity"],
                "average_price": h["average_price"],
                "last_price": h["last_price"],
                "pnl": h["pnl"],
            }
            for h in _load_kite_holdings(db)
        ]
    except HTTPException as exc:
        holdings, holdings_note = None, str(exc.detail)

    result = build_report(db, start, end, holdings)
    result["holdings_note"] = holdings_note
    return result


@router.post("/sync", response_model=MessageResponse)
def sync_today(db: DbSession) -> MessageResponse:
    """Pull today's trades from Zerodha now, instead of waiting for the daily job."""
    from swing_trade_ml.brokers.kite import kite_broker

    kite_broker.load_session(db)
    if not kite_broker.is_authenticated:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Log into Zerodha first — fetching trades needs a live session."
        )
    result = fills_service.capture_todays_fills(db)
    return MessageResponse(
        message=f"Added {result.added} new trade{'s' if result.added != 1 else ''} from today.",
        detail=f"{result.already_stored} already saved.",
    )


@router.post("/import-tradebook", response_model=MessageResponse)
async def import_tradebook(db: DbSession, file: UploadFile = File(...)) -> MessageResponse:
    """Load Zerodha's own tradebook file, so the report reaches back before
    this app began saving trades."""
    content = await file.read(MAX_TRADEBOOK_BYTES + 1)
    if len(content) > MAX_TRADEBOOK_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "That file is too large.")
    try:
        result = fills_service.import_tradebook_csv(db, content)
    except fills_service.TradebookError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return MessageResponse(
        message=f"Added {result.added} trade{'s' if result.added != 1 else ''} from your file.",
        detail=(
            f"{result.already_stored} were already saved; "
            f"{result.skipped} rows were not share trades and were ignored."
        ),
    )
