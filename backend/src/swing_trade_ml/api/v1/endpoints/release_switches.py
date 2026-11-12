"""Owner-only, read-only view of the release switches."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from swing_trade_ml.api.deps import require_owner
from swing_trade_ml.core.release_switches import switch_states

admin = APIRouter(prefix="/admin", tags=["release-switches"], dependencies=[Depends(require_owner)])


@admin.get("/release-switches")
def release_switches() -> dict:
    return {"switches": switch_states()}
