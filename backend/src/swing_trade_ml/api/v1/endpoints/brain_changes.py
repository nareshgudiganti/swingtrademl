"""What changed since yesterday (ux11): read only, for the TradeMind idea screens.

Compares today's live nightly brain ideas with the previous trading day's. It never runs the
brain and never writes; see services/brain_changes.py. Gated like the other TradeMind brain
reads (core/plans.py::brain_route_access), and hidden while the brain is switched off.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from swing_trade_ml.api.deps import DbSession, Principal, get_principal
from swing_trade_ml.api.v1.endpoints.brain import _brain_switched_on
from swing_trade_ml.services import brain_changes

router = APIRouter(prefix="/brain", tags=["brain"], dependencies=[Depends(_brain_switched_on)])


@router.get("/changes")
def changes(
    db: DbSession,
    principal: Annotated[Principal, Depends(get_principal)],
    run_id: str | None = Query(None, max_length=40),
    book: str = Query("paper", pattern="^(paper|live)$"),
) -> dict:
    return brain_changes.changes(db, run_id=run_id, book=book, owner=principal.is_owner)
