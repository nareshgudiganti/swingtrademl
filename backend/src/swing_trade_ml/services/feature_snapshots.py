"""M02 feature snapshot invalidation when candles are corrected (Service 1 #13)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.brain import FeatureSnapshot
from swing_trade_ml.db.models.market import Instrument

log = get_logger(__name__)
IST = ZoneInfo("Asia/Kolkata")


def bar_date_from_candle_ts(ts: datetime) -> date:
    """IST calendar day for a daily candle timestamp (matches M02 `as_of`)."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts.astimezone(IST).date()


def invalidate_snapshots_from(db: Session, symbol: str, from_bar_date: date) -> int:
    """Drop stored M02 rows from `from_bar_date` onward so the next nightly run recomputes them."""
    result = db.execute(
        delete(FeatureSnapshot).where(
            FeatureSnapshot.symbol == symbol,
            FeatureSnapshot.bar_date >= from_bar_date,
        )
    )
    count = result.rowcount or 0
    if count:
        log.info(
            "feature_snapshots.invalidated",
            symbol=symbol,
            from_date=from_bar_date.isoformat(),
            count=count,
        )
    return count


def invalidate_snapshots_for_candle_corrections(
    db: Session,
    instrument_id: int,
    interval: str,
    correction_ts: list[datetime],
) -> int:
    """After a daily bar overwrite, invalidate affected brain feature snapshots."""
    if interval != "day" or not correction_ts:
        return 0
    symbol = db.execute(
        select(Instrument.tradingsymbol).where(Instrument.id == instrument_id)
    ).scalar_one_or_none()
    if not symbol:
        return 0
    from_date = min(bar_date_from_candle_ts(ts) for ts in correction_ts)
    return invalidate_snapshots_from(db, symbol, from_date)
