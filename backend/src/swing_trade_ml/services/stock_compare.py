"""Stock Compare: how far each stock's price moved over 1 week to 5 years, from the daily candles we store.

Display only. It reads stored candles, changes no pick, order, stop, size or limit, and the brain never reads
it. A period we do not have enough history for is None ("not enough history"), never a guess."""

from __future__ import annotations

from datetime import date, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.db.models.market import Candle, Instrument

IST = ZoneInfo("Asia/Kolkata")

MAX_STOCKS = 3

# Calendar-day look-backs, shown in this order.
PERIODS: tuple[tuple[str, int], ...] = (
    ("1W", 7),
    ("1M", 30),
    ("3M", 91),
    ("6M", 182),
    ("1Y", 365),
    ("2Y", 730),
    ("3Y", 1095),
    ("5Y", 1826),
)

# A base close more than this many days before the target date means a gap in our data (or a long closure),
# so the period is reported as not available instead of using a far-off day.
_MAX_GAP_DAYS = 7


def period_returns(closes: list[tuple[date, float]]) -> dict[str, float | None]:
    """Percent change from the last close back over each period. `closes` is (IST date, close), any order.
    A period is None when the history starts after the target date or the nearest earlier close is too old."""
    labels = [label for label, _ in PERIODS]
    rows = sorted(c for c in closes if c[1] and c[1] > 0)
    if not rows:
        return dict.fromkeys(labels)
    last_day, last_close = rows[-1]
    out: dict[str, float | None] = {}
    for label, days in PERIODS:
        target = last_day - timedelta(days=days)
        base = next(((d, c) for d, c in reversed(rows) if d <= target), None)
        if base is None or (target - base[0]).days > _MAX_GAP_DAYS:
            out[label] = None
        else:
            out[label] = round((last_close / base[1] - 1) * 100, 2)
    return out


def _view_for(db: Session, symbol: str) -> dict:
    inst = db.execute(
        select(Instrument).where(Instrument.tradingsymbol == symbol, Instrument.exchange == "NSE")
    ).scalar_one_or_none()
    if inst is None:
        return {
            "symbol": symbol,
            "name": None,
            "state": "unknown",
            "as_of": None,
            "last_close": None,
            "returns": {},
        }
    rows = db.execute(
        select(Candle.ts, Candle.close)
        .where(Candle.instrument_id == inst.id, Candle.interval == "day")
        .order_by(Candle.ts.desc())
        .limit(1900)
    ).all()
    # Daily candles are stamped IST midnight (18:30 UTC the day before): always read the IST date.
    closes = [(ts.astimezone(IST).date(), float(close)) for ts, close in rows]
    if not closes:
        return {
            "symbol": symbol,
            "name": inst.name,
            "state": "no_history",
            "as_of": None,
            "last_close": None,
            "returns": {},
        }
    latest = max(closes)
    return {
        "symbol": symbol,
        "name": inst.name,
        "state": "ok",
        "as_of": latest[0].isoformat(),
        "last_close": latest[1],
        "returns": period_returns(closes),
    }


def parse_symbols(raw: str) -> list[str]:
    """'a, B,a' -> ['A', 'B']: upper-case, blanks and repeats dropped, order kept."""
    return list(dict.fromkeys(s.strip().upper() for s in raw.split(",") if s.strip()))


def build_compare(db: Session, symbols: list[str]) -> dict:
    return {"periods": [label for label, _ in PERIODS], "stocks": [_view_for(db, s) for s in symbols]}
