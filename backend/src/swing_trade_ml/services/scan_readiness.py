"""Are the target session's daily candles in, so the daily scan can run? (#316 slice 1)

The scan is only as fresh as the newest daily bar. Run before the session's bars arrive, it scores
yesterday's bar as if it were today's. This check answers, before the scan runs:

- waiting:  the benchmark index, or every watchlisted stock, has no bar for the target session yet.
            The scan must not run; the record says why. "Stocks" are the ones the scan scores: the
            watchlist plus every active strategy's own list (scan_stocks).
- partial:  the benchmark and at least one stock have it, some stocks do not. The scan runs as before
            and the record names the missing stocks, so the result is never mistaken for complete.
- complete: everything required has the bar.

Read-only: it only counts candles already stored. No threshold beyond "none at all" is invented here;
coverage rules for publishing rankings are a separate, owner-approved decision (#279).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.market_session import IST, last_closed_trading_day
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.trading import Strategy

Status = Literal["waiting", "partial", "complete"]
MAX_LISTED = 20  # names kept in the scan record; the count is always exact


@dataclass(frozen=True)
class Readiness:
    target_session: date
    status: Status
    required: int  # the stocks the scan scores (scan_stocks)
    arrived: int  # of those, how many have the session's bar
    missing: list[str] = field(default_factory=list)
    reason: str = ""

    @property
    def ready(self) -> bool:
        return self.status != "waiting"

    def record(self) -> dict[str, Any]:
        """Fields added to the scan heartbeat record."""
        return {
            "status": self.status,
            "target_session": self.target_session.isoformat(),
            "required_count": self.required,
            "arrived_count": self.arrived,
            "missing_count": len(self.missing),
            "missing_symbols": self.missing[:MAX_LISTED],
            "waiting_reason": self.reason or None,
        }


def target_session(now: datetime) -> date:
    """The session whose daily bar the scan should be using: today once its bar is final (15:40 IST),
    otherwise the trading day before."""
    return last_closed_trading_day(now)


def _has_bar(db: Session, instrument_ids: list[int], day: date) -> set[int]:
    if not instrument_ids:
        return set()
    start = datetime.combine(day, time(0, 0), tzinfo=IST)  # daily candles are stamped IST midnight
    rows = db.execute(
        select(Candle.instrument_id)
        .where(
            Candle.instrument_id.in_(instrument_ids),
            Candle.interval == "day",
            Candle.ts >= start,
            Candle.ts < start + timedelta(days=1),
        )
        .distinct()
    )
    return {iid for (iid,) in rows}


def scan_stocks(db: Session) -> dict[int, str]:
    """The stocks the scan scores: active watchlisted instruments plus every ACTIVE strategy's own
    symbols (instrument id -> symbol). Indices (instrument_type == "INDEX") are never stocks."""
    watchlisted = set(
        db.execute(select(Instrument.tradingsymbol).where(Instrument.is_watchlisted.is_(True))).scalars()
    )
    extra: set[str] = set()
    for symbols in db.execute(select(Strategy.symbols).where(Strategy.is_active.is_(True))).scalars():
        extra.update(str(s).upper() for s in symbols or [])
    extra -= watchlisted
    rows = db.execute(
        select(Instrument.id, Instrument.tradingsymbol, Instrument.instrument_type).where(
            Instrument.is_active.is_(True),
            Instrument.is_watchlisted.is_(True) | Instrument.tradingsymbol.in_(extra),
        )
    ).all()
    return {iid: sym for iid, sym, kind in rows if kind != "INDEX"}


def check(db: Session, now: datetime | None = None) -> Readiness:
    day = target_session(now or datetime.now(IST))
    stocks = list(scan_stocks(db).items())
    bench_symbol = settings.BENCHMARK_INDEX_SYMBOL
    bench_ids = list(
        db.execute(select(Instrument.id).where(Instrument.tradingsymbol == bench_symbol)).scalars()
    )

    with_bar = _has_bar(db, [iid for iid, _ in stocks], day)
    missing = sorted(sym for iid, sym in stocks if iid not in with_bar)
    arrived = len(stocks) - len(missing)
    when = f"{day:%d %b}"

    if not _has_bar(db, bench_ids, day):
        reason = f"the {bench_symbol} index has no {when} candle yet"
        return Readiness(day, "waiting", len(stocks), arrived, missing, reason)
    if stocks and arrived == 0:
        reason = f"0 of {len(stocks)} watchlist stocks have their {when} candle yet"
        return Readiness(day, "waiting", len(stocks), arrived, missing, reason)
    return Readiness(day, "partial" if missing else "complete", len(stocks), arrived, missing)
