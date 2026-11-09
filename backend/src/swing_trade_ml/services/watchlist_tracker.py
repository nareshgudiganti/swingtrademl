"""Groww Tracker: pure maths for the personal watchlist tracker.

Read-only and display-only. Nothing in trading, sizing, exits, limits or the
brain reads this. No database here, so every rule is unit-testable.
"""

from __future__ import annotations

from datetime import date, datetime

from swing_trade_ml.core.market_session import IST

HORIZON_DAYS = 15
STOP_WARN_PCT = -3.0  # within 1 point of the -4% stop, or beyond it
TARGET_PCT = 5.0  # the half-out level
TIME_WARN_DAYS = 13
WEAK_SCORE_DROP = -10.0


def ist_date(ts: datetime) -> date:
    """Daily candles are stamped IST midnight (18:30 UTC the day before): always convert."""
    return ts.astimezone(IST).date()


def return_pct(entry: float | None, last: float | None) -> float | None:
    if entry is None or last is None or entry <= 0:
        return None
    return (last / entry - 1.0) * 100.0


def today_pct(closes: list[tuple[date, float]]) -> float | None:
    """Last close vs the one before it (oldest first)."""
    if len(closes) < 2 or closes[-2][1] <= 0:
        return None
    return (closes[-1][1] / closes[-2][1] - 1.0) * 100.0


def pick_entry(
    added: date, buy_price: float | None, closes: list[tuple[date, float]]
) -> tuple[float | None, str | None, list[tuple[date, float]]]:
    """(entry price, source, closes from the entry day onward). Closes are oldest first."""
    after = [(d, c) for d, c in closes if d >= added]
    if buy_price is not None and buy_price > 0:
        return buy_price, "your_price", after
    if after:
        return after[0][1], "added_close", after
    return None, None, after


def days_done(after: list[tuple[date, float]]) -> int:
    """Trading days since the entry day (0 on that day); only days that have candles count."""
    return max(0, min(len(after) - 1, HORIZON_DAYS))


def state(ret: float | None, days: int, score_first: float | None, score_today: float | None) -> str:
    """stop > target > time > weak > ok. Missing data never makes it more aggressive."""
    if ret is not None:
        if ret <= STOP_WARN_PCT:
            return "stop"
        if ret >= TARGET_PCT:
            return "target"
    if days >= TIME_WARN_DAYS:
        return "time"
    if score_first is not None and score_today is not None and score_today - score_first <= WEAK_SCORE_DROP:
        return "weak"
    return "ok"


def build_item(
    *,
    symbol: str,
    name: str | None,
    added_at: datetime,
    note: str | None,
    buy_price: float | None,
    candles: list[tuple[date, float]],
    scores: list[tuple[date, float]],
) -> dict:
    """One tracker row. `candles`/`scores` are (IST date, value), oldest first."""
    added = ist_date(added_at)
    entry, source, after = pick_entry(added, buy_price, candles)
    last = candles[-1][1] if candles else None
    ret = return_pct(entry, last)
    days = days_done(after)
    sc = [(d, s) for d, s in scores if d >= added]
    s_today = sc[-1][1] if sc else None
    s_prev = sc[-2][1] if len(sc) >= 2 else None
    s_first = sc[0][1] if sc else None
    return {
        "symbol": symbol,
        "name": name,
        "added_at": added_at.isoformat(),
        "note": note,
        "buy_price": buy_price,
        "entry_price": entry,
        "entry_source": source,
        "last_price": last,
        "return_pct": ret,
        "today_pct": today_pct(candles),
        "days_done": days,
        "score_today": s_today,
        "score_prev": s_prev,
        "score_delta": (s_today - s_prev) if s_today is not None and s_prev is not None else None,
        "score_first": s_first,
        "scores": [{"date": d.isoformat(), "score": s} for d, s in sc],
        "closes": [{"date": d.isoformat(), "close": c} for d, c in after],
        "state": state(ret, days, s_first, s_today),
    }
