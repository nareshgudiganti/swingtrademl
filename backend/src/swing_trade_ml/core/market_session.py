"""The app's one market clock (one-app technical design, step 2).

Every "is it a trading day / is the market open / when does it open next"
question in the app is answered here, from the NSE holiday list in
`core.holidays` and the session times in settings (09:15 to 15:30 IST).

A year missing from the holiday list is never an error: weekdays count as
trading days (the app's long-standing fail-safe rule — a scan on an unlisted
holiday just finds no new bar), and `calendar_warning` says so plainly from
1 November of the year before, so the list is added in time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.holidays import NSE_HOLIDAYS

IST = ZoneInfo("Asia/Kolkata")

# Ten minutes after the 15:30 close the day's daily bar is final.
SESSION_FINAL = time(15, 40)
# From this day the next year's holiday list should be in place.
CALENDAR_WARN_FROM = (11, 1)


class SessionState(StrEnum):
    PRE_OPEN = "pre_open"
    OPEN = "open"
    CLOSED = "closed"
    WEEKEND = "weekend"
    HOLIDAY = "holiday"


@dataclass(frozen=True)
class MarketSession:
    state: SessionState
    now: datetime
    trading_day: bool
    opens_at: datetime | None  # today's open, on a trading day
    closes_at: datetime | None  # today's close, on a trading day
    next_open: datetime  # the next open strictly after now
    next_close: datetime  # the next close at or after now
    last_closed_trading_day: date
    plain: str


def _now() -> datetime:
    return datetime.now(UTC)


def _ist(now: datetime | None) -> datetime:
    return (now or _now()).astimezone(IST)


def is_holiday(d: date) -> bool:
    return d in NSE_HOLIDAYS.get(d.year, set())


def is_trading_day(d: date) -> bool:
    """A weekday that is not a listed NSE holiday."""
    return d.weekday() < 5 and not is_holiday(d)


def next_trading_day(d: date) -> date:
    d += timedelta(days=1)
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d


def previous_trading_day(d: date) -> date:
    d -= timedelta(days=1)
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d


def trading_days_between(earlier: date, later: date) -> int:
    """Trading days strictly after `earlier`, up to and including `later`."""
    count, d = 0, earlier + timedelta(days=1)
    while d <= later:
        if is_trading_day(d):
            count += 1
        d += timedelta(days=1)
    return count


def _at(d: date, t: time) -> datetime:
    return datetime.combine(d, t, tzinfo=IST)


def is_open(now: datetime | None = None, *, include_close: bool = False) -> bool:
    """In the session. Orders use the default (never at or after the close);
    `include_close=True` is ingestion's long-standing inclusive rule."""
    local = _ist(now)
    if not is_trading_day(local.date()):
        return False
    t = local.time()
    if t < settings.market_open:
        return False
    return t <= settings.market_close if include_close else t < settings.market_close


def last_closed_trading_day(now: datetime) -> date:
    """The latest trading day whose daily bar can no longer change: today only
    from 15:40 IST on a trading day, otherwise the trading day before. Weekends
    and listed holidays are both skipped."""
    local = now.astimezone(IST)
    day = local.date()
    if is_trading_day(day) and local.time() >= SESSION_FINAL:
        return day
    return previous_trading_day(day)


def _clock(t: time) -> str:
    hour = t.hour % 12 or 12
    return f"{hour}:{t.minute:02d} {'am' if t.hour < 12 else 'pm'}"


def when(dt: datetime) -> str:
    """e.g. 'Mon 05 Oct, 9:15 am' (IST)."""
    return _when(dt.astimezone(IST))


def _when(dt: datetime) -> str:
    return f"{dt:%a %d %b}, {_clock(dt.timetz())}"


def session(now: datetime | None = None) -> MarketSession:
    local = _ist(now)
    today = local.date()
    trading = is_trading_day(today)
    t = local.time()
    opens = _at(today, settings.market_open) if trading else None
    closes = _at(today, settings.market_close) if trading else None
    if not trading:
        state = SessionState.WEEKEND if today.weekday() >= 5 else SessionState.HOLIDAY
    elif t < settings.market_open:
        state = SessionState.PRE_OPEN
    elif t < settings.market_close:
        state = SessionState.OPEN
    else:
        state = SessionState.CLOSED
    next_open = (
        opens if state is SessionState.PRE_OPEN else _at(next_trading_day(today), settings.market_open)
    )
    next_close = (
        closes
        if state in (SessionState.PRE_OPEN, SessionState.OPEN)
        else _at(next_trading_day(today), settings.market_close)
    )
    if state is SessionState.OPEN:
        plain = f"Market open · closes {_clock(settings.market_close)}"
    elif state is SessionState.PRE_OPEN:
        plain = f"Market opens at {_clock(settings.market_open)}"
    else:
        plain = f"Market closed · opens {_when(next_open)}"
    return MarketSession(
        state=state,
        now=local,
        trading_day=trading,
        opens_at=opens,
        closes_at=closes,
        next_open=next_open,
        next_close=next_close,
        last_closed_trading_day=last_closed_trading_day(local),
        plain=plain,
    )


def calendar_warning(today: date | None = None) -> str | None:
    """A plain warning when the holiday list for this year — or, from
    1 November, for next year — is missing; None when it is in place."""
    today = today or _ist(None).date()
    if today.year not in NSE_HOLIDAYS:
        return (
            f"The {today.year} stock-market holiday list is missing, so holidays count as trading days. "
            f"Add the {today.year} NSE holidays."
        )
    if (today.month, today.day) >= CALENDAR_WARN_FROM and today.year + 1 not in NSE_HOLIDAYS:
        return (
            f"The {today.year + 1} NSE holiday list is not added yet. Add it before 1 Jan {today.year + 1}."
        )
    return None
