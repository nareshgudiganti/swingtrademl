"""M18: the brain beside version 1, the owner's trading stage, and approvals.

Separate from endpoints/brain.py on purpose: nothing on that router can place
an order, while the approvals here can (only through v1 execution, after the
owner's OK). Same gate: hidden while BRAIN_ENABLED is false."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query

from swing_trade_ml.api.deps import DbSession
from swing_trade_ml.api.v1.endpoints.brain import _brain_switched_on
from swing_trade_ml.services.brain_golive import compare

router = APIRouter(prefix="/brain", tags=["brain"], dependencies=[Depends(_brain_switched_on)])


@router.get("/compare")
def compare_report(db: DbSession, since: date | None = Query(None)) -> dict:
    return compare.report(db, since)
