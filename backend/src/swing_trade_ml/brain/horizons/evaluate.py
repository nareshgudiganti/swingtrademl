"""Evaluate a stored horizon record against later daily bars, using that record's own target and stop.

Starting price = the open of the session after the input session (owner decision 2026-11-20, #387; the
same entry as the h05 lane's shadow trade, without its costs and slippage). That entry session is
holding session 1. Sessions 1..horizon are walked in order using only bars on or before `as_of`:
- the low reaching the stop ends it as "stop" (checked first, so a session touching both counts as stop);
- the high reaching the target ends it as "target";
- reaching the last session with neither ends it as "time", dated that session on the supplied calendar.
Missing versus impossible:
- A session with NO bar is "pending" until a bar of a LATER session, on or before `as_of`, exists for the same
  stock; only then is the gap real and the record "unmeasurable". A candle that has simply not arrived yet is
  never a result: when it arrives, the next check gives the true one. A bar dated after `as_of` is never read,
  not even to decide that a gap is real.
- A bar that is PRESENT but cannot be real (a price that is not finite and positive, or an open or close
  outside the day's low-high range) is "unmeasurable" at once.
- Either way a missing session is never filled from the next bar, skipped, or counted as a quiet session.
A calendar that stops before a needed session only leaves the record "pending": it proves nothing about the
data, and a pending record is checked again with a longer calendar.

`as_of` must be a CLOSED session (or any date after one): this module has no clock, so it cannot tell that a
bar dated `as_of` is still forming. A partial candle on the last session would otherwise end as a "time" exit.

What the result means (it is not the h05 lane's result):
- `label` 1 = the target was touched BEFORE the stop within the horizon; 0 = the stop first, or neither
  (time). The h05 lane's `label_hit` is a different question: is the CLOSE of session 5 at least +2% above
  the signal close? The two can disagree for the same stock and day; never show them as one number.
- The 15D plan's half-out at +5% is stored on the record but NOT evaluated here: a trade that reaches +5% and
  then the stop is label 0. Only the target and the stop decide the label.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from math import isclose, isfinite

from swing_trade_ml.brain.horizons.workflow import NO_DECISION, HorizonRecord, due_session

Bar = tuple[float, float, float, float]  # open, high, low, close


@dataclass(frozen=True, slots=True)
class Evaluation:
    status: str  # pending | complete | unmeasurable | no_decision
    exit_reason: str | None = None  # target | stop | time
    exit_session: date | None = None
    label: int | None = None  # 1 = target reached first, 0 = stop or time
    note: str = ""
    entry_session: date | None = None
    entry_price: float | None = None


def _usable(bar: Bar) -> bool:
    """A candle that can be real: every price finite and positive, low <= open and close <= high."""
    o, h, low, c = bar
    if not all(isfinite(p) and p > 0 for p in bar):
        return False
    return low <= o <= h and low <= c <= h


def _later_bar_exists(sessions: Sequence[date], bars: Mapping[date, Bar], day: date, as_of: date) -> bool:
    """True when this stock has a bar on a session after `day` and on or before `as_of`, so a missing bar on
    `day` is a real gap and not a candle that has not arrived yet. A bar after `as_of` is never counted."""
    return any(day < d <= as_of and d in bars for d in sessions)


def evaluate_record(
    record: HorizonRecord, sessions: Sequence[date], bars: Mapping[date, Bar], *, as_of: date
) -> Evaluation:
    if record.decision == NO_DECISION:
        return Evaluation("no_decision", note=record.reason)
    assert record.target_pct and record.stop_pct  # set on every decided record
    entry_day = due_session(sessions, record.input_session, 1)
    if entry_day is None:  # a calendar that stops early says nothing about the data: wait for a longer one
        return Evaluation("pending", note="the calendar does not reach the entry session yet")
    if entry_day > as_of:
        return Evaluation("pending", note=f"the entry session ({entry_day}) has not closed yet")
    entry_bar = bars.get(entry_day)
    if entry_bar is None:
        if _later_bar_exists(sessions, bars, entry_day, as_of):
            return Evaluation("unmeasurable", note=f"no candle on the entry session ({entry_day})")
        return Evaluation("pending", note=f"the entry session's candle ({entry_day}) has not arrived yet")
    if not _usable(entry_bar):
        return Evaluation("unmeasurable", note=f"no usable candle on the entry session ({entry_day})")
    entry = entry_bar[0]
    target = entry * (1 + record.target_pct)
    stop = entry * (1 - record.stop_pct)

    def result(status: str, *args, note: str = "") -> Evaluation:
        return Evaluation(status, *args, note=note, entry_session=entry_day, entry_price=entry)

    day = entry_day
    for n in range(1, record.decision_horizon + 1):
        day = due_session(sessions, record.input_session, n)
        if day is None:  # not proof of a data problem; a calendar that ends at as_of simply stops early
            return result("pending", note=f"the calendar does not reach session {n} yet")
        if day > as_of:
            return result("pending", note=f"session {n} ({day}) has not closed yet")
        bar = bars.get(day)
        if bar is None:
            if _later_bar_exists(sessions, bars, day, as_of):
                return result("unmeasurable", note=f"no candle on session {n} ({day})")
            return result("pending", note=f"the candle for session {n} ({day}) has not arrived yet")
        if not _usable(bar):
            return result("unmeasurable", note=f"unusable candle on session {n} ({day})")
        _, high, low, _ = bar
        # A price exactly on the line counts as touching it: 110 * 1.08 is 118.80000000000001 in floating
        # point, but the tape shows 118.80. Prices move in paise, so a relative 1e-9 hides no real miss.
        if low <= stop or isclose(low, stop, rel_tol=1e-9):
            return result("complete", "stop", day, 0)
        if high >= target or isclose(high, target, rel_tol=1e-9):
            return result("complete", "target", day, 1)
    return result("complete", "time", day, 0)
