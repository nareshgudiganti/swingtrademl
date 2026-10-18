"""Baselines, exactly as `evidence-defs-v1` defines them (evidence plan section 3a, locked as tag
evidence-defs-v1). Pure: no database.

Two levels, both always reported, neither replacing the other:

1. Trade level (matched): the candidate's ideas against every stock, random 5, momentum 5 and NIFTY on the
   candidate's own days, with the same next-open entry, exit rule and costs (`replay_scoring.strict_score`).
   NIFTY here follows each idea's own exit day, so it is a comparison, never an index strategy.
2. Portfolio level (equal capital, independently executable): the candidate, random 5 and momentum 5 each
   run through the same account replay (`brain/portfolio_sim.simulate`: ladder limits, sector cap, 15% halt,
   costs), next to NIFTY bought and held and cash. Random 5 and momentum 5 trade every day of the period,
   not only the candidate's days, so they do not depend on the candidate.

The Observatory's Outcomes page (Phase 1A, `outcomes.py`) shows the trade level only; the monthly evidence
pack (`pack.py`, evidence plan A5) shows both.
"""

from __future__ import annotations

import random
import statistics
from collections.abc import Sequence
from datetime import date

import pandas as pd

from swing_trade_ml.brain.portfolio_sim import Pick, PortfolioResult, simulate
from swing_trade_ml.brain.replay_scoring import HORIZON_BARS, POSITION_INR, STOP, TARGET, StrictOutcome
from swing_trade_ml.brain.walk_forward import bootstrap_low, daily_edge, momentum_scores, outcomes_for
from swing_trade_ml.services.brain_observatory import defs
from swing_trade_ml.services.costs import apply_slippage, compute_charges

Picks = dict[date, list[str]]

NIFTY_MATCHED_NOTE = (
    "Trade-level comparison only: each NIFTY holding ends on the matching idea's exit day, which nobody "
    "could know in advance, so this is not an index strategy anyone could run."
)
NIFTY_HOLD_NOTE = (
    "Whole capital in NIFTY 50 from the first day's open to the last day's close, one round trip of the "
    "stock delivery cost model (an index fund's real costs are a little lower)."
)


def summarise(outs: Sequence[StrictOutcome | None]) -> dict:
    """Picked, finished, still open, no price data, average net result and hit rate of finished ideas."""
    finished = [o for o in outs if o is not None and o.net_return is not None]
    still_open = sum(1 for o in outs if o is not None and o.net_return is None)
    nets = [o.net_return for o in finished]
    return {
        "picked": len(outs),
        "finished": len(finished),
        "open": still_open,
        "no_data": len(outs) - len(finished) - still_open,
        "avg_net": sum(nets) / len(nets) if nets else None,
        "hit_rate": sum(1 for o in finished if o.status == "target") / len(finished) if finished else None,
    }


def momentum_picks(bars: dict[str, pd.DataFrame], pool: Picks, days: Sequence[date]) -> Picks:
    """Each day, the `TOP_N` stocks of that day's pool with the highest 20-day return at the close."""
    scores = momentum_scores(bars, days)
    out: Picks = {}
    for d in days:
        ranked = sorted(
            (s for s in pool.get(d, []) if d in scores.get(s, {})), key=lambda s: (-scores[s][d], s)
        )
        out[d] = ranked[: defs.TOP_N]
    return out


def _random_day_picks(rng: random.Random, pool: Picks, days: Sequence[date]) -> Picks:
    return {d: rng.sample(sorted(pool.get(d, [])), min(defs.TOP_N, len(pool.get(d, [])))) for d in days}


def index_matched_return(index_bars: pd.DataFrame, decision_day: date, exit_day: date) -> float | None:
    """NIFTY from the open after `decision_day` to the close of `exit_day` (or the last index bar before
    it), with the same slippage and charges as one stock trade of `POSITION_INR`."""
    after = index_bars[index_bars["day"] > decision_day]
    held = after[after["day"] <= exit_day]
    if held.empty:
        return None
    fill = apply_slippage(float(held.iloc[0]["open"]), "BUY")
    qty = POSITION_INR / fill
    brokerage, taxes = compute_charges(fill * qty, "BUY")
    cash_in = fill * qty + brokerage + taxes
    gross = apply_slippage(float(held.iloc[-1]["close"]), "SELL") * qty
    brokerage, taxes = compute_charges(gross, "SELL")
    return (gross - brokerage - taxes) / cash_in - 1.0


def trade_level(
    candidate: Picks,
    pool: Picks,
    bars: dict[str, pd.DataFrame],
    index_bars: pd.DataFrame | None = None,
    *,
    draws: int = defs.TRADE_RANDOM_DRAWS,
    seed: int = defs.RANDOM_SEED,
) -> dict:
    """The candidate's ideas against the matched baselines, on the days the candidate picked anything.

    `pool` is the stocks available each day (the same list the candidate chose from)."""
    days = sorted(d for d, syms in candidate.items() if syms)
    every = {d: sorted(pool.get(d, [])) for d in days}
    outcomes = outcomes_for(bars, sorted(set(pool) | set(days)), HORIZON_BARS, TARGET, STOP)

    def outs(picks: Picks) -> list[StrictOutcome | None]:
        return [outcomes.get((s, d)) for d in days for s in picks.get(d, [])]

    cand = summarise(outs(candidate))

    rng = random.Random(seed)
    random_avgs = []
    for _ in range(draws if days else 0):
        avg = summarise(outs(_random_day_picks(rng, pool, days)))["avg_net"]
        if avg is not None:
            random_avgs.append(avg)
    random_avgs.sort()
    random_row: dict = {
        "draws": len(random_avgs),
        "avg_net_mean": None,
        "p5": None,
        "p95": None,
        "beaten_share": None,
    }
    if random_avgs:
        random_row.update(
            avg_net_mean=sum(random_avgs) / len(random_avgs),
            p5=random_avgs[int(0.05 * (len(random_avgs) - 1))],
            p95=random_avgs[int(0.95 * (len(random_avgs) - 1))],
            beaten_share=(
                None
                if cand["avg_net"] is None
                else sum(1 for a in random_avgs if cand["avg_net"] > a) / len(random_avgs)
            ),
        )

    nifty: dict = {"finished": 0, "avg_net": None, "note": NIFTY_MATCHED_NOTE}
    if index_bars is not None and not index_bars.empty:
        rets = []
        for d in days:
            for s in candidate[d]:
                o = outcomes.get((s, d))
                if o is not None and o.net_return is not None and o.exit_day is not None:
                    r = index_matched_return(index_bars, d, o.exit_day)
                    if r is not None:
                        rets.append(r)
        nifty.update(finished=len(rets), avg_net=sum(rets) / len(rets) if rets else None)

    edge = daily_edge({d: candidate[d] for d in days}, every, outcomes)
    low = (
        bootstrap_low(edge, defs.BLOCK_DAYS, defs.BOOTSTRAP_DRAWS, defs.BOOTSTRAP_SEED)
        if len(edge) >= defs.MIN_CONFIDENCE_DAYS
        else None
    )
    word = "insufficient" if low is None else "above zero" if low > 0 else "not above zero"

    return {
        "defs": defs.EVIDENCE_DEFS_VERSION,
        "label": defs.OBSERVED_NOT_PROOF,
        "candidate": cand,
        "every_stock": summarise(outs(every)),
        "random_5": random_row,
        "momentum_5": summarise(outs(momentum_picks(bars, every, days))),
        "nifty_matched": nifty,
        "cash": {"avg_net": 0.0},
        "edge": {
            "days": len(edge),
            "mean": sum(edge) / len(edge) if edge else None,
            "lower_bound": low,
            "word": word,
        },
        "coverage": {
            "days_with_ideas": len(days),
            "days_available": sum(1 for syms in pool.values() if syms),
        },
    }


# --- portfolio level ---------------------------------------------------------------------------


def risk_report(res: PortfolioResult) -> dict:
    """The four numbers the plan asks for, plus trade counts."""
    return {
        "max_drawdown": res.max_drawdown,
        "halt_triggered": res.halted_days > 0,
        "halted_days": res.halted_days,
        "final_net_return": res.total_return,
        "trades": res.trades,
        "still_open": res.still_open,
    }


def _spread(values: list[float]) -> dict:
    xs = sorted(values)
    if not xs:
        return {"median": None, "p5": None, "p95": None}
    return {
        "median": statistics.median(xs),
        "p5": xs[int(0.05 * (len(xs) - 1))],
        "p95": xs[int(0.95 * (len(xs) - 1))],
    }


def nifty_hold(index_bars: pd.DataFrame | None, days: Sequence[date], capital: float) -> dict | None:
    """Buy NIFTY with the whole capital at the first day's open, hold, sell at the last day's close."""
    if index_bars is None or index_bars.empty or not days:
        return None
    held = index_bars[(index_bars["day"] >= days[0]) & (index_bars["day"] <= days[-1])]
    if held.empty:
        return None
    fill = apply_slippage(float(held.iloc[0]["open"]), "BUY")
    qty = capital / fill
    brokerage, taxes = compute_charges(fill * qty, "BUY")
    qty *= capital / (fill * qty + brokerage + taxes)  # spend the capital, charges included
    brokerage, taxes = compute_charges(fill * qty, "BUY")
    left = capital - fill * qty - brokerage - taxes
    peak, max_dd = capital, 0.0
    for close in held["close"]:
        value = left + qty * float(close)
        peak = max(peak, value)
        max_dd = max(max_dd, (peak - value) / peak)
    gross = apply_slippage(float(held.iloc[-1]["close"]), "SELL") * qty
    brokerage, taxes = compute_charges(gross, "SELL")
    end = left + gross - brokerage - taxes
    max_dd = max(max_dd, (peak - end) / peak)
    return {
        "max_drawdown": max_dd,
        "halt_triggered": None,  # one holding and no new entries: the halt does not apply
        "halted_days": None,
        "final_net_return": end / capital - 1.0,
        "note": NIFTY_HOLD_NOTE,
    }


def _run(
    picks: Sequence[Pick], bars: dict[str, pd.DataFrame], days: Sequence[date], capital: float
) -> PortfolioResult:
    """One account. Only the picked stocks' prices are passed: the replay reads no other stock, so the
    result is the same and the account is much quicker to replay."""
    used = {p.symbol for p in picks}
    return simulate(
        picks,
        {s: df for s, df in bars.items() if s in used},
        days,
        capital=capital,
        max_drawdown_pct=defs.MAX_DRAWDOWN_HALT,
    )


def portfolio_baselines(
    pool: Picks,
    bars: dict[str, pd.DataFrame],
    days: Sequence[date],
    buckets: dict[str, str | None],
    index_bars: pd.DataFrame | None,
    *,
    capital: float,
    runs: int = defs.PORTFOLIO_RANDOM_RUNS,
    seed: int = defs.RANDOM_SEED,
) -> dict:
    """The accounts that do not depend on any candidate: random 5 and momentum 5 on every day of the
    pool, NIFTY bought and held, and cash. Computed once and shared by every candidate of a report."""
    decision_days = sorted(d for d, syms in pool.items() if syms)
    rng = random.Random(seed)
    random_reports = []
    for _ in range(runs if decision_days else 0):
        picks = [
            Pick(d, s, rng.random(), buckets.get(s))
            for d, syms in _random_day_picks(rng, pool, decision_days).items()
            for s in syms
        ]
        random_reports.append(risk_report(_run(picks, bars, days, capital)))

    scores = momentum_scores(bars, decision_days)
    mom = [
        Pick(d, s, scores[s][d], buckets.get(s))
        for d, syms in momentum_picks(bars, pool, decision_days).items()
        for s in syms
    ]
    random_row: dict = {"runs": len(random_reports)}
    for key in ("max_drawdown", "halted_days", "final_net_return"):
        random_row[key] = _spread([r[key] for r in random_reports])
    random_row["halt_triggered_share"] = (
        sum(1 for r in random_reports if r["halt_triggered"]) / len(random_reports)
        if random_reports
        else None
    )
    return {
        "random_5": random_row,
        "momentum_5": risk_report(_run(mom, bars, days, capital)),
        "nifty_hold": nifty_hold(index_bars, days, capital),
        "cash": {"max_drawdown": 0.0, "halt_triggered": False, "halted_days": 0, "final_net_return": 0.0},
    }


def portfolio_level(
    candidate: Sequence[Pick],
    pool: Picks,
    bars: dict[str, pd.DataFrame],
    days: Sequence[date],
    buckets: dict[str, str | None],
    index_bars: pd.DataFrame | None,
    *,
    capital: float,
    runs: int = defs.PORTFOLIO_RANDOM_RUNS,
    seed: int = defs.RANDOM_SEED,
    shared: dict | None = None,
) -> dict:
    """Equal-capital accounts over `days` (every trading day from the first decision day to the end of
    the data). Every account gets the same limits; none uses another's trades. `shared` is a
    `portfolio_baselines` result for the same pool, days and capital, to avoid recomputing it."""
    if shared is None:
        shared = portfolio_baselines(
            pool, bars, days, buckets, index_bars, capital=capital, runs=runs, seed=seed
        )
    return {
        "defs": defs.EVIDENCE_DEFS_VERSION,
        "label": defs.OBSERVED_NOT_PROOF,
        "capital": capital,
        "first_day": days[0].isoformat() if days else None,
        "last_day": days[-1].isoformat() if days else None,
        "candidate": risk_report(_run(candidate, bars, days, capital)),
        **shared,
    }
