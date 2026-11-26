"""Late and corrected daily candles, for the admin screen (#565, requirements #282 G10 / A2).

Read-only. The ingestion writer already records when each bar first arrived (`candle_arrivals`) and
every overwrite of a stored bar (`candle_corrections`); this only reads them back so a person can see
them. It changes no candle, feature, score or decision.

"Late" here is a display rule only: a bar first received after the next trading session opened (09:15 IST on
the next trading day), so it could not have been used before that morning's decisions. History
downloaded for a newly added stock counts as late too, which is true: it was not on file in time.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.core.market_session import IST, next_trading_day
from swing_trade_ml.db.models.market import CandleArrival, CandleCorrection, Instrument

OPEN = time(9, 15)
DEFAULT_DAYS = 30
MAX_ROWS = 200
LATE_RULE = "A day's price bar is late when it first reached us after 09:15 IST on the next trading day."
UNKNOWN_NOTE = "Bars stored before arrival times were recorded have no arrival time, so they are not listed."


def _day(ts: datetime) -> date:
    return ts.astimezone(IST).date()


def _iso(dt: datetime) -> str:
    return dt.astimezone(IST).isoformat()


def due_by(bar_day: date) -> datetime:
    """When a bar for `bar_day` had to be on file: the next trading session's open, in IST."""
    return datetime.combine(next_trading_day(bar_day), OPEN, tzinfo=IST)


def build_candle_log(db: Session, *, now: datetime | None = None, days: int = DEFAULT_DAYS) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    since = now - timedelta(days=days)
    late: list[dict[str, Any]] = []
    arrivals = db.execute(
        select(CandleArrival, Instrument.tradingsymbol)
        .join(Instrument, Instrument.id == CandleArrival.instrument_id)
        .where(CandleArrival.interval == "day", CandleArrival.ts >= since)
        .order_by(CandleArrival.ts.desc(), Instrument.tradingsymbol)
    ).all()
    for arr, symbol in arrivals:
        bar_day = _day(arr.ts)
        due = due_by(bar_day)
        if arr.received_at > due:
            late.append(
                {
                    "symbol": symbol,
                    "day": bar_day.isoformat(),
                    "due_by": due.isoformat(),
                    "received_at": _iso(arr.received_at),
                    "late_by_hours": round((arr.received_at - due).total_seconds() / 3600, 1),
                }
            )
    corrections = [
        {
            "symbol": symbol,
            "day": _day(c.ts).isoformat(),
            "corrected_at": _iso(c.corrected_at),
            "old_close": c.old_close,
            "new_close": c.new_close,
            "close_change_pct": round(c.new_close / c.old_close - 1, 4) if c.old_close else None,
            "old_volume": c.old_volume,
            "new_volume": c.new_volume,
        }
        for c, symbol in db.execute(
            select(CandleCorrection, Instrument.tradingsymbol)
            .join(Instrument, Instrument.id == CandleCorrection.instrument_id)
            .where(CandleCorrection.interval == "day", CandleCorrection.corrected_at >= since)
            .order_by(CandleCorrection.corrected_at.desc(), Instrument.tradingsymbol)
            .limit(MAX_ROWS)
        ).all()
    ]
    return {
        "window_days": days,
        "late_rule": LATE_RULE,
        "unknown_note": UNKNOWN_NOTE,
        "late_total": len(late),
        "late": late[:MAX_ROWS],
        "corrections": corrections,
    }
