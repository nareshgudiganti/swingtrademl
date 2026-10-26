"""Company and news: what a company has filed, for the stock page's second tab. Read-only."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter

from swing_trade_ml.api.deps import DbSession
from swing_trade_ml.services import company_filings

IST = ZoneInfo("Asia/Kolkata")

router = APIRouter(prefix="/company", tags=["company"])


@router.get("/{symbol}")
def get_company(symbol: str, db: DbSession) -> dict:
    """Every block with its source, its "as of" date and a state: ok, out_of_date or not_available.
    Display only: it changes no pick, order, stop, size or limit."""
    return company_filings.build_view(db, symbol, datetime.now(IST).date())
