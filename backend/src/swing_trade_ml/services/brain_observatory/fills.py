"""How realistic are our fill prices? (ps4, 2026-10-20). Read-only.

The paper broker fills at the price it can see at that moment: the live price in market hours, but the
last stored close when the market is shut. A real order placed after the close would fill at the NEXT
session's open instead. This compares every filled order with what the market really offered:

- **in market hours**: was the price inside that day's low-high range (a fill outside it was impossible),
  and how far was it from the day's typical price, (high + low + close) / 3, a stand-in for the average
  price traded that day (daily bars have no intraday detail);
- **outside market hours**: how far was it from the open of the next session, the price a real order
  placed then would have met first.

`better_by_bps` is how much better the recorded price was for us than that reference, in basis points
(100 = 1%): above zero means the record flatters the result. Paper and real (live) orders are reported
apart and never added together. The monthly figure feeds ps3 (cost stress) with a measured number.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import mean, median
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.core import market_session
from swing_trade_ml.core.enums import OrderStatus
from swing_trade_ml.core.market_session import IST

RANGE_TOLERANCE = 0.0005  # 0.05%: rounding to the tick is not "outside the range"


@dataclass(frozen=True, slots=True)
class Fill:
    order_id: int
    symbol: str
    mode: str  # paper | live
    side: str  # BUY | SELL
    filled_at: datetime
    price: float


@dataclass(frozen=True, slots=True)
class Bar:
    open: float
    high: float
    low: float
    close: float


def _reference_day(filled_at: datetime) -> tuple[str, date]:
    """("in_hours", that day) or ("after_hours", the session whose open a real order would meet)."""
    local = filled_at.astimezone(IST)
    if market_session.is_open(filled_at, include_close=True):
        return "in_hours", local.date()
    d = local.date()
    if market_session.is_trading_day(d) and local.time() < market_session.settings.market_open:
        return "after_hours", d  # before the open: today's open is the next price
    return "after_hours", market_session.next_trading_day(d)


def judge(fill: Fill, bars: dict[date, Bar]) -> dict[str, Any]:
    kind, day = _reference_day(fill.filled_at)
    row: dict[str, Any] = {
        "order_id": fill.order_id,
        "symbol": fill.symbol,
        "mode": fill.mode,
        "side": fill.side,
        "kind": kind,
        "filled_at": fill.filled_at.isoformat(),
        "price": fill.price,
        "reference_day": day.isoformat(),
    }
    bar = bars.get(day)
    if bar is None:
        return row | {"reference": None, "better_by_bps": None, "outside_range": None}
    if kind == "in_hours":
        reference = (bar.high + bar.low + bar.close) / 3
        lo, hi = bar.low * (1 - RANGE_TOLERANCE), bar.high * (1 + RANGE_TOLERANCE)
        outside = not lo <= fill.price <= hi
    else:
        reference, outside = bar.open, None
    sign = 1 if fill.side == "BUY" else -1  # a buy below the reference, or a sell above it, flatters us
    better = sign * (reference - fill.price) / reference * 10_000
    return row | {
        "reference": round(reference, 4),
        "better_by_bps": round(better, 1),
        "outside_range": outside,
    }


def _stats(rows: list[dict]) -> dict[str, Any]:
    scored = [r["better_by_bps"] for r in rows if r["better_by_bps"] is not None]
    in_hours = [r for r in rows if r["kind"] == "in_hours" and r["outside_range"] is not None]
    return {
        "fills": len(rows),
        "scored": len(scored),
        "no_price_data": len(rows) - len(scored),
        "avg_better_by_bps": round(mean(scored), 1) if scored else None,
        "median_better_by_bps": round(median(scored), 1) if scored else None,
        "outside_day_range": sum(bool(r["outside_range"]) for r in in_hours),
    }


def summarise(rows: list[dict]) -> dict[str, Any]:
    """Per mode (paper / live, never mixed), split by in / outside market hours."""
    out: dict[str, Any] = {}
    for mode in sorted({r["mode"] for r in rows}):
        mine = [r for r in rows if r["mode"] == mode]
        out[mode] = {
            "all": _stats(mine),
            "in_hours": _stats([r for r in mine if r["kind"] == "in_hours"]),
            "after_hours": _stats([r for r in mine if r["kind"] == "after_hours"]),
        }
    return out


# --- database ----------------------------------------------------------------------------------


def _ist_midnight(d: date) -> datetime:
    return datetime.combine(d, datetime.min.time(), tzinfo=IST)


def load_fills(db: Session, start: date, end: date) -> tuple[list[Fill], dict[str, int]]:
    """Filled orders from `start` to `end` (IST days, inclusive), and each symbol's instrument id."""
    from swing_trade_ml.db.models.market import Instrument
    from swing_trade_ml.db.models.trading import Order

    lo, hi = _ist_midnight(start), _ist_midnight(end + timedelta(days=1))
    rows = db.execute(
        select(
            Order.id,
            Instrument.tradingsymbol,
            Order.mode,
            Order.transaction_type,
            Order.filled_at,
            Order.average_price,
            Order.instrument_id,
        )
        .join(Instrument, Instrument.id == Order.instrument_id)
        .where(
            Order.status == OrderStatus.COMPLETE,
            Order.average_price.isnot(None),
            Order.filled_at.isnot(None),
            Order.filled_at >= lo,
            Order.filled_at < hi,
        )
        .order_by(Order.filled_at)
    ).all()
    return [
        Fill(order_id=r[0], symbol=r[1], mode=str(r[2]), side=str(r[3]), filled_at=r[4], price=float(r[5]))
        for r in rows
    ], {r[1]: r[6] for r in rows}


def load_bars(
    db: Session, instrument_ids: dict[str, int], start: date, end: date
) -> dict[str, dict[date, Bar]]:
    from swing_trade_ml.db.models.market import Candle

    # From the day before (a candle is stamped 18:30 UTC the previous day) to well past the next session.
    lo, hi = _ist_midnight(start - timedelta(days=1)), _ist_midnight(end + timedelta(days=10))
    out: dict[str, dict[date, Bar]] = {}
    for symbol, iid in instrument_ids.items():
        rows = db.execute(
            select(Candle.ts, Candle.open, Candle.high, Candle.low, Candle.close).where(
                Candle.instrument_id == iid, Candle.interval == "day", Candle.ts >= lo, Candle.ts < hi
            )
        ).all()
        # Daily candles are stamped at IST midnight (18:30 UTC the day before): always convert to IST.
        out[symbol] = {
            ts.astimezone(IST).date(): Bar(*map(float, (o, h, low, c))) for ts, o, h, low, c in rows
        }
    return out


def fill_quality(db: Session, start: date, end: date) -> dict[str, Any]:
    fills, ids = load_fills(db, start, end)
    bars = load_bars(db, ids, start, end)
    rows = [judge(f, bars.get(f.symbol, {})) for f in fills]
    return {"from": start.isoformat(), "to": end.isoformat(), "summary": summarise(rows), "fills": rows}
