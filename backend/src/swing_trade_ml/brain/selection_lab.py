# backend/src/swing_trade_ml/brain/selection_lab.py
# ruff: noqa: E501 (long lines are protocol sentences)
"""Selection lab (15-day stock selection experiments): building blocks, draft protocol `sl-protocol-v1`.

Design: `docs/superpowers/specs/2026-10-29-selection-model-experiments-design.md` (rev 3). Nothing here runs an
experiment, trains a model, writes to the database or is imported by live code. This first piece is the label of
section 4.1: whether a stock "beats the day's median" over the next 15 trading days.
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Mapping, Sequence
from datetime import date

import numpy as np
import pandas as pd

HORIZON_BARS = 15
TOP_SHARE = 0.30  # label 1 = in the top 30% of the reference group's excess return
MIN_REFERENCE = 10  # fewer reference stocks with a valid return on a day means no labels that day
_TOL = 1e-12  # float noise only: a value exactly on the cut-off must count as on it


def forward_return(bars: pd.DataFrame, decision_day: date) -> float | None:
    """r(s,d) = close of day 15 / open of day 1 - 1, gross of costs. Day 1 is the first bar after the decision day.
    None when the window is incomplete or either price is not a positive number."""
    days = list(bars["day"])
    k = bisect.bisect_right(days, decision_day)  # first bar strictly after the decision day
    if k + HORIZON_BARS - 1 >= len(days):
        return None
    entry_open = float(bars.iloc[k]["open"])
    exit_close = float(bars.iloc[k + HORIZON_BARS - 1]["close"])
    if not (math.isfinite(entry_open) and math.isfinite(exit_close)) or entry_open <= 0 or exit_close <= 0:
        return None
    return exit_close / entry_open - 1.0


def excess_labels(
    returns: Mapping[str, float], reference: Sequence[str], min_reference: int = MIN_REFERENCE
) -> tuple[dict[str, int], float] | None:
    """The label of design section 4.1 for one decision day, for every stock in `returns` (reference or not).

    Excess e = r - median r of the reference group. One cut-off C = the 70th percentile of e over the reference
    group only (linear interpolation). Label = 1 if e >= C, else 0, for every stock alike, so an extra training
    stock is labelled by the same rule against a fixed distribution and never moves C. A value at or tied with C
    is 1. A stock without a finite return gets no label. Returns None (no labels that day) with fewer than
    `min_reference` reference stocks that have a valid return.
    """
    valid = {s: float(r) for s, r in returns.items() if r is not None and math.isfinite(r)}
    ref_returns = [valid[s] for s in reference if s in valid]
    if len(ref_returns) < min_reference:
        return None
    median = float(np.median(ref_returns))
    cut = float(np.percentile([r - median for r in ref_returns], (1 - TOP_SHARE) * 100, method="linear"))
    return {s: int(r - median >= cut - _TOL) for s, r in valid.items()}, cut
