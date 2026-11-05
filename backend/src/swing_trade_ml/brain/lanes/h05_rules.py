# backend/src/swing_trade_ml/brain/lanes/h05_rules.py
# ruff: noqa: E501, N812 (short P / R import aliases and long report sentences, as in brain/five_day.py)
"""Pure rules for the h05 lane: sessions, the endpoint label, the fixed-rule shadow trade, ranking.

No database, no broker, no clock. Every date is an IST trading date. `sessions` is the sorted list of
market sessions (NIFTY daily bars); a stock's own bars are looked up by date, so a stock that skipped a
session is UNRESOLVED instead of silently counted on its next bar.
"""

from __future__ import annotations

import bisect
import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from statistics import fmean

import numpy as np

from swing_trade_ml.brain.lanes import h05_protocol as P

Bar = tuple[float, float, float, float]  # open, high, low, close


# ------------------------------------------------------------------ sessions


def session_index(sessions: Sequence[date], day: date) -> int | None:
    i = bisect.bisect_left(sessions, day)
    return i if i < len(sessions) and sessions[i] == day else None


def sessions_after(sessions: Sequence[date], day: date, n: int) -> list[date]:
    """Up to `n` market sessions strictly after `day` (session 1 first). Shorter than `n` = not all happened yet."""
    i = session_index(sessions, day)
    return [] if i is None else list(sessions[i + 1 : i + 1 + n])


# ------------------------------------------------------------------ the endpoint label (what the model learned)


@dataclass(frozen=True)
class EndpointOutcome:
    status: str  # pending | evaluated | not_evaluated
    label: int | None
    day5: date | None
    close5: float | None
    note: str = ""


def endpoint_outcome(
    closes: dict[date, float], sessions: Sequence[date], signal_day: date
) -> EndpointOutcome:
    """Does the close five market sessions after the signal reach +2% above the signal close?

    Same expression the training label used (ml/features.py: future_close / close - 1 >= target), but on
    market sessions: a missing candle on session 5 means NOT EVALUATED, never the stock's next bar."""
    i = session_index(sessions, signal_day)
    if i is None:
        return EndpointOutcome("not_evaluated", None, None, None, "signal day is not a market session")
    c0 = closes.get(signal_day)
    if c0 is None or c0 <= 0:
        return EndpointOutcome("not_evaluated", None, None, None, "no signal close")
    if i + P.HORIZON >= len(sessions):
        return EndpointOutcome("pending", None, None, None, "session 5 has not happened yet")
    day5 = sessions[i + P.HORIZON]
    c5 = closes.get(day5)
    if c5 is None:
        return EndpointOutcome("not_evaluated", None, day5, None, "no candle on session 5")
    forward_return = c5 / c0 - 1
    return EndpointOutcome("evaluated", int(forward_return >= P.LABEL_TARGET), day5, c5)


# ------------------------------------------------------------------ the fixed-rule shadow trade


def charges(turnover: float, side: str, times: float = 1.0) -> float:
    """Frozen charges for one order (the formula of services/costs.compute_charges, with pinned rates)."""
    sell = side.upper() == "SELL"
    rate = P.COSTS["tax_bps_sell"] if sell else P.COSTS["tax_bps_buy"]
    return times * (
        P.COSTS["brokerage_per_order"]
        + turnover * rate / 10_000
        + (P.COSTS["dp_charge_per_sell"] if sell else 0.0)
    )


@dataclass(frozen=True)
class TradeResult:
    status: str  # pending | target | stop | expiry | unresolved
    note: str = ""
    entry_day: date | None = None
    entry_open: float | None = None
    entry_fill: float | None = None
    exit_day: date | None = None
    exit_price: float | None = None
    exit_fill: float | None = None
    sessions_held: int | None = None
    gap_fill: bool = False
    ambiguous: bool = False
    costs_inr: float | None = None
    net_return: float | None = None
    flags: tuple[str, ...] = field(default_factory=tuple)


def simulate_trade(
    bars: dict[date, Bar],
    sessions: Sequence[date],
    signal_day: date,
    signal_close: float,
    group: str,
    stress: bool = False,
) -> TradeResult:
    """+2% target / -4% stop / at most 5 sessions, entered at the open of session 1.

    The entry session is holding session 1; if neither level is hit the trade is sold at the close of
    session 5. Stop is checked first, so a candle touching both is the stop (flagged ambiguous). A gap
    through a level fills at the open. A missing candle in the window leaves the trade UNRESOLVED.
    `stress=True` is the protocol's higher-cost sensitivity: every fill worse by STRESS["extra_slip_bps"] on
    top of the group slippage, and charges multiplied by STRESS["charges_x"]. It runs the same rules."""
    window = sessions_after(sessions, signal_day, P.TRADE_SESSIONS)
    if session_index(sessions, signal_day) is None:
        return TradeResult("unresolved", "signal day is not a market session")
    if not window:
        return TradeResult("pending", "session 1 has not happened yet")
    slip = (P.SLIPPAGE_BPS[group] + (P.STRESS["extra_slip_bps"] if stress else 0.0)) / 10_000
    times = P.STRESS["charges_x"] if stress else 1.0
    first = bars.get(window[0])
    if first is None:
        return TradeResult("unresolved", "no candle on the entry session", flags=("missing_candle",))
    entry_open = first[0]
    entry_fill = entry_open * (1 + slip)
    qty = int(P.NOTIONAL_INR // entry_fill)
    if qty < 1:
        return TradeResult(
            "unresolved", "price above the notional: not even one share", flags=("too_expensive",)
        )
    stop_px, target_px = entry_fill * (1 - P.TRADE_STOP), entry_fill * (1 + P.TRADE_TARGET)

    flags: list[str] = []
    prev_close = signal_close
    exit_price, reason, gap, ambiguous, held, exit_day = None, "", False, False, 0, None
    for k, day in enumerate(window, start=1):
        bar = bars.get(day)
        if bar is None:
            return TradeResult(
                "unresolved", f"no candle on session {k}", entry_day=window[0], flags=("missing_candle",)
            )
        o, h, lo, c = bar
        if prev_close and abs(o / prev_close - 1) > P.BIG_GAP and "possible_corporate_action" not in flags:
            flags.append("possible_corporate_action")
        prev_close = c
        if lo <= stop_px:
            ambiguous = h >= target_px
            gap = o <= stop_px
            exit_price, reason, held, exit_day = (o if gap else stop_px), "stop", k, day
            break
        if h >= target_px:
            gap = o >= target_px
            exit_price, reason, held, exit_day = (o if gap else target_px), "target", k, day
            break
    if exit_price is None:
        if len(window) < P.TRADE_SESSIONS:
            return TradeResult("pending", "session 5 has not happened yet", entry_day=window[0])
        exit_price, reason, held, exit_day = prev_close, "expiry", P.TRADE_SESSIONS, window[-1]
    if ambiguous:
        flags.append("same_candle_both_levels")
    if gap:
        flags.append("gap_fill")

    exit_fill = exit_price * (1 - slip)
    buy_cost = charges(qty * entry_fill, "BUY", times)
    sell_cost = charges(qty * exit_fill, "SELL", times)
    basis = qty * entry_fill + buy_cost
    proceeds = qty * exit_fill - sell_cost
    return TradeResult(
        reason,
        "",
        window[0],
        entry_open,
        entry_fill,
        exit_day,
        exit_price,
        exit_fill,
        held,
        gap,
        ambiguous,
        buy_cost + sell_cost,
        (proceeds - basis) / basis,
        tuple(flags),
    )


# ------------------------------------------------------------------ ranking and selection


def rank_group(scored: Sequence[tuple[str, float]]) -> list[tuple[str, float, int]]:
    """(symbol, score, rank) within ONE group: score descending, ties by symbol ascending. Never mix groups."""
    ordered = sorted(scored, key=lambda t: (-t[1], t[0]))
    return [(sym, score, rank) for rank, (sym, score) in enumerate(ordered, start=1)]


def select_top(ranked: Sequence[tuple[str, float, int]], k: int = P.TOP_K) -> tuple[list[str], int]:
    """The top k symbols and the shortfall (how many of the k places stayed empty)."""
    chosen = [sym for sym, _, rank in ranked if rank <= k]
    return chosen, max(0, k - len(chosen))


def repeat_blocked(selected: dict[date, Sequence[str]], sessions: Sequence[date]) -> set[tuple[date, str]]:
    """Selections that repeat a stock whose previous COUNTED selection is still inside its 5 sessions.

    A stock selected on session j is held through session j+5 at the latest, so it may count again from
    j+5. Blocked selections stay recorded; they just do not count."""
    last: dict[str, int] = {}
    blocked: set[tuple[date, str]] = set()
    for day in sorted(selected):
        i = session_index(sessions, day)
        if i is None:
            continue
        for sym in sorted(selected[day]):
            if sym in last and i - last[sym] < P.TRADE_SESSIONS:
                blocked.add((day, sym))
            else:
                last[sym] = i
    return blocked


# ------------------------------------------------------------------ uncertainty


def block_range(
    values: Sequence[float], block: int = 5, draws: int = 2000, level: float = 0.90, seed: int = 7
) -> tuple[float, float] | None:
    """A (low, high) range for the average of day-ordered `values`, resampling runs of `block` consecutive
    signal days. Overlapping 5-day trades are not independent, so single days would look surer than they are.

    Seeded, so the same series always gives the same range (the report and the simulation in h05_power use
    this one function)."""
    n = len(values)
    if n < max(5, 2 * block):
        return None
    data = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    per_draw = -(-n // block)
    starts = rng.integers(0, n - block + 1, size=(draws, per_draw))
    means = data[starts[:, :, None] + np.arange(block)].reshape(draws, -1).mean(axis=1)
    means.sort()
    tail = (1 - level) / 2
    return float(means[int(tail * draws)]), float(means[min(draws - 1, int((1 - tail) * draws))])


def random_k_distribution(
    pools: Sequence[Sequence[float]], k: int = P.TOP_K, draws: int = 200, seed: int = 7
) -> list[float]:
    """Average result of `draws` random picks of k from each day's pool of outcomes (sorted). The seeded
    yardstick for 'could a random pick have done this?'. Days with an empty pool are skipped."""
    rng = random.Random(seed)
    usable = [list(p) for p in pools if p]
    out = []
    for _ in range(draws):
        picks: list[float] = []
        for pool in usable:
            picks.extend(rng.sample(pool, min(k, len(pool))))
        out.append(fmean(picks) if picks else 0.0)
    return sorted(out)
