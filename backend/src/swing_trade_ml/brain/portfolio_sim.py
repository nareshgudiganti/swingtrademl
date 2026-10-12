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
from collections.abc import Sequence
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
    else:
        if not pos.half_done and pos.qty >= 2 and h >= pos.half_px:
            half = pos.qty // 2
            got += _sell(o if o >= pos.half_px else pos.half_px, half)
            pos.qty -= half
            pos.half_done = True
        if h >= pos.target_px:
            got += _sell(o if o >= pos.target_px else pos.target_px, pos.qty)
            pos.qty = 0
        elif pos.bars_held >= horizon:
            got += _sell(c, pos.qty)
            pos.qty = 0
    pos.cash_back += got
    return pos.qty == 0, got


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
    `max_drawdown` in the result always uses the true running peak, never a reset one."""
    modes = modes or {}
    by_day: dict[date, list[Pick]] = {}
    for p in picks:
        by_day.setdefault(p.day, []).append(p)
    index = {s: df.set_index("day") for s, df in bars.items() if not df.empty}

    cash, peak = float(capital), float(capital)
    open_: list[_Position] = []
    closed_returns: list[float] = []
    skipped: dict[str, int] = {}
    curve: list[tuple[date, float]] = []
    invested_share: list[float] = []
    halted_days, max_dd = 0, 0.0
    control_peak, cooldown_left, pending = float(capital), 0, None
    triggers = forced_exits = underwater = longest_underwater = 0
    forced_shortfall = 0.0
    was_halted = False

    def skip(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    equity = float(capital)
    for i, day in enumerate(days):
        # 1. buys decided on the previous trading day, filled at today's open
        todays = sorted(by_day.get(days[i - 1], []), key=lambda p: (-p.score, p.symbol)) if i else []
        mode = modes.get(days[i - 1], "NORMAL") if i else "NORMAL"
        limits = limits_for(equity)
        if pending is not None:  # forced exits decided at yesterday's close, filled at today's open
            left: list[_Position] = []
            for pos in open_:
                ix = index.get(pos.symbol)
                sell_qty = pos.qty if pending == "all" else pos.qty // 2
                if ix is None or day not in ix.index or sell_qty < 1:
                    left.append(pos)
                    continue
                o = float(ix.loc[day, "open"])
                got = _sell(o, sell_qty)
                forced_shortfall += sell_qty * pos.last_close - got
                forced_exits += 1
                cash += got
                pos.cash_back += got
                pos.qty -= sell_qty
                pos.last_close = o
                if pos.qty == 0:
                    closed_returns.append(pos.cash_back / pos.cost_in - 1.0)
                else:
                    left.append(pos)
            open_ = left
            pending = "all" if pending == "all" and any(p.qty for p in open_) else None
            cooldown_left = cooldown_days
            equity = cash + sum(p.qty * p.last_close for p in open_)
        if drawdown_policy == "halt":
            halted = control_peak > 0 and (control_peak - equity) / control_peak >= max_drawdown_pct
        else:
            halted = cooldown_left > 0 or pending is not None
            if cooldown_left > 0:
                cooldown_left -= 1
                if cooldown_left == 0:
                    control_peak = equity  # a fresh start after the cooling-off period
        if halted:
            halted_days += 1
        if halted and not was_halted:
            triggers += 1 if drawdown_policy == "halt" else 0
        was_halted = halted
        cap_new = (
            0 if mode == "NO_NEW_TRADES" else DEFENSIVE_MAX_NEW if mode == "DEFENSIVE" else NORMAL_MAX_NEW
        )
        bought = 0
        held = {p.symbol for p in open_}
        for pick in todays:
            if bought >= cap_new:
                skip("market_mode_limit" if mode != "NORMAL" else "top_5_limit")
                continue
            if halted:
                skip("drawdown_halt")
                continue
            if pick.symbol in held:
                skip("already_held")
                continue
            if len(open_) >= limits.max_positions:
                skip("no_free_slot")
                continue
            ix = index.get(pick.symbol)
            if ix is None or day not in ix.index:
                skip("no_price")
                continue
            exposure = {}
            for p in open_:
                key = p.bucket or p.symbol
                exposure[key] = exposure.get(key, 0.0) + p.qty * p.last_close
            key = pick.bucket or pick.symbol
            if limits.sector_rule == "one_per_sector" and key in exposure:
                skip("sector_cap")
                continue
            fill = apply_slippage(float(ix.loc[day, "open"]), "BUY")
            risk_pct = risk_per_trade_pct
            budget = min(limits.max_position_pct, risk_pct / stop) * equity
            if mode == "DEFENSIVE":
                budget *= DEFENSIVE_SIZE_FACTOR
            if limits.sector_cap_pct is not None:
                budget = min(budget, limits.sector_cap_pct * equity - exposure.get(key, 0.0))
            budget = min(budget, cash - limits.cash_floor_inr)
            qty = math.floor(budget / fill) if fill > 0 else 0
            if qty < 1 or qty * fill < limits.min_position_inr:
                skip("too_small_or_no_cash")
                continue
            brokerage, taxes = compute_charges(fill * qty, "BUY")
            cost = fill * qty + brokerage + taxes
            if cost > cash:
                skip("too_small_or_no_cash")
                continue
            cash -= cost
            open_.append(
                _Position(
                    pick.symbol, pick.bucket, qty, cost, day,
                    fill * (1 - stop), fill * (1 + target), fill * (1 + half_out), last_close=fill,
                )
            )
            held.add(pick.symbol)
            bought += 1

        # 2. today's bar for every position (a new one counts today as bar 1, like strict_score)
        still: list[_Position] = []
        for pos in open_:
            ix = index.get(pos.symbol)
            if ix is None or day not in ix.index:
                still.append(pos)
                continue
            closed, got = _step(pos, ix.loc[day], horizon)
            cash += got
            if closed:
                closed_returns.append(pos.cash_back / pos.cost_in - 1.0)
            else:
                still.append(pos)
        open_ = still

        # 3. close-of-day equity
        shares_value = sum(p.qty * p.last_close for p in open_)
        equity = cash + shares_value
        peak = max(peak, equity)
        control_peak = max(control_peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak if peak else 0.0)
        underwater = underwater + 1 if equity < peak else 0
        longest_underwater = max(longest_underwater, underwater)
        if (
            drawdown_policy != "halt"
            and pending is None
            and cooldown_left == 0
            and open_
            and control_peak > 0
            and (control_peak - equity) / control_peak >= max_drawdown_pct
        ):
            pending = "all" if drawdown_policy == "liquidate" else "half"
            triggers += 1
        curve.append((day, equity))
        invested_share.append(shares_value / equity if equity else 0.0)

    # a position still open when the data ends is marked at its last close, not counted as a trade
    return PortfolioResult(
        start_equity=float(capital),
        end_equity=equity,
        total_return=equity / capital - 1.0,
        max_drawdown=max_dd,
        trades=len(closed_returns),
        wins=sum(1 for r in closed_returns if r > 0),
        avg_trade_return=sum(closed_returns) / len(closed_returns) if closed_returns else None,
        avg_invested_share=sum(invested_share) / len(invested_share) if invested_share else 0.0,
        halted_days=halted_days,
        still_open=len(open_),
        triggers=triggers,
        forced_exits=forced_exits,
        forced_shortfall=forced_shortfall,
        longest_underwater_days=longest_underwater,
        skipped=skipped,
        curve=curve,
    )


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
) -> dict:
    """Total return and worst fall over `draws` random-pick accounts (same count of picks per day)."""
    rets, dds = [], []
    for n in range(draws):
        r = simulate(
            random_picks(pool, per_day, seed + n, buckets),
            bars,
            days,
            capital=capital,
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
    out = []
    for capital in capitals:
        for policy in POLICIES:
            res = simulate(picks, bars, days, capital=capital, drawdown_policy=policy)
            base = random_baseline(
                pool, per_day, bars, days, buckets, capital=capital, draws=draws, drawdown_policy=policy
            )
            out.append({"capital": capital, "policy": policy, "model": res.summary(), "random": base})
    return {
        "from": first_start.isoformat(),
        "to": last_end.isoformat(),
        "folds": len(folds),
        "stocks": len(bars),
        "picks": len(picks),
        "accounts": out,
        "limits": list(LIMITS),
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
    a = p.parse_args(argv)
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
