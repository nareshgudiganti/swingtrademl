"""Admin > Server health: the memory samples the API and the worker keep. Owner only, read only.

The samples come from services/server_watch.py (one every five minutes per process). Nothing here can
start, stop or change anything.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query

from swing_trade_ml.api.deps import require_owner
from swing_trade_ml.services import server_watch

router = APIRouter(
    prefix="/admin/server-health", tags=["admin-server-health"], dependencies=[Depends(require_owner)]
)


@router.get("")
def server_health(limit: int = Query(default=288, ge=1, le=server_watch.MAX_SAMPLES)) -> dict[str, Any]:
    """The last `limit` samples (newest first; 288 is one day) and, per process, how fast its memory has
    been growing since its last restart."""
    samples = server_watch.read_samples(limit)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "samples_available": bool(samples),
        "every_seconds": server_watch.SAMPLE_EVERY_SECONDS,
        "restart_above_mb": round(server_watch.RESTART_RSS_BYTES / 1024**2),
        "warn_below_available": server_watch.WARN_AVAILABLE,
        "summary": server_watch.summarize(samples),
        "samples": samples,
    }
