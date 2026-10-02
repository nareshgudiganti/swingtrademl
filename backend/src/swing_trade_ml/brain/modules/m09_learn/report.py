"""M09 learning loop, task 2: pure reporting — expected vs actual, grouped by
confidence band, by decision word and by ISO week.

Pure: takes a DataFrame with the columns below (Task 5 builds it from
`brain_decisions`); no side effects, no database.

rows columns: run_started (datetime), decision_day (date), symbol, word,
confidence (float|None), outcome, ret.
"""

from __future__ import annotations

import pandas as pd

BANDS: tuple[tuple[float, float], ...] = ((0.0, 0.4), (0.4, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 1.01))
WORD_ORDER: tuple[str, ...] = ("TRADE", "WATCH", "WAIT", "AVOID")
R_UNIT = 0.04  # the 4% risked; R = ret / R_UNIT


def one_per_day(rows: pd.DataFrame) -> pd.DataFrame:
    """Keep only the latest `run_started` per (symbol, decision_day): a stock
    decided more than once on the same day (e.g. a catch-up run) counts
    once, using the freshest call."""
    if rows.empty:
        return rows
    return rows.sort_values("run_started").drop_duplicates(subset=["symbol", "decision_day"], keep="last")


def _band_label(lo: float, hi: float) -> str:
    if hi >= 1.0:
        return f"{round(lo * 100)}%+"
    return f"{round(lo * 100)}-{round(hi * 100)}%"


def _hit_and_avg_r(group: pd.DataFrame) -> tuple[float, float]:
    hit = float((group["outcome"] == "target").mean())
    avg_r = float(group["ret"].mean() / R_UNIT)
    return hit, avg_r


def by_band(rows: pd.DataFrame) -> list[dict]:
    """Per confidence band with at least one row: how many ideas, what
    confidence they carried on average ("said"), the share that actually hit
    target ("hit"), and the average outcome in R. Rows with no confidence are
    skipped — they were never scored for calibration."""
    rows = one_per_day(rows)
    rows = rows[rows["confidence"].notna()]
    out = []
    for lo, hi in BANDS:
        in_band = rows[(rows["confidence"] >= lo) & (rows["confidence"] < hi)]
        if in_band.empty:
            continue
        hit, avg_r = _hit_and_avg_r(in_band)
        out.append(
            {
                "band": _band_label(lo, hi),
                "n": len(in_band),
                "said": float(in_band["confidence"].mean()),
                "hit": hit,
                "avg_r": avg_r,
            }
        )
    return out


def by_word(rows: pd.DataFrame) -> list[dict]:
    """Per decision word actually present, in the fixed TRADE/WATCH/WAIT/AVOID
    order."""
    rows = one_per_day(rows)
    out = []
    for word in WORD_ORDER:
        in_word = rows[rows["word"] == word]
        if in_word.empty:
            continue
        hit, avg_r = _hit_and_avg_r(in_word)
        out.append({"word": word, "n": len(in_word), "hit": hit, "avg_r": avg_r})
    return out


def _iso_week(d) -> str:
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def by_week(rows: pd.DataFrame) -> list[dict]:
    """Per ISO week of `decision_day`, ascending."""
    rows = one_per_day(rows)
    if rows.empty:
        return []
    rows = rows.assign(_week=rows["decision_day"].map(_iso_week))
    out = []
    for week in sorted(rows["_week"].unique()):
        in_week = rows[rows["_week"] == week]
        hit, avg_r = _hit_and_avg_r(in_week)
        out.append({"week": week, "n": len(in_week), "hit": hit, "avg_r": avg_r})
    return out
