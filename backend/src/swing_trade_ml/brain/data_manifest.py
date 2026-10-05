"""Per-run data manifest (Service 1 gaps #5 / #8 lite)."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.connectors import connector_status
from swing_trade_ml.brain.context import BrainContext
from swing_trade_ml.brain.modules.m02_perception.snapshot import feature_set_version
from swing_trade_ml.db.models.market import WatchlistSnapshot
from swing_trade_ml.services.watchlist_snapshots import watchlist_as_of

IST = ZoneInfo("Asia/Kolkata")


def _universe_snapshot_date(db: Session, request: c.RunRequest) -> str | None:
    as_of_day = request.as_of.astimezone(IST).date()
    if request.live:
        row = db.execute(select(func.max(WatchlistSnapshot.snapshot_date))).scalar_one_or_none()
        return row.isoformat() if row else None
    row = db.execute(
        select(func.max(WatchlistSnapshot.snapshot_date)).where(
            WatchlistSnapshot.snapshot_date <= as_of_day
        )
    ).scalar_one_or_none()
    return row.isoformat() if row else None


def build_data_manifest(db: Session, request: c.RunRequest, ctx: BrainContext) -> dict:
    as_of_day = request.as_of.astimezone(IST).date()
    universe = tuple(ctx.request.universe)
    snap_symbols = watchlist_as_of(db, as_of_day) if not request.live else ()
    return {
        "feature_set_version": feature_set_version(),
        "universe_snapshot_date": _universe_snapshot_date(db, request),
        "universe_count": len(universe),
        "universe_snapshot_symbol_count": len(snap_symbols),
        "live": request.live,
        "as_of": as_of_day.isoformat(),
        "connectors": connector_status(db, as_of_day),
    }
