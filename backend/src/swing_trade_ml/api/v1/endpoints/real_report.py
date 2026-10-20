"""Buy & sell report and P&L for the real Zerodha account.

Read-only: nothing here places, changes or cancels an order.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status

from swing_trade_ml.api.deps import DbSession, require_real_account
from swing_trade_ml.api.v1.endpoints.portfolio import _held_quantity, _load_kite_holdings
from swing_trade_ml.schemas import MessageResponse
from swing_trade_ml.services import fills as fills_service
from swing_trade_ml.services import tax_export
from swing_trade_ml.services.real_report import build_report

router = APIRouter(prefix="/real-report", tags=["real-report"], dependencies=[Depends(require_real_account)])

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
                "quantity": (qty := _held_quantity(h)),
                "average_price": h["average_price"],
                "last_price": h["last_price"],
                "pnl": (h["last_price"] - h["average_price"]) * qty,
            }
            for h in _load_kite_holdings(db)
        ]
    except HTTPException as exc:
        holdings, holdings_note = None, str(exc.detail)

    result = build_report(db, start, end, holdings)
    result["holdings_note"] = holdings_note
    return result


def _tax_year(db: DbSession, year: str | None) -> dict[str, Any]:
    try:
        return tax_export.build_tax_export(db, year or tax_export.current_fy())
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/tax", response_model=dict)
def tax_year(db: DbSession, year: str | None = None) -> dict[str, Any]:
    """Real sales in one financial year (e.g. 2025-26), sorted short-term / long-term. Read-only."""
    return _tax_year(db, year)


@router.get("/tax.csv")
def tax_year_csv(db: DbSession, year: str | None = None) -> Response:
    """The same, as a spreadsheet file. The BOM lets Excel show the ₹ sign."""
    export = _tax_year(db, year)
    return Response(
        content=chr(0xFEFF) + tax_export.to_csv(export),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="real-trades-tax-{export["year"]}.csv"'},
    )


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
