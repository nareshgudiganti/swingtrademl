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


MIN_BARS = 220  # a stock is in the reference group only with this much history up to the decision day
MIN_TURNOVER_INR = 5e7  # Rs 5 crore: median close x volume over 20 sessions up to and including the day
TURNOVER_SESSIONS = 20
IST = "Asia/Kolkata"


def median_turnover(bars: pd.DataFrame, day: date, sessions: int = TURNOVER_SESSIONS) -> float | None:
    """Median of close x volume over the last `sessions` bars up to and including `day`; None with fewer."""
    upto = bars[bars["day"] <= day].tail(sessions)
    if len(upto) < sessions:
        return None
    return float((upto["close"] * upto["volume"]).median())


def reference_for_day(day: date, candidates: Sequence[str], bars: Mapping[str, pd.DataFrame]) -> list[str]:
    """The reference group of design section 4.1 for one decision day: the candidates (the 49) with enough
    history and enough turnover. A valid forward return is checked by `excess_labels`, which drops the rest."""
    out = []
    for s in candidates:
        df = bars.get(s)
        if df is None or int((df["day"] <= day).sum()) < MIN_BARS:
            continue
        t = median_turnover(df, day)
        if t is not None and t >= MIN_TURNOVER_INR:
            out.append(s)
    return out


def label_frame(
    dataset: pd.DataFrame, bars: Mapping[str, pd.DataFrame], candidates: Sequence[str]
) -> tuple[pd.DataFrame, dict]:
    """Replace a training frame's target with the section 4.1 label. `dataset` has `symbol` and a tz-aware `ts`
    (the decision bar); the decision day is the IST date of the stamp. Rows without a forward return, and every
    row on a day without enough reference stocks, are dropped and counted. Returns the labelled frame (with a
    `day` column) and a report: counts, and the share of 1s among reference and extra stocks per year."""
    work = dataset.assign(day=pd.to_datetime(dataset["ts"], utc=True).dt.tz_convert(IST).dt.date)
    rets: dict[tuple[str, date], float | None] = {}
    for s, d in set(zip(work["symbol"], work["day"], strict=True)):
        df = bars.get(s)
        rets[(s, d)] = forward_return(df, d) if df is not None else None
    work["_r"] = [rets[(s, d)] for s, d in zip(work["symbol"], work["day"], strict=True)]
    no_return = int(work["_r"].isna().sum())
    labelled, days_ok, days_bad = [], set(), set()
    for d, grp in work.dropna(subset=["_r"]).groupby("day"):
        got = excess_labels(
            dict(zip(grp["symbol"], grp["_r"], strict=True)), reference_for_day(d, candidates, bars)
        )
        if got is None:
            days_bad.add(d)
            continue
        days_ok.add(d)
        labels, _cut = got
        labelled.append(grp.assign(target=[labels[s] for s in grp["symbol"]]))
    out = pd.concat(labelled).drop(columns=["_r"]) if labelled else work.iloc[0:0].drop(columns=["_r"])
    share: dict[str, dict[str, float]] = {}
    if len(out):
        cand = set(candidates)
        tagged = out.assign(year=[d.year for d in out["day"]], is_ref=[s in cand for s in out["symbol"]])
        for (year, is_ref), grp in tagged.groupby(["year", "is_ref"]):
            share.setdefault(str(year), {})["reference" if is_ref else "extra"] = float(grp["target"].mean())
    return out, {
        "rows_in": len(work),
        "rows_without_return": no_return,
        "days_labelled": len(days_ok),
        "days_without_labels": len(days_bad),
        "share_of_ones_by_year": share,
    }
