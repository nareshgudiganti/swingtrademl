"""Pure rules for horizon experiments: session timing, the simulated fill, sample counting, uncertainty.

No database access. Daily candles are stamped IST midnight; every date here is an IST trading date.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from statistics import fmean
from zoneinfo import ZoneInfo

from swing_trade_ml.core.holidays import NSE_HOLIDAYS
from swing_trade_ml.core.market_session import is_trading_day as _is_trading_day

from .protocol import Protocol, frozen_charges

IST = ZoneInfo("Asia/Kolkata")


class CalendarMissingError(Exception):
    """A date falls in a year with no NSE holiday list, so trading sessions cannot be counted honestly."""


def _check_year(d: date) -> None:
    if d.year not in NSE_HOLIDAYS:
        raise CalendarMissingError(f"No NSE holiday list for {d.year}; its sessions cannot be counted.")


def is_trading_day(d: date) -> bool:
    _check_year(d)
    return _is_trading_day(d)


def _next_session(d: date) -> date:
    d += timedelta(days=1)
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d


def cutoff(protocol_cutoff: str = "09:00") -> time:
    hh, mm = (int(x) for x in protocol_cutoff.split(":"))
    return time(hh, mm)


def entry_session(submitted_at: datetime, protocol_cutoff: str = "09:00") -> date:
    """Before the cutoff (IST) on a trading day: that session. Otherwise: the next trading session."""
    local = submitted_at.astimezone(IST)
    d = local.date()
    if is_trading_day(d) and local.time() < cutoff(protocol_cutoff):
        return d
    return _next_session(d)


def session_n(entry: date, n: int) -> date:
    """The n-th trading session counting the entry session as 1."""
    if n < 1:
        raise ValueError("n must be at least 1")
    if not is_trading_day(entry):
        raise ValueError(f"{entry} is not a trading session")
    d = entry
    for _ in range(n - 1):
        d = _next_session(d)
    return d


def cutoff_moment(session: date, protocol_cutoff: str = "09:00") -> datetime:
    """The last moment a pick for this session can still be changed."""
    return datetime.combine(session, cutoff(protocol_cutoff), IST)


@dataclass(frozen=True)
class Fill:
    qty: int
    entry_fill: float
    exit_fill: float
    gross_return: float
    net_return: float
    costs_inr: float
    slippage_inr: float


def simulate(entry_open: float, exit_close: float, protocol: Protocol) -> Fill | None:
    """Equal notional, whole shares, slippage against us on both sides, frozen charges.

    None when not even one share fits the notional."""
    slip = protocol.slippage_bps / 10_000
    entry_fill = entry_open * (1 + slip)
    exit_fill = exit_close * (1 - slip)
    qty = int(protocol.notional_inr // entry_fill)
    if qty < 1:
        return None
    buy_cost = frozen_charges(protocol.costs, qty * entry_fill, "BUY")
    sell_cost = frozen_charges(protocol.costs, qty * exit_fill, "SELL")
    basis = qty * entry_fill + buy_cost
    proceeds = qty * exit_fill - sell_cost
    return Fill(
        qty=qty,
        entry_fill=entry_fill,
        exit_fill=exit_fill,
        gross_return=exit_close / entry_open - 1,
        net_return=(proceeds - basis) / basis,
        costs_inr=buy_cost + sell_cost,
        slippage_inr=qty * (entry_fill - entry_open) + qty * (exit_close - exit_fill),
    )


def non_overlapping(windows: list[tuple[date, date]]) -> int:
    """How many holding windows can be chosen with no two overlapping (earliest-finish greedy)."""
    count, last_end = 0, None
    for start, end in sorted(windows, key=lambda w: (w[1], w[0])):
        if last_end is None or start > last_end:
            count += 1
            last_end = end
    return count


def bootstrap_mean_range(
    values: list[float], *, draws: int = 2000, level: float = 0.90, seed: int = 20261017
):
    """A (low, high) range for the mean from resampling, fixed seed so the same data gives the same range.
    None with fewer than two values. It describes noise in these picks, not a promise about future ones."""
    if len(values) < 2:
        return None
    rng = random.Random(seed)
    n = len(values)
    means = sorted(fmean(rng.choices(values, k=n)) for _ in range(draws))
    tail = (1 - level) / 2
    return means[int(tail * draws)], means[min(draws - 1, int((1 - tail) * draws))]
