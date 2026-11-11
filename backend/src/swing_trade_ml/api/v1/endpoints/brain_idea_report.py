"""Portfolio page > Reports: brain ideas by word, score, horizon and market mood, with days done / left.

Owner only and read-only (its own READ ONLY transaction). It places no orders and writes nothing. The trial
seal applies: see services/idea_report.py.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from swing_trade_ml.api.deps import require_owner
from swing_trade_ml.core.config import settings
from swing_trade_ml.services import idea_report
from swing_trade_ml.services.brain_observatory.db import get_readonly_db

IST = ZoneInfo("Asia/Kolkata")


def _brain_on() -> None:
    if not settings.BRAIN_ENABLED:
        raise HTTPException(404, "Not Found")


ReadOnlyDb = Annotated[Session, Depends(get_readonly_db)]
router = APIRouter(
    prefix="/brain/idea-report",
    tags=["brain-idea-report"],
    dependencies=[Depends(_brain_on), Depends(require_owner)],
)


@router.get("")
def idea_report_route(
    db: ReadOnlyDb,
    start: date | None = Query(None, alias="from"),
    end: date | None = Query(None, alias="to"),
    word: Annotated[list[str] | None, Query()] = None,
    band: Annotated[list[str] | None, Query()] = None,
    horizon: Annotated[list[int] | None, Query()] = None,
    regime: Annotated[list[str] | None, Query()] = None,
    outcome: Annotated[list[str] | None, Query()] = None,
    current_only: bool = False,
) -> dict:
    today = datetime.now(IST).date()
    end = end or today
    start = start or end - timedelta(days=59)
    if end < start:
        raise HTTPException(422, "'to' must be on or after 'from'.")
    if (end - start).days + 1 > idea_report.MAX_DAYS:
        raise HTTPException(422, f"Ask for at most {idea_report.MAX_DAYS} days at a time.")
    words = [w.upper() for w in word or []]
    if bad := [w for w in words if w not in idea_report.WORDS]:
        raise HTTPException(422, f"Unknown word(s): {', '.join(bad)}.")
    if bad := [b for b in band or [] if b not in {x for x, _, _ in idea_report.SCORE_BANDS}]:
        raise HTTPException(422, f"Unknown score band(s): {', '.join(bad)}.")
    if bad := [o for o in outcome or [] if o not in idea_report.OUTCOMES]:
        raise HTTPException(422, f"Unknown outcome(s): {', '.join(bad)}.")
    return idea_report.build(
        db,
        start,
        end,
        settings.TRADING_MODE,
        words=words,
        bands=band or [],
        horizons=horizon or [],
        regimes=regime or [],
        outcomes=outcome or [],
        current_only=current_only,
    )
