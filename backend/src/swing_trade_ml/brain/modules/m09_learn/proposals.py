"""M09 learning loop, task 4: a buy-level proposal from scored ideas — pure,
no side effects. Nothing here changes the brain's behaviour by itself
(constitution C9): `store.create` only records the suggestion, and only the
owner's `store.accept` makes it count."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

R_UNIT = 0.04  # the 4% risked; R = ret / R_UNIT


@dataclass(frozen=True, slots=True)
class Draft:
    kind: str  # "buy_level" | "module_mode"
    title: str
    evidence: str
    change: dict


def _group(rows: pd.DataFrame, threshold: float) -> pd.DataFrame:
    return rows[rows["confidence"] >= threshold]


def _avg_r(rows: pd.DataFrame) -> float:
    return float(rows["ret"].mean() / R_UNIT)


def buy_level_proposal(
    rows: pd.DataFrame,
    current: float,
    candidates: tuple[float, ...] = (0.55, 0.6, 0.65, 0.7, 0.75),
    min_cases: int = 20,
    min_gain_r: float = 0.05,
) -> Draft | None:
    """Among scored ideas (`rows`: `report.one_per_day` output, with
    `confidence`, `outcome` and `ret`), see whether a different buy-level bar
    than `current` would plainly have done better. For each candidate
    threshold (other than `current`) with at least `min_cases` ideas scored
    at or above it, the average result in R (the 4% risked; `ret / 0.04`) of
    those ideas is compared with the same average at `current`. The
    best-scoring candidate is proposed only when it beats `current` by at
    least `min_gain_r` R and `current` itself has enough cases to judge it
    against — otherwise None, so a quiet or data-starved stretch proposes
    nothing rather than a noisy suggestion.

    Rows with no confidence are ignored (they were never scored for this)."""
    rows = rows[rows["confidence"].notna()]
    current_group = _group(rows, current)
    if len(current_group) < min_cases:
        return None
    avg_r_current = _avg_r(current_group)

    best_t: float | None = None
    best_avg_r = float("-inf")
    best_group: pd.DataFrame | None = None
    for t in candidates:
        if t == current:
            continue
        group = _group(rows, t)
        if len(group) < min_cases:
            continue
        avg_r = _avg_r(group)
        # Strict `>` keeps the first of equal averages; candidates run lowest
        # threshold first, so on a tie the lowest threshold wins.
        if avg_r > best_avg_r:
            best_t, best_avg_r, best_group = t, avg_r, group

    if best_t is None or best_avg_r < avg_r_current + min_gain_r:
        return None

    raising = best_t > current
    # The "wide" side is whichever threshold is lower (more ideas qualify);
    # the delta between the two thresholds is what the change would skip
    # (raising, going from the wider current to the narrower best) or add
    # (lowering, going from the narrower current to the wider best).
    wide_group = current_group if raising else best_group
    narrow_t = best_t if raising else current
    delta = wide_group[wide_group["confidence"] < narrow_t]
    stop_total = int((wide_group["outcome"] == "stop").sum())
    target_total = int((wide_group["outcome"] == "target").sum())
    delta_stop = int((delta["outcome"] == "stop").sum())
    delta_target = int((delta["outcome"] == "target").sum())
    verb = "skipped" if raising else "added"

    action = "Raise" if raising else "Lower"
    best_pct, current_pct = round(best_t * 100), round(current * 100)
    title = f"{action} the buy level to {best_pct}%"
    evidence = (
        f"Among {len(best_group)} past ideas scored {best_pct}% or more, the average result was "
        f"{best_avg_r:+.2f} R per trade, against {avg_r_current:+.2f} R for {len(current_group)} ideas "
        f"at the current {current_pct}%. It would have {verb} {delta_stop} of {stop_total} losing "
        f"ideas and {delta_target} of {target_total} winning ones."
    )
    return Draft(kind="buy_level", title=title, evidence=evidence, change={"buy_level": best_t})
