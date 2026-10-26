"""Shadow Test: every ranked stock followed for 15 trading days, bought or not. Owner only, read only.

Not a TradeMind consumer route: it is not listed in core/plans.py::brain_route_access, so it stays
owner-only by default. It never runs the brain and never writes; see services/shadow_test.py.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends

from swing_trade_ml.api.deps import DbSession
from swing_trade_ml.api.v1.endpoints.brain import _brain_switched_on
from swing_trade_ml.services import shadow_test

router = APIRouter(prefix="/brain", tags=["brain"], dependencies=[Depends(_brain_switched_on)])


@router.get("/shadow-test")
def get_shadow_test(db: DbSession) -> dict:
    return shadow_test.build_view(db, datetime.now(UTC))
