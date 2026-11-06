"""Weekly paper report: owner-only, read-only. See services/weekly_paper_report.py for the counting rules."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from swing_trade_ml.api.deps import DbSession, require_owner
from swing_trade_ml.services import weekly_paper_report

router = APIRouter(
    prefix="/research/weekly-report", tags=["weekly-report"], dependencies=[Depends(require_owner)]
)


@router.get("")
def weekly_report(db: DbSession) -> dict:
    return weekly_paper_report.build_report(db)
