# backend/src/swing_trade_ml/brain/portfolio_sim.py
"""Point-in-time portfolio replay: what a real account would have done with the day's picks.

The walk-forward and replay-score tools judge every idea on its own, as if each had unlimited
money. This runs the same picks through one account: limited cash, the position limits of the
capital ladder for the account's size that day, the sector cap, the 15% drawdown halt, and the
market-mode limit. Exits and costs follow the same strict rule as `replay_scoring` (enter at the
next open, +8% / -4%, half out at +5%, 15 trading days, real slippage and charges).

The strategy is not changed here; it is only given a wallet. Read-only evidence: the pure
simulator touches no database, and the runner only registers `wf_*` trial models like walk_forward.
Limits to keep in mind: shares are whole; cap tiers, liquidity ceiling and the regime ceiling
(services/deployable.py) are not applied; the universe is today's watchlist (survivor bias).
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from swing_trade_ml.brain.replay_scoring import HALF_OUT, HORIZON_BARS, STOP, TARGET, _sell
from swing_trade_ml.services.costs import apply_slippage, compute_charges
from swing_trade_ml.services.limits import limits_for

POLICIES = ("halt", "reduce", "liquidate")  # at a 15% fall: stop buying / also sell half / also sell all
MAX_DRAWDOWN = 0.15  # the settled rule; pinned here so a local .env cannot change a result
RISK_PER_TRADE = 0.01
NORMAL_MAX_NEW = 5  # the owner's "top 5 a day"
DEFENSIVE_MAX_NEW = 2  # same as M07
DEFENSIVE_SIZE_FACTOR = 0.5  # same as M07


@dataclass(frozen=True, slots=True)
class Pick:
    day: date  # decision day; the buy happens at the next trading day's open
    symbol: str
    score: float
    bucket: str | None = None  # sector bucket, None = unmapped (treated as its own sector)


@dataclass(slots=True)
class _Position:
    symbol: str
    bucket: str | None
    qty: int
    cost_in: float
    entry_day: date
    stop_px: float
    target_px: float
    half_px: float
    bars_held: int = 0
    half_done: bool = False
    cash_back: float = 0.0
    last_close: float = 0.0
    fill: float = 0.0  # the buy fill per share, slippage included
    exit_reason: str | None = None  # target | stop | timeout | forced, once fully sold
    plan: tuple[date, float, str] | None = None  # (exit day, price, reason) when the exit is scripted


@dataclass(frozen=True, slots=True)
class ClosedTrade:
    symbol: str
    entry_day: date
    exit_day: date
    status: str  # target (+8% reached first) | stop | timeout | forced (the drawdown control sold it)
    net_return: float  # cash back / cash put in - 1, after slippage and charges
    half_out: bool


@dataclass(slots=True)
class PortfolioResult:
    start_equity: float
    end_equity: float
    total_return: float
    max_drawdown: float  # worst peak-to-trough fall of daily closing equity, as a positive fraction
    trades: int
    wins: int
    avg_trade_return: float | None
    avg_invested_share: float  # average share of the account in shares, over the days simulated
    halted_days: int
    still_open: int
    triggers: int = 0  # times the drawdown control fired (halt: days it started; others: forced exits)
    forced_exits: int = 0  # positions sold (fully or by half) because the control fired
    forced_shortfall: float = 0.0  # rupees lost from last close to the forced fill
    longest_underwater_days: int = 0  # longest run of days below the previous equity peak
    skipped: dict[str, int] = field(default_factory=dict)
    curve: list[tuple[date, float]] = field(default_factory=list)
    closed: list[ClosedTrade] = field(default_factory=list)  # every finished trade, in exit order

    def summary(self) -> dict:
        return {
            "start_equity": round(self.start_equity, 2),
            "end_equity": round(self.end_equity, 2),
            "total_return": self.total_return,
            "max_drawdown": self.max_drawdown,
            "trades": self.trades,
            "win_rate": None if not self.trades else self.wins / self.trades,
            "avg_trade_return": self.avg_trade_return,
            "avg_invested_share": self.avg_invested_share,
            "halted_days": self.halted_days,
            "still_open": self.still_open,
            "triggers": self.triggers,
            "forced_exits": self.forced_exits,
            "forced_shortfall": round(self.forced_shortfall, 2),
            "longest_underwater_days": self.longest_underwater_days,
            "skipped": dict(self.skipped),
        }


def _step(pos: _Position, row, horizon: int) -> tuple[bool, float]:
    """Apply one daily bar to a position (same order as `strict_score`).
    Returns (fully sold, cash received today); the cash is the caller's to add."""
    o, h, lo, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
    pos.last_close = c
    pos.bars_held += 1
    got = 0.0
    if lo <= pos.stop_px:  # a bar touching the stop and anything else counts as the stop
        got += _sell(o if o <= pos.stop_px else pos.stop_px, pos.qty)
        pos.qty = 0
        pos.exit_reason = "stop"
    else:
        if not pos.half_done and pos.qty >= 2 and h >= pos.half_px:
            half = pos.qty // 2
            got += _sell(o if o >= pos.half_px else pos.half_px, half)
            pos.qty -= half
            pos.half_done = True
        if h >= pos.target_px:
            got += _sell(o if o >= pos.target_px else pos.target_px, pos.qty)
            pos.qty = 0
            pos.exit_reason = "target"
        elif pos.bars_held >= horizon:
            got += _sell(c, pos.qty)
            pos.qty = 0
            pos.exit_reason = "timeout"
    pos.cash_back += got
    return pos.qty == 0, got


def entry_budget(
    equity: float,
    cash: float,
    limits,
    mode: str,
    sector_used: float,
    *,
    stop: float = STOP,
    risk_per_trade_pct: float = RISK_PER_TRADE,
) -> float:
    """Rupees one new position may take: 1% risk at the stop, capped by the ladder's single-stock limit,
    halved in a DEFENSIVE market, inside the sector cap and the cash reserve."""
    budget = min(limits.max_position_pct, risk_per_trade_pct / stop) * equity
    if mode == "DEFENSIVE":
        budget *= DEFENSIVE_SIZE_FACTOR
    if limits.sector_cap_pct is not None:
        budget = min(budget, limits.sector_cap_pct * equity - sector_used)
    return min(budget, cash - limits.cash_floor_inr)


ExitPlan = Callable[[str, date], tuple[date, float, str] | None]


def _planned_step(pos: _Position, day: date, row) -> tuple[bool, float]:
    """One bar for a position whose exit was worked out beforehand (`exit_plan`): marked at the
    close until its exit day, then sold at the planned price. No plan = held to the end of the data."""
    pos.last_close = float(row["close"])
    pos.bars_held += 1
    if pos.plan is None or day < pos.plan[0]:
        return False, 0.0
    got = _sell(pos.plan[1], pos.qty)
    pos.qty = 0
    pos.exit_reason = pos.plan[2]
    pos.cash_back += got
    return True, got


class Book:
    """One account, stepped one trading day at a time. `simulate` runs it over a whole period; the
    point-in-time brain replay (`pit_replay.py`) steps it between brain runs, so each run sees the
    account exactly as it stood at that day's close. The rules are the ones `simulate` documents."""

    def __init__(
        self,
        bars: dict[str, pd.DataFrame],
        *,
        capital: float,
        horizon: int = HORIZON_BARS,
        target: float = TARGET,
        stop: float = STOP,
        half_out: float = HALF_OUT,
        risk_per_trade_pct: float = RISK_PER_TRADE,
        max_drawdown_pct: float = MAX_DRAWDOWN,
        drawdown_policy: str = "halt",
        cooldown_days: int = 10,
        exit_plan: ExitPlan | None = None,
    ) -> None:
        self.index = {s: df.set_index("day") for s, df in bars.items() if not df.empty}
        self.capital = float(capital)
        self.horizon, self.target, self.stop, self.half_out = horizon, target, stop, half_out
        self.risk_per_trade_pct = risk_per_trade_pct
        self.max_drawdown_pct = max_drawdown_pct
        self.drawdown_policy = drawdown_policy
        self.cooldown_days = cooldown_days
        # Optional scripted exits (fd-protocol-v1): `exit_plan(symbol, decision_day)` gives the exit
        # day, price and reason the per-idea scoring found. None keeps the strict rule of `_step`.
        self.exit_plan = exit_plan
        self.cash = self.peak = self.equity = self.control_peak = float(capital)
        self.open_: list[_Position] = []
        self.closed: list[ClosedTrade] = []
        self.skipped: dict[str, int] = {}
        self.curve: list[tuple[date, float]] = []
        self.invested_share: list[float] = []
        self.halted_days = 0
        self.max_dd = 0.0
        self.cooldown_left = 0
        self.pending: str | None = None
        self.triggers = self.forced_exits = self.underwater = self.longest_underwater = 0
        self.forced_shortfall = 0.0
        self.was_halted = False
        self.last_day: date | None = None

    # --- what the account looks like now (after the last stepped day's close) ---

    def halted_now(self) -> bool:
        """Would the drawdown halt stop a buy at the next open? (the "halt" policy's rule)"""
        if self.drawdown_policy == "halt":
            return self.control_peak > 0 and (self.control_peak - self.equity) / self.control_peak >= (
                self.max_drawdown_pct
            )
        return self.cooldown_left > 0 or self.pending is not None

    def drawdown(self) -> float:
        return (self.peak - self.equity) / self.peak if self.peak else 0.0

    def exposure(self) -> dict[str, float]:
        """Rupees held per sector bucket (an unmapped stock is its own bucket), at the last close."""
        out: dict[str, float] = {}
        for p in self.open_:
            key = p.bucket or p.symbol
            out[key] = out.get(key, 0.0) + p.qty * p.last_close
        return out

    def refusal(
        self, symbol: str, bucket: str | None, price: float | None, mode: str, limits, *, cash: float
    ) -> tuple[str | None, int, float]:
        """Why a buy of `symbol` at `price` (before slippage) would be refused, or (None, qty, fill).
        The checks and their order are the buy rules of `step`."""
        if symbol in {p.symbol for p in self.open_}:
            return "already_held", 0, 0.0
        if len(self.open_) >= limits.max_positions:
            return "no_free_slot", 0, 0.0
        if price is None:
            return "no_price", 0, 0.0
        exposure = self.exposure()
        key = bucket or symbol
        if limits.sector_rule == "one_per_sector" and key in exposure:
            return "sector_cap", 0, 0.0
        fill = apply_slippage(float(price), "BUY")
        budget = entry_budget(
            self.equity,
            cash,
            limits,
            mode,
            exposure.get(key, 0.0),
            stop=self.stop,
            risk_per_trade_pct=self.risk_per_trade_pct,
        )
        qty = math.floor(budget / fill) if fill > 0 else 0
        if qty < 1 or qty * fill < limits.min_position_inr:
            return "too_small_or_no_cash", 0, fill
        brokerage, taxes = compute_charges(fill * qty, "BUY")
        if fill * qty + brokerage + taxes > cash:
            return "too_small_or_no_cash", 0, fill
        return None, qty, fill

    def _skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1

    def _close(self, pos: _Position, day: date, status: str) -> None:
        self.closed.append(
            ClosedTrade(
                pos.symbol, pos.entry_day, day, status, pos.cash_back / pos.cost_in - 1.0, pos.half_done
            )
        )

    # --- one trading day ---

    def step(self, day: date, todays: Sequence[Pick], mode: str = "NORMAL") -> None:
        """Buy `todays` picks (decided at the previous trading day's close, in market mode `mode`) at
        this day's open, then apply this day's bar to every position and record the closing equity."""
        todays = sorted(todays, key=lambda p: (-p.score, p.symbol))
        limits = limits_for(self.equity)
        if self.pending is not None:  # forced exits decided at yesterday's close, filled at today's open
            left: list[_Position] = []
            for pos in self.open_:
                ix = self.index.get(pos.symbol)
                sell_qty = pos.qty if self.pending == "all" else pos.qty // 2
                if ix is None or day not in ix.index or sell_qty < 1:
                    left.append(pos)
                    continue
                o = float(ix.loc[day, "open"])
                got = _sell(o, sell_qty)
                self.forced_shortfall += sell_qty * pos.last_close - got
                self.forced_exits += 1
                self.cash += got
                pos.cash_back += got
                pos.qty -= sell_qty
                pos.last_close = o
                if pos.qty == 0:
                    pos.exit_reason = "forced"
                    self._close(pos, day, "forced")
                else:
                    left.append(pos)
            self.open_ = left
            self.pending = "all" if self.pending == "all" and any(p.qty for p in self.open_) else None
            self.cooldown_left = self.cooldown_days
            self.equity = self.cash + sum(p.qty * p.last_close for p in self.open_)
        if self.drawdown_policy == "halt":
            halted = self.halted_now()
        else:
            halted = self.cooldown_left > 0 or self.pending is not None
            if self.cooldown_left > 0:
                self.cooldown_left -= 1
                if self.cooldown_left == 0:
                    self.control_peak = self.equity  # a fresh start after the cooling-off period
        if halted:
            self.halted_days += 1
        if halted and not self.was_halted:
            self.triggers += 1 if self.drawdown_policy == "halt" else 0
        self.was_halted = halted
        cap_new = (
            0 if mode == "NO_NEW_TRADES" else DEFENSIVE_MAX_NEW if mode == "DEFENSIVE" else NORMAL_MAX_NEW
        )
        bought = 0
        for pick in todays:
            if bought >= cap_new:
                self._skip("market_mode_limit" if mode != "NORMAL" else "top_5_limit")
                continue
            if halted:
                self._skip("drawdown_halt")
                continue
            ix = self.index.get(pick.symbol)
            price = float(ix.loc[day, "open"]) if ix is not None and day in ix.index else None
            why, qty, fill = self.refusal(pick.symbol, pick.bucket, price, mode, limits, cash=self.cash)
            if why is not None:
                self._skip(why)
                continue
            brokerage, taxes = compute_charges(fill * qty, "BUY")
            cost = fill * qty + brokerage + taxes
            self.cash -= cost
            self.open_.append(
                _Position(
                    pick.symbol,
                    pick.bucket,
                    qty,
                    cost,
                    day,
                    fill * (1 - self.stop),
                    fill * (1 + self.target),
                    fill * (1 + self.half_out),
                    last_close=fill,
                    fill=fill,
                    plan=self.exit_plan(pick.symbol, pick.day) if self.exit_plan is not None else None,
                )
            )
            bought += 1

        # 2. today's bar for every position (a new one counts today as bar 1, like strict_score)
        still: list[_Position] = []
        for pos in self.open_:
            ix = self.index.get(pos.symbol)
            if ix is None or day not in ix.index:
                still.append(pos)
                continue
            if self.exit_plan is not None:
                closed, got = _planned_step(pos, day, ix.loc[day])
            else:
                closed, got = _step(pos, ix.loc[day], self.horizon)
            self.cash += got
            if closed:
                self._close(pos, day, pos.exit_reason or "timeout")
            else:
                still.append(pos)
        self.open_ = still

        # 3. close-of-day equity
        shares_value = sum(p.qty * p.last_close for p in self.open_)
        self.equity = self.cash + shares_value
        self.peak = max(self.peak, self.equity)
        self.control_peak = max(self.control_peak, self.equity)
        self.max_dd = max(self.max_dd, (self.peak - self.equity) / self.peak if self.peak else 0.0)
        self.underwater = self.underwater + 1 if self.equity < self.peak else 0
        self.longest_underwater = max(self.longest_underwater, self.underwater)
        if (
            self.drawdown_policy != "halt"
            and self.pending is None
            and self.cooldown_left == 0
            and self.open_
            and self.control_peak > 0
            and (self.control_peak - self.equity) / self.control_peak >= self.max_drawdown_pct
        ):
            self.pending = "all" if self.drawdown_policy == "liquidate" else "half"
            self.triggers += 1
        self.curve.append((day, self.equity))
        self.invested_share.append(shares_value / self.equity if self.equity else 0.0)
        self.last_day = day

    def result(self) -> PortfolioResult:
        """A position still open when the data ends is marked at its last close, not counted as a trade."""
        returns = [t.net_return for t in self.closed]
        return PortfolioResult(
            start_equity=self.capital,
            end_equity=self.equity,
            total_return=self.equity / self.capital - 1.0,
            max_drawdown=self.max_dd,
            trades=len(returns),
            wins=sum(1 for r in returns if r > 0),
            avg_trade_return=sum(returns) / len(returns) if returns else None,
            avg_invested_share=(
                sum(self.invested_share) / len(self.invested_share) if self.invested_share else 0.0
            ),
            halted_days=self.halted_days,
            still_open=len(self.open_),
            triggers=self.triggers,
            forced_exits=self.forced_exits,
            forced_shortfall=self.forced_shortfall,
            longest_underwater_days=self.longest_underwater,
            skipped=self.skipped,
            curve=self.curve,
            closed=list(self.closed),
        )


def simulate(
    picks: Sequence[Pick],
    bars: dict[str, pd.DataFrame],
    days: Sequence[date],
    *,
    capital: float,
    modes: dict[date, str] | None = None,
    horizon: int = HORIZON_BARS,
    target: float = TARGET,
    stop: float = STOP,
    half_out: float = HALF_OUT,
    risk_per_trade_pct: float = RISK_PER_TRADE,
    max_drawdown_pct: float = MAX_DRAWDOWN,
    drawdown_policy: str = "halt",
    cooldown_days: int = 10,
    exit_plan: ExitPlan | None = None,
) -> PortfolioResult:
    """Run `picks` through one account over `days` (every trading day, ascending, covering the
    picks and the time they need to finish). `modes` maps a decision day to NORMAL, DEFENSIVE or
    NO_NEW_TRADES; a missing day is NORMAL.

    `drawdown_policy` is what happens when closing equity is `max_drawdown_pct` below the peak:
    - "halt": no new buys until equity recovers (the current rule); open positions stay open.
    - "liquidate": also sell every open position at the next open, then no buys for `cooldown_days`
      trading days, after which the peak is reset to the account's value that day.
    - "reduce": the same, but sell only half of each open position.
    The trigger is checked on closing equity, so the exit happens a day later and can gap past it.
    `max_drawdown` in the result always uses the true running peak, never a reset one.
    `exit_plan(symbol, decision_day)` optionally scripts each position's exit (day, price, reason)
    instead of the strict +target / -stop / horizon rule; left out, nothing changes."""
    modes = modes or {}
    by_day: dict[date, list[Pick]] = {}
    for p in picks:
        by_day.setdefault(p.day, []).append(p)
    book = Book(
        bars,
        capital=capital,
        horizon=horizon,
        target=target,
        stop=stop,
        half_out=half_out,
        risk_per_trade_pct=risk_per_trade_pct,
        max_drawdown_pct=max_drawdown_pct,
        drawdown_policy=drawdown_policy,
        cooldown_days=cooldown_days,
        exit_plan=exit_plan,
    )
    for i, day in enumerate(days):
        # buys decided on the previous trading day, filled at today's open
        todays = by_day.get(days[i - 1], []) if i else []
        mode = modes.get(days[i - 1], "NORMAL") if i else "NORMAL"
        book.step(day, todays, mode)
    return book.result()


def random_picks(
    pool: dict[date, list[str]], per_day: dict[date, int], scores_seed: int, buckets: dict[str, str | None]
) -> list[Pick]:
    """The same number of picks each day, drawn at random from the stocks that day (seeded)."""
    rng = random.Random(scores_seed)
    out: list[Pick] = []
    for day, k in per_day.items():
        syms = pool.get(day, [])
        for sym in rng.sample(syms, min(k, len(syms))):
            out.append(Pick(day, sym, rng.random(), buckets.get(sym)))
    return out


def random_baseline(
    pool: dict[date, list[str]],
    per_day: dict[date, int],
    bars: dict[str, pd.DataFrame],
    days: Sequence[date],
    buckets: dict[str, str | None],
    *,
    capital: float,
    draws: int = 30,
    seed: int = 11,
    drawdown_policy: str = "halt",
    modes: dict[date, str] | None = None,
) -> dict:
    """Total return and worst fall over `draws` random-pick accounts (same count of picks per day)."""
    rets, dds = [], []
    for n in range(draws):
        r = simulate(
            random_picks(pool, per_day, seed + n, buckets),
            bars,
            days,
            capital=capital,
            modes=modes,
            drawdown_policy=drawdown_policy,
        )
        rets.append(r.total_return)
        dds.append(r.max_drawdown)
    rets.sort()
    dds.sort()

    def at(xs: list[float], q: float) -> float:
        return xs[int(q * (len(xs) - 1))]

    return {
        "draws": draws,
        "return_mean": sum(rets) / len(rets),
        "return_p5": at(rets, 0.05),
        "return_p95": at(rets, 0.95),
        "drawdown_mean": sum(dds) / len(dds),
        "drawdown_p95": at(dds, 0.95),
    }


# --- rules only (layer 2 protocol, section 3): the arm the brain must beat --------------------------------
#
# The same account (cash, ladder limits, sector cap, sizing, market-mode limit, 15% halt, exits, costs),
# but the stocks are drawn at random from the ones the brain's rules left eligible that day, ignoring the
# model's score. If the brain does not beat this, the score adds nothing and what remains is a discipline
# layer. Offline evidence only; nothing here is read by a live run or counts toward the 30-idea gate.

RULES_ONLY_DRAWS = 200  # evidence-defs-v1: 200 seeded runs
RULES_ONLY_MIN_DAYS = 40  # protocol section 5 (proposed, owner to confirm)
RULES_ONLY_MIN_TRADES = 60
EXCLUDED_WORDS = ("AVOID",)  # an idea with this word was ruled out by the brain's rules: not eligible
RULES_ONLY_LIMITS: tuple[str, ...] = (
    "Rules only: the same account rules as the brain, with stocks drawn at random from those the brain "
    "did not call AVOID that day. WATCH and WAIT ideas are eligible, though some of those words come "
    "partly from the model's score, so the pool is not fully free of the model.",
    "Rules only buys as many stocks a day as the brain did (matched count), so it tests which stocks "
    "were picked, not how many.",
)


def rules_only_picks(
    eligible: dict[date, Sequence[str]],
    *,
    seed: int,
    buckets: dict[str, str | None],
    per_day: dict[date, int] | None = None,
) -> list[Pick]:
    """Random picks from each day's eligible stocks (seeded). With `per_day`, exactly that many a day (or
    all of them, when fewer are eligible); without it, every eligible stock in a random order, and the
    account takes the first ones it can, up to the day's market-mode limit. The score is only the order."""
    rng = random.Random(seed)
    out: list[Pick] = []
    for day in sorted(eligible):
        syms = sorted(set(eligible[day]))
        k = len(syms) if per_day is None else min(per_day.get(day, 0), len(syms))
        chosen = rng.sample(syms, k)
        out += [Pick(day, sym, float(k - n), buckets.get(sym)) for n, sym in enumerate(chosen)]
    return out


def _spread(values: list[float]) -> dict:
    xs = sorted(values)
    if not xs:
        return {"median": None, "p5": None, "p95": None, "mean": None}

    def at(q: float) -> float:
        return xs[int(q * (len(xs) - 1))]

    mid = len(xs) // 2
    median = xs[mid] if len(xs) % 2 else (xs[mid - 1] + xs[mid]) / 2
    return {"median": median, "p5": at(0.05), "p95": at(0.95), "mean": sum(xs) / len(xs)}


def rules_only_baseline(
    eligible: dict[date, Sequence[str]],
    bars: dict[str, pd.DataFrame],
    days: Sequence[date],
    buckets: dict[str, str | None],
    *,
    capital: float,
    per_day: dict[date, int] | None = None,
    modes: dict[date, str] | None = None,
    draws: int = RULES_ONLY_DRAWS,
    seed: int = 11,
    drawdown_policy: str = "halt",
) -> dict:
    """`draws` rules-only accounts (seeds seed..seed+draws-1) through `simulate`, and the spread of their
    results. Average per trade is what protocol section 5 compares; draws with no finished trade have
    none and are counted apart."""
    results = [
        simulate(
            rules_only_picks(eligible, seed=seed + n, buckets=buckets, per_day=per_day),
            bars,
            days,
            capital=capital,
            modes=modes,
            drawdown_policy=drawdown_policy,
        )
        for n in range(draws)
    ]
    per_trade = sorted(r.avg_trade_return for r in results if r.avg_trade_return is not None)
    return {
        "draws": draws,
        "seeds": f"{seed}..{seed + draws - 1}",
        "matched_count": per_day is not None,
        "total_return": _spread([r.total_return for r in results]),
        "avg_trade_return": {**_spread(per_trade), "draws_with_trades": len(per_trade), "values": per_trade},
        "max_drawdown": _spread([r.max_drawdown for r in results]),
        "trades": _spread([float(r.trades) for r in results]),
    }


def beats_rules_only(
    brain: dict,
    rules: dict,
    *,
    trading_days: int,
    min_days: int = RULES_ONLY_MIN_DAYS,
    min_trades: int = RULES_ONLY_MIN_TRADES,
) -> dict:
    """Protocol section 5, "beats rules only": the brain's average per trade (after costs) is above the
    middle of the rules-only draws, and the draws' 5th percentile is below the brain. Fewer than
    `min_days` decision days or `min_trades` finished brain trades reads "insufficient", never "fail".
    `brain` is a `PortfolioResult.summary()`; `rules` is `rules_only_baseline`'s result."""
    avg, trades = brain.get("avg_trade_return"), int(brain.get("trades") or 0)
    dist = rules["avg_trade_return"]
    values = dist.get("values") or []
    out = {
        "brain_avg_trade_return": avg,
        "brain_trades": trades,
        "trading_days": trading_days,
        "rules_median": dist["median"],
        "rules_p5": dist["p5"],
        "rules_draws_with_trades": dist["draws_with_trades"],
        # share of rules-only draws the brain's average per trade is above (shown, not part of the rule)
        "brain_beats_share": (
            sum(1 for v in values if v < avg) / len(values) if values and avg is not None else None
        ),
    }
    if trading_days < min_days:
        why = f"{trading_days} decision days; at least {min_days} are needed."
    elif trades < min_trades:
        why = f"{trades} finished brain trades; at least {min_trades} are needed."
    elif avg is None or dist["median"] is None:
        why = "No rules-only draw finished a trade, so there is nothing to compare with."
    else:
        why = None
    if why is not None:
        return {**out, "word": "insufficient", "why": why}
    passed = avg > dist["median"] and dist["p5"] < avg
    return {**out, "word": "pass" if passed else "fail", "why": None}


def compare_with_rules_only(
    brain_picks: Sequence[Pick],
    eligible: dict[date, Sequence[str]],
    bars: dict[str, pd.DataFrame],
    days: Sequence[date],
    buckets: dict[str, str | None],
    *,
    capital: float,
    modes: dict[date, str] | None = None,
    draws: int = RULES_ONLY_DRAWS,
    seed: int = 11,
    matched: bool = True,
    drawdown_policy: str = "halt",
) -> dict:
    """The brain's picks and the rules-only draws through the same account, side by side, with the
    section 5 answer. `matched` draws as many stocks a day as the brain picked (0 on days it picked
    none); otherwise rules only fills up to the market-mode limit. Pure: no database."""
    brain = simulate(
        brain_picks, bars, days, capital=capital, modes=modes, drawdown_policy=drawdown_policy
    ).summary()
    per_day: dict[date, int] | None = None
    if matched:
        per_day = dict.fromkeys(eligible, 0)
        for p in brain_picks:
            per_day[p.day] = per_day.get(p.day, 0) + 1
    rules = rules_only_baseline(
        eligible,
        bars,
        days,
        buckets,
        capital=capital,
        per_day=per_day,
        modes=modes,
        draws=draws,
        seed=seed,
        drawdown_policy=drawdown_policy,
    )
    limits = list(RULES_ONLY_LIMITS)
    if not matched:
        limits[1] = "Rules only fills up to the market-mode limit each day (not the brain's count)."
    return {
        "capital": capital,
        "decision_days": len(eligible),
        "brain": brain,
        "rules_only": rules,
        "verdict": beats_rules_only(brain, rules, trading_days=len(eligible)),
        "limits": limits,
    }


def rules_only_inputs(db, start: date, end: date, *, replays: bool = False) -> dict:
    """From stored nightly brain runs (one per IST day, `trial_journal.load_sessions`): the brain's TRADE
    picks, each day's eligible stocks (every idea not in `EXCLUDED_WORDS`), the brain's count a day and
    the banner. Refuses any window that touches the sealed blind trial (services/trial_seal.py)."""
    from swing_trade_ml.brain.trial_journal import load_sessions
    from swing_trade_ml.ml.sector_map import get_sector_bucket
    from swing_trade_ml.services import trial_seal

    if trial_seal.touches_seal(start, end):
        raise ValueError(
            f"{start}..{end} includes sealed trial days (from {trial_seal.SEALED_FROM}); "
            "a rules-only comparison would reveal the trial's results."
        )
    sessions = load_sessions(db, start, end, live=not replays)
    picks: list[Pick] = []
    eligible: dict[date, list[str]] = {}
    per_day: dict[date, int] = {}
    banners: dict[date, str | None] = {}
    for s in sessions:
        trade = sorted((i for i in s.ideas if i.word == "TRADE"), key=lambda i: i.symbol)
        picks += [Pick(s.day, i.symbol, i.score or 0.0, get_sector_bucket(i.symbol)) for i in trade]
        eligible[s.day] = sorted({i.symbol for i in s.ideas if i.word not in EXCLUDED_WORDS})
        per_day[s.day] = len(trade)
        banners[s.day] = s.banner
    return {"picks": picks, "eligible": eligible, "per_day": per_day, "banners": banners}


def run_rules_only_comparison(
    db,
    *,
    start: date,
    end: date,
    capitals: Sequence[float],
    draws: int = RULES_ONLY_DRAWS,
    replays: bool = False,
    derive_modes: bool = True,
) -> dict:
    """Stored brain runs from `start` to `end` (not the sealed trial) against rules only, one account per
    starting capital. Market mode per decision day: the recorded banner, else the point-in-time M10 mode
    (`market_mode_history.history_for`), else NORMAL, and the result says how many of each."""
    from datetime import timedelta

    from swing_trade_ml.brain.market_mode_history import (
        DERIVED_LIMITS,
        history_for,
        modes_only,
        source_counts,
    )
    from swing_trade_ml.brain.replay_score import load_bars
    from swing_trade_ml.ml.sector_map import get_sector_bucket

    inp = rules_only_inputs(db, start, end, replays=replays)
    decision_days = sorted(inp["eligible"])
    symbols = sorted(
        {s for syms in inp["eligible"].values() for s in syms} | {p.symbol for p in inp["picks"]}
    )
    bars = {s: df for s, df in load_bars(db, symbols, end + timedelta(days=60)).items() if len(df)}
    buckets = {s: get_sector_bucket(s) for s in bars}
    days = sorted({d for df in bars.values() for d in df["day"] if d >= start})
    history = history_for(db, decision_days, derive=derive_modes)
    counts = source_counts(history, decision_days)
    modes = modes_only(history)
    accounts = [
        compare_with_rules_only(
            inp["picks"], inp["eligible"], bars, days, buckets, capital=capital, modes=modes, draws=draws
        )
        for capital in capitals
    ]
    limits = [*RULES_ONLY_LIMITS, *(DERIVED_LIMITS if counts["derived"] else ())]
    if counts["missing"]:
        limits.append(f"{counts['missing']} decision days had no market mode and were treated as NORMAL.")
    limits.append(LIMITS[0])
    limits.append(LIMITS[4])
    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "source": "replay" if replays else "live",
        "decision_days": len(decision_days),
        "brain_picks": len(inp["picks"]),
        "stocks": len(bars),
        "mode_days": counts,
        "accounts": [{k: v for k, v in a.items() if k != "limits"} for a in accounts],
        "limits": limits,
    }


def rules_only_report(result: dict) -> str:
    def pct(x):
        return "n/a" if x is None else f"{x * 100:+.2f}%"

    m = result["mode_days"]
    lines = [
        f"Brain against rules only, {result['from']} to {result['to']} ({result['source']} runs): "
        f"{result['decision_days']} decision days, {result['brain_picks']} brain TRADE picks, "
        f"{result['stocks']} stocks. Market mode: {m['recorded']} recorded, {m['derived']} derived, "
        f"{m['missing']} missing.",
        "",
        "| Start money | Brain: per trade | Brain trades | Rules only: per trade, middle (5th-95th) "
        "| Brain above | Answer |",
        "|---|---|---|---|---|---|",
    ]
    for a in result["accounts"]:
        v, r = a["verdict"], a["rules_only"]["avg_trade_return"]
        share = "n/a" if v["brain_beats_share"] is None else f"{v['brain_beats_share']:.0%} of draws"
        answer = v["word"] + (f" ({v['why']})" if v["why"] else "")
        lines.append(
            f"| ₹{a['capital']:,.0f} | {pct(v['brain_avg_trade_return'])} | {v['brain_trades']} "
            f"| {pct(r['median'])} ({pct(r['p5'])} to {pct(r['p95'])}) | {share} | {answer} |"
        )
    lines += ["", "Limits:"] + [f"- {t}" for t in result["limits"]]
    return "\n".join(lines)


def run_portfolio_walk_forward(
    db,
    *,
    first_start: date,
    last_end: date,
    capitals: Sequence[float],
    test_days: int = 28,
    top_k: int = NORMAL_MAX_NEW,
    train_fn=None,
    score_fn=None,
    draws: int = 30,
) -> dict:
    """Walk-forward picks (a new model per window, as in walk_forward.py) run through one account
    per starting capital, next to random picks (same count a day) through the same account."""
    from sqlalchemy import select

    from swing_trade_ml.brain.horizon_grid import top_k_by_day
    from swing_trade_ml.brain.replay_score import load_bars
    from swing_trade_ml.brain.walk_forward import _train, make_folds
    from swing_trade_ml.db.models.market import Instrument
    from swing_trade_ml.ml.sector_map import get_sector_bucket

    if train_fn is None:
        train_fn = _train
    if score_fn is None:
        from swing_trade_ml.ml.asof import score_series as score_fn
    folds = make_folds(first_start, last_end, test_days)
    if not folds:
        raise ValueError("No test window fits between the start and end dates.")
    from datetime import timedelta

    instruments = list(
        db.execute(
            select(Instrument).where(Instrument.is_active.is_(True), Instrument.is_watchlisted.is_(True))
        ).scalars()
    )
    bars = {
        s: df
        for s, df in load_bars(
            db, [i.tradingsymbol for i in instruments], last_end + timedelta(days=60)
        ).items()
        if len(df)
    }
    buckets = {s: get_sector_bucket(s) for s in bars}
    days = sorted({d for df in bars.values() for d in df["day"] if d >= first_start})
    picks: list[Pick] = []
    pool: dict[date, list[str]] = {}
    per_day: dict[date, int] = {}
    for fold in folds:
        fold_days = [d for d in days if fold.start <= d <= fold.end]
        model = train_fn(db, fold.cutoff, HORIZON_BARS, TARGET, STOP)
        scores = {
            i.tradingsymbol: {
                d: p for d, p in score_fn(db, i, model, fold.cutoff).items() if fold.start <= d <= fold.end
            }
            for i in instruments
        }
        top = top_k_by_day(scores, fold_days, top_k)
        for d in fold_days:
            pool[d] = [s for s, sc in scores.items() if d in sc]
            per_day[d] = len(top.get(d, []))
            for sym in top.get(d, []):
                picks.append(Pick(d, sym, scores[sym][d], buckets.get(sym)))
    # leave room after the last pick for it to finish; the data is cut at last_end + 60 days
    from swing_trade_ml.brain.market_mode_history import coverage, mode_history

    scored_days = sorted(per_day)
    modes = mode_history(db)
    have, total = coverage(modes, scored_days)
    out = []
    for capital in capitals:
        for policy in POLICIES:
            res = simulate(picks, bars, days, capital=capital, modes=modes, drawdown_policy=policy)
            base = random_baseline(
                pool,
                per_day,
                bars,
                days,
                buckets,
                capital=capital,
                draws=draws,
                drawdown_policy=policy,
                modes=modes,
            )
            out.append({"capital": capital, "policy": policy, "model": res.summary(), "random": base})
    return {
        "from": first_start.isoformat(),
        "to": last_end.isoformat(),
        "folds": len(folds),
        "stocks": len(bars),
        "picks": len(picks),
        "accounts": out,
        "mode_days": {"recorded": have, "scored": total},
        "limits": limits_for_coverage(have, total),
    }


LIMITS: tuple[str, ...] = (
    "Whole shares; cap tiers, liquidity ceiling and the regime ceiling are not applied.",
    "No market-mode history exists for these days, so every day is NORMAL (top 5 a day, full size). "
    "This is NOT the brain's real behaviour and the effect on the results is unknown: DEFENSIVE days "
    "would have bought fewer and smaller positions, which changes both losses and gains. Do not read "
    "this replay as conservative.",
    "The drawdown control checks closing equity and sells at the next open, so a gap can carry the loss "
    "past 15%. It is a trigger, not a guaranteed ceiling.",
    "'Reduce' and 'sell all' wait 10 trading days after firing, then take the account's value that day "
    "as the new peak; the worst fall shown always uses the true running peak.",
    "Universe is today's watchlist (survivor bias). Daily candles: a bar touching both stop and target "
    "counts as the stop.",
    "Sizing is 1% risk at a 4% stop, capped by the capital ladder (about 25% of the account at most).",
)


MODE_LIMIT = (
    "Market mode comes from the banner the brain recorded on {have} of the {total} scored days. {rest}"
)


def limits_for_coverage(have: int, total: int) -> list[str]:
    """The limits list, with the market-mode line matching how many days had a recorded mode."""
    if have == 0:
        return list(LIMITS)
    rest = (
        "Every day had a recorded mode."
        if have == total
        else "The other days were treated as NORMAL (top 5 a day, full size), which is not the brain's "
        "real behaviour and the effect on the results is unknown."
    )
    mode_line = MODE_LIMIT.format(have=have, total=total, rest=rest)
    return [mode_line if "No market-mode history" in t else t for t in LIMITS]


def plain_report(result: dict) -> str:
    def pct(x):
        return "n/a" if x is None else f"{x * 100:+.1f}%"

    names = {"halt": "Stop buying only", "reduce": "Stop + sell half", "liquidate": "Stop + sell all"}
    lines = [
        f"Portfolio replay {result['from']} to {result['to']}: {result['folds']} windows, "
        f"{result['stocks']} stocks, {result['picks']} daily picks (top 5 a day).",
        "",
        "| Start money | At a 15% fall | Model: end result | Worst fall | Trades | Times fired "
        "| Forced sells (cost) | Longest below peak | Random picks: end (5th-95th) | Random worst fall |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for a in result["accounts"]:
        m, r = a["model"], a["random"]
        lines.append(
            f"| ₹{a['capital']:,.0f} | {names[a['policy']]} | {pct(m['total_return'])} "
            f"| {pct(-m['max_drawdown'])} | {m['trades']} | {m['triggers']} "
            f"| {m['forced_exits']} (₹{m['forced_shortfall']:,.0f}) | {m['longest_underwater_days']} days "
            f"| {pct(r['return_mean'])} ({pct(r['return_p5'])} to {pct(r['return_p95'])}) "
            f"| {pct(-r['drawdown_mean'])} |"
        )
    lines += ["", "Why picks were not bought (first account, stop buying only): "]
    lines.append(str(result["accounts"][0]["model"]["skipped"]))
    lines += ["", "Limits:"] + [f"- {t}" for t in result["limits"]]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    import argparse
    import json
    from datetime import UTC, datetime
    from pathlib import Path

    from swing_trade_ml.brain.walk_forward import latest_scoreable_end
    from swing_trade_ml.core.market_session import last_closed_trading_day
    from swing_trade_ml.db.session import SessionLocal

    p = argparse.ArgumentParser(description="Portfolio replay of the walk-forward picks (read-only evidence)")
    p.add_argument("--from", dest="start", required=True)
    p.add_argument("--to", dest="end", default=None)
    p.add_argument("--capital", type=float, nargs="+", default=[100_000, 500_000, 1_000_000])
    p.add_argument("--out", default="docs/brain/evidence")
    p.add_argument(
        "--rules-only",
        action="store_true",
        help="compare stored brain runs with rules only (layer 2 protocol section 3) instead",
    )
    p.add_argument(
        "--replays", action="store_true", help="with --rules-only: read replayed runs, not live ones"
    )
    p.add_argument("--draws", type=int, default=RULES_ONLY_DRAWS)
    a = p.parse_args(argv)
    if a.rules_only:
        if not a.end:
            p.error("--rules-only needs --to (a window that ends before the sealed trial)")
        with SessionLocal() as db:
            result = run_rules_only_comparison(
                db,
                start=date.fromisoformat(a.start),
                end=date.fromisoformat(a.end),
                capitals=a.capital,
                draws=a.draws,
                replays=a.replays,
            )
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        stem = f"rules_only_{result['source']}_{result['from']}_{result['to']}"
        (out / f"{stem}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        text = rules_only_report(result)
        (out / f"{stem}.md").write_text("# Brain against rules only\n\n" + text + "\n", encoding="utf-8")
        print(text)
        return 0
    end = (
        date.fromisoformat(a.end)
        if a.end
        else latest_scoreable_end(last_closed_trading_day(datetime.now(UTC)))
    )
    with SessionLocal() as db:
        result = run_portfolio_walk_forward(
            db, first_start=date.fromisoformat(a.start), last_end=end, capitals=a.capital
        )
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"portfolio_replay_{result['from']}_{result['to']}"
    (out / f"{stem}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    text = plain_report(result)
    (out / f"{stem}.md").write_text("# Portfolio replay\n\n" + text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
