"""Read one stock's event calendar: what is coming, what just happened, and
whether the exchange is watching it.

* results soon    results within the next 5 trading days. A results day can
                  gap the price past any stop, so new ideas are avoided.
* event blackout  a split, bonus, rights issue or similar within the next 2
                  trading days: the share price is about to be reset.
* price reset     such an action's ex-date was today or in the last 2 trading
                  days: a big drop then is arithmetic, not a breakdown.
* restrictions    the stock is on NSE's ASM or GSM list (a list older than 4
                  days is treated as unknown, not as current).

Plus plain card lines: the next results date within 3 weeks, and the reset.
Pure: the caller passes rows that were known by the run's date.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta

from swing_trade_ml.brain.contracts import Situation
from swing_trade_ml.brain.modules.m01_quality.quality import is_trading_day

RESULTS_WINDOW_TRADING_DAYS = 5
ACTION_WINDOW_TRADING_DAYS = 2
RESET_LOOKBACK_TRADING_DAYS = 2
RESTRICTION_MAX_AGE_DAYS = 4
NOTE_AHEAD_DAYS = 21


@dataclass(frozen=True, slots=True)
class EventRow:
    symbol: str
    kind: str  # results | corporate_action
    day: date
    detail: str = ""


@dataclass(frozen=True, slots=True)
class RestrictionRow:
    symbol: str
    kind: str  # ASM | GSM
    stage: str
    as_of: date


@dataclass(frozen=True, slots=True)
class StockEvents:
    situations: tuple[Situation, ...] = ()
    restrictions: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


def trading_days_until(today: date, day: date) -> int:
    """Trading days from `today` to `day`: 0 for the same day, negative for
    the past (trading days since)."""
    lo, hi, sign = (today, day, 1) if day >= today else (day, today, -1)
    count, d = 0, lo
    while d < hi:
        d += timedelta(days=1)
        if is_trading_day(d):
            count += 1
    return sign * count


def _situation(symbol: str, label: str, evidence: str) -> Situation:
    return Situation(scope="stock", subject=symbol, label=label, confidence=1.0, evidence=(evidence,))


def read_calendar(
    symbol: str, today: date, events: Iterable[EventRow], restrictions: Iterable[RestrictionRow]
) -> StockEvents:
    mine = sorted((e for e in events if e.symbol == symbol), key=lambda e: e.day)
    situations: list[Situation] = []
    notes: list[str] = []

    results = next((e for e in mine if e.kind == "results" and e.day >= today), None)
    if results is not None and (results.day - today).days <= NOTE_AHEAD_DAYS:
        notes.append(f"Results on {results.day:%d %b}.")
        if trading_days_until(today, results.day) <= RESULTS_WINDOW_TRADING_DAYS:
            situations.append(
                _situation(
                    symbol,
                    "results soon",
                    f"Results on {results.day:%d %b}: the brain avoids new trades "
                    f"{RESULTS_WINDOW_TRADING_DAYS} trading days before results",
                )
            )

    for action in (e for e in mine if e.kind == "corporate_action"):
        until = trading_days_until(today, action.day)
        if 0 < until <= ACTION_WINDOW_TRADING_DAYS:
            situations.append(
                _situation(
                    symbol,
                    "event blackout",
                    f"{action.detail} on {action.day:%d %b} resets the share price",
                )
            )
        elif -RESET_LOOKBACK_TRADING_DAYS <= until <= 0:
            line = (
                f"{action.detail} took effect on {action.day:%d %b}; a drop in the share price then "
                "is the reset, not a fall in value."
            )
            situations.append(_situation(symbol, "price reset", line))
            notes.append(line)

    current = [
        r
        for r in restrictions
        if r.symbol == symbol and today - timedelta(days=RESTRICTION_MAX_AGE_DAYS) <= r.as_of <= today
    ]
    names = tuple(dict.fromkeys(f"{r.kind} ({r.stage})" if r.stage else r.kind for r in current))
    return StockEvents(situations=tuple(situations), restrictions=names, notes=tuple(notes))
