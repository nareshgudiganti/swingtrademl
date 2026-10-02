"""Look up similar past cases and summarise what happened next.

Only cases whose outcome was known by the run's date count (`outcome_day`
on or before it); the day-by-day band uses only cases whose whole 15-day
path was known (`path_day`). With fewer than MIN_CASES exact matches the key
is widened — volatility dropped first, then the market label, then the
20-day trend — and the parts dropped are recorded, so the card can say how
loose the match was.

Honesty: on 46 months the lookup never saw (docs/brain/evidence/
m05_memory_walk_forward.py) recall ranked outcomes barely better than chance
(AUC 0.52) and over-promised — matches it scored 40%+ came true 22.5%. Its
distance from the overall average was about a quarter real, so besides the
raw history it reports honest figures that keep RELIABILITY of that distance:
honest = base + RELIABILITY x (similar - base). Pure.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from swing_trade_ml.brain.contracts import Recall

MIN_CASES = 30
RELIABILITY = 0.25
PARTS = ("market", "stock", "trend", "vol")
WIDEN = (("vol", "volatility"), ("market", "market"), ("trend", "trend"))


def describe(key: dict, dropped: tuple[str, ...] = ()) -> str:
    names = {"market": "market", "stock": "stock trend", "trend": "last 20 days", "vol": "volatility"}
    return " · ".join(f"{names[p]} {key[p]}" for p in PARTS if p in key and p not in dropped)


def recall(
    cases: pd.DataFrame, symbol: str, key: dict, as_of_day: date, min_cases: int = MIN_CASES
) -> Recall:
    known = cases[cases["outcome_day"] <= as_of_day] if len(cases) else cases
    parts = [p for p in PARTS if p in key]
    dropped: list[str] = []
    widened: list[str] = []

    def matches(use: list[str]) -> pd.DataFrame:
        mask = np.ones(len(known), dtype=bool)
        for p in use:
            mask &= (known[p] == key[p]).to_numpy()
        return known[mask]

    found = matches(parts)
    for part, name in WIDEN:
        if len(found) >= min_cases or part not in parts:
            continue
        dropped.append(part)
        widened.append(name)
        found = matches([p for p in parts if p not in dropped])

    if found.empty:
        return Recall(symbol=symbol, n_similar=0, key=describe(key, tuple(dropped)), widened=tuple(widened))

    returns = found["exit_return"].to_numpy(float)
    base_hit = float((known["outcome"] == "target").mean())
    base_mean = float(known["exit_return"].mean())
    hit_rate = float((found["outcome"] == "target").mean())
    mean_return = float(returns.mean())
    hits = found[found["outcome"] == "target"]
    full = found[found["path_day"] <= as_of_day]
    path = ()
    if len(full):
        paths = np.vstack(full["path"].to_numpy())
        path = tuple(
            (
                d + 1,
                float(np.percentile(paths[:, d], 25)),
                float(np.median(paths[:, d])),
                float(np.percentile(paths[:, d], 75)),
            )
            for d in range(paths.shape[1])
        )
    return Recall(
        symbol=symbol,
        n_similar=len(found),
        hit_rate=hit_rate,
        mean_return=mean_return,
        honest_hit_rate=base_hit + RELIABILITY * (hit_rate - base_hit),
        honest_mean_return=base_mean + RELIABILITY * (mean_return - base_mean),
        median_return=float(np.median(returns)),
        p25=float(np.percentile(returns, 25)),
        p75=float(np.percentile(returns, 75)),
        median_days=float(np.median(hits["days"])) if len(hits) else None,
        key=describe(key, tuple(dropped)),
        widened=tuple(widened),
        typical_path=path,
    )
