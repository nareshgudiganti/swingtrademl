"""Trade-level baselines, exactly as `evidence-defs-v1` defines them (evidence plan section 3a, locked as tag
evidence-defs-v1). Pure: no database.

The candidate's ideas against every stock, random 5, momentum 5 and NIFTY on the candidate's own days, with
the same next-open entry, exit rule and costs (`replay_scoring.strict_score`). NIFTY here follows each
idea's own exit day, so it is a comparison, never an index strategy.

Brought across from feature/evidence-phase-a (3686a1c), trade level only; the portfolio-level accounts of
that branch are outside the approved Observatory Phase 1A scope.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from datetime import date

import pandas as pd

from swing_trade_ml.brain.replay_scoring import HORIZON_BARS, POSITION_INR, STOP, TARGET, StrictOutcome
from swing_trade_ml.brain.walk_forward import bootstrap_low, daily_edge, momentum_scores, outcomes_for
from swing_trade_ml.services.brain_observatory import defs
from swing_trade_ml.services.costs import apply_slippage, compute_charges

Picks = dict[date, list[str]]

NIFTY_MATCHED_NOTE = (
    "Trade-level comparison only: each NIFTY holding ends on the matching idea's exit day, which nobody "
    "could know in advance, so this is not an index strategy anyone could run."
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
