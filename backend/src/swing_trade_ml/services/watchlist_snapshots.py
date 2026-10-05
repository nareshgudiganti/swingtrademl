"""Daily watchlist snapshots for point-in-time brain universe (Service 1 #4)."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.market import Instrument, WatchlistSnapshot

log = get_logger(__name__)
IST = ZoneInfo("Asia/Kolkata")


def snapshot_date_ist(when: datetime | None = None) -> date:
    when = when or datetime.now(IST)
    if when.tzinfo is None:
        when = when.replace(tzinfo=IST)
    return when.astimezone(IST).date()


def record_watchlist_snapshot(db: Session, on: date | None = None) -> int:
    """Replace the snapshot for `on` (default: today IST) with current watchlist flags."""
    day = on or snapshot_date_ist()
    symbols = sorted(
        db.execute(
            select(Instrument.tradingsymbol).where(
                Instrument.is_watchlisted.is_(True),
                Instrument.is_active.is_(True),
            )
        ).scalars()
    )
    db.execute(delete(WatchlistSnapshot).where(WatchlistSnapshot.snapshot_date == day))
    if symbols:
        db.execute(
            pg_insert(WatchlistSnapshot).values([{"snapshot_date": day, "symbol": s} for s in symbols])
        )
    db.commit()
    log.info("watchlist.snapshot.recorded", date=day.isoformat(), count=len(symbols))
    return len(symbols)


def watchlist_as_of(db: Session, as_of: date) -> tuple[str, ...]:
    """Watchlist symbols on or before `as_of` (IST trading day).

    Uses the latest snapshot with ``snapshot_date <= as_of``. When no snapshot
    exists yet, returns an empty tuple — replay runs then rely only on version 1
    strategy scan symbols (conservative; avoids today's watchlist hindsight).
    """
    snap_day = db.execute(
        select(func.max(WatchlistSnapshot.snapshot_date)).where(WatchlistSnapshot.snapshot_date <= as_of)
    ).scalar_one_or_none()
    if snap_day is None:
        return ()
    rows = db.execute(
        select(WatchlistSnapshot.symbol)
        .where(WatchlistSnapshot.snapshot_date == snap_day)
        .order_by(WatchlistSnapshot.symbol)
    ).scalars()
    return tuple(rows)


def latest_snapshot_date(db: Session) -> date | None:
    return db.execute(select(func.max(WatchlistSnapshot.snapshot_date))).scalar_one_or_none()
