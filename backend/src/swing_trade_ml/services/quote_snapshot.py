"""One honest price for a stock page: what it is, and as of when.

The stock page used to show the last stored daily close with a bare "at last
close" label. This module decides, from the stored quote and the stored daily
candles, which price may be shown and how it must be labelled. It is a pure
read-side helper: it never writes, never touches brain decisions, and never
feeds order placement or risk checks.

Rules (all of them lean toward showing less, never a fresher-looking number):
  * In the session, a fresh stored quote is LIVE; a few minutes old is DELAYED;
    older than 15 minutes, from an earlier day, or from the future is STALE.
  * With no usable quote, the last stored close is shown with its own date.
  * The change % needs a verified previous close: the candle for the session
    before the price's session. A missing day, a gap, or a quote/candle
    previous-close disagreement hides the change instead of guessing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from zoneinfo import ZoneInfo

from swing_trade_ml.core import market_session
from swing_trade_ml.core.config import settings

IST = ZoneInfo("Asia/Kolkata")

# A quote is LIVE for a few poll cycles, DELAYED after that, STALE past 15 minutes.
STALE_AFTER_SECONDS = 15 * 60
# Quote vs candle previous close may differ by rounding only.
PREV_CLOSE_TOLERANCE = 0.001  # 0.1%: the JAMNAAUTO gap (123.16 vs 123.57) is 0.33%


def _live_max_seconds() -> int:
    return max(180, 3 * settings.LIVE_POLL_SECONDS)


class SnapshotState(StrEnum):
    LIVE = "live"
    DELAYED = "delayed"
    STALE = "stale"
    CLOSE_ONLY = "close_only"  # session open, but only the last close is available
    CLOSED = "closed"
    HOLIDAY = "holiday"
    NO_DATA = "no_data"


@dataclass(frozen=True)
class QuotePoint:
    last_price: float
    prev_close: float | None
    ts: datetime


@dataclass(frozen=True)
class CandlePoint:
    day: date  # IST trading day
    close: float


@dataclass(frozen=True)
class Snapshot:
    state: SnapshotState
    price: float | None
    price_ts: datetime | None  # a live quote's time
    price_date: date | None  # a close's trading day
    prev_close: float | None
    prev_close_date: date | None
    change_pct: float | None
    age_seconds: int | None
    prev_close_mismatch: bool
    note: str


def candle_points(rows: list, *, tz: ZoneInfo = IST) -> list[CandlePoint]:
    """Stored candles (oldest first) as IST trading days. Daily bars are stamped
    IST midnight, so the date must be taken in IST, never UTC."""
    return [CandlePoint(day=r.ts.astimezone(tz).date(), close=float(r.close)) for r in rows]


def _pct(price: float, prev: float) -> float | None:
    return (price / prev - 1) * 100 if prev else None


def _from_close(now: datetime, sess: market_session.MarketSession, bars: list[CandlePoint]) -> Snapshot:
    last = bars[-1]
    before = bars[-2] if len(bars) > 1 else None
    expected_prev = market_session.previous_trading_day(last.day)
    prev_ok = before is not None and before.day == expected_prev
    change = _pct(last.close, before.close) if prev_ok and before else None
    in_session = sess.state is market_session.SessionState.OPEN

    if last.day < sess.last_closed_trading_day:
        state, change = SnapshotState.STALE, None
        note = f"Latest price on file is the close of {last.day:%d %b}; newer prices have not arrived."
    elif in_session:
        state = SnapshotState.CLOSE_ONLY
        note = f"Live price not available; showing the close of {last.day:%d %b}."
    elif sess.state is market_session.SessionState.HOLIDAY:
        state = SnapshotState.HOLIDAY
        note = f"Market holiday today; showing the close of {last.day:%d %b}."
    else:
        state = SnapshotState.CLOSED
        note = f"Market closed; showing the close of {last.day:%d %b}."
    if state is not SnapshotState.STALE and not prev_ok:
        note += " The move is hidden because the previous day's close is missing."
    return Snapshot(
        state=state,
        price=last.close,
        price_ts=None,
        price_date=last.day,
        prev_close=before.close if prev_ok and before else None,
        prev_close_date=before.day if prev_ok and before else None,
        change_pct=change,
        age_seconds=None,
        prev_close_mismatch=False,
        note=note,
    )


def _from_quote(
    now: datetime, sess: market_session.MarketSession, quote: QuotePoint, bars: list[CandlePoint]
) -> Snapshot:
    age = int((now - quote.ts).total_seconds())
    today = now.astimezone(IST).date()
    quote_day = quote.ts.astimezone(IST).date()
    if age < 0 or quote_day != today or age > STALE_AFTER_SECONDS:
        state = SnapshotState.STALE
    elif age > _live_max_seconds():
        state = SnapshotState.DELAYED
    else:
        state = SnapshotState.LIVE

    ref_day = sess.last_closed_trading_day
    ref = next((b for b in bars if b.day == ref_day), None)
    mismatch = bool(
        ref is not None
        and quote.prev_close
        and abs(quote.prev_close - ref.close) / ref.close > PREV_CLOSE_TOLERANCE
    )
    verified = ref is not None and not mismatch and bool(quote.prev_close)
    change = _pct(quote.last_price, ref.close) if verified and ref else None
    if state is SnapshotState.STALE:
        change = None

    if state is SnapshotState.LIVE:
        note = f"Live price as of {quote.ts.astimezone(IST):%d %b, %H:%M} IST."
    elif state is SnapshotState.DELAYED:
        note = f"Delayed price from {quote.ts.astimezone(IST):%d %b, %H:%M} IST ({age // 60} min old)."
    else:
        note = f"Price on file is old ({quote.ts.astimezone(IST):%d %b, %H:%M} IST); not shown as live."
    if mismatch:
        note += " The move is hidden because two sources disagree on yesterday's close."
    elif ref is None and state is not SnapshotState.STALE:
        note += " The move is hidden because yesterday's close is not on file."
    return Snapshot(
        state=state,
        price=quote.last_price,
        price_ts=quote.ts,
        price_date=None,
        prev_close=ref.close if ref else quote.prev_close,
        prev_close_date=ref.day if ref and not mismatch else None,
        change_pct=change,
        age_seconds=age,
        prev_close_mismatch=mismatch,
        note=note,
    )


def build_snapshot(now: datetime, quote: QuotePoint | None, candles: list[CandlePoint]) -> Snapshot:
    """`candles` oldest first. `now` is any timezone-aware instant."""
    now = now.astimezone(UTC)
    sess = market_session.session(now)
    bars = sorted(candles, key=lambda c: c.day)
    in_session = sess.state is market_session.SessionState.OPEN
    if in_session and quote is not None:
        return _from_quote(now, sess, quote, bars)
    if not bars:
        return Snapshot(
            SnapshotState.NO_DATA, None, None, None, None, None, None, None, False, "No price on file yet."
        )
    return _from_close(now, sess, bars)
