"""Has the market ever looked like this before?

Each day becomes a small vector — NIFTY's 20- and 60-day change, its
distance from the 1-year high, its 20-day volatility, India VIX and VIX's
5-day change — standardised on history. For every past day we measure the
distance to its nearest other past day (at least GAP days away, so a day is
not "similar" to its own neighbours); the 99th percentile of those is the
line. Today beyond the line → unknown: the brain has no comparable past to
lean on, which is itself a reason to be careful.

Needs MIN_HISTORY usable days; with less, nothing is called unknown.
Pure.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

GAP = 20
MIN_HISTORY = 250
PERCENTILE = 99


@dataclass(frozen=True, slots=True)
class Novelty:
    is_unknown: bool
    distance: float | None
    threshold: float | None
    nearest_day: date | None
    line: str


def state_vectors(nifty: pd.Series, vix: pd.Series) -> pd.DataFrame:
    close = nifty.astype(float)
    vix = vix.astype(float).reindex(close.index).ffill()
    frame = pd.DataFrame(
        {
            "ret20": close.pct_change(20),
            "ret60": close.pct_change(60),
            "dd": close / close.rolling(252, min_periods=1).max() - 1,
            "vol20": close.pct_change().rolling(20).std() * np.sqrt(252),
            "vix": vix,
            "vix_chg5": vix.pct_change(5),
        },
        index=close.index,
    )
    return frame.dropna()


def _nearest(points: np.ndarray, target: np.ndarray) -> tuple[float, int]:
    d = np.sqrt(((points - target) ** 2).sum(axis=1))
    i = int(np.argmin(d))
    return float(d[i]), i


def novelty(vectors: pd.DataFrame) -> Novelty:
    if len(vectors) < MIN_HISTORY + GAP:
        return Novelty(False, None, None, None, "Not enough history to tell whether today is unusual.")
    past = vectors.iloc[:-1]
    mean, std = past.mean(), past.std().replace(0, 1.0)
    z = ((vectors - mean) / std).to_numpy()
    history, today = z[:-1], z[-1]

    nn = []
    for i in range(len(history)):
        far = np.r_[0 : max(0, i - GAP), min(len(history), i + GAP + 1) : len(history)].astype(int)
        if far.size:
            nn.append(_nearest(history[far], history[i])[0])
    threshold = float(np.percentile(nn, PERCENTILE))

    candidates = history[: len(history) - GAP + 1]  # leave out the last few weeks
    distance, j = _nearest(candidates, today)
    nearest = vectors.index[j]
    if distance > threshold:
        line = (
            f"Today's market looks unlike any day in the history the brain has "
            f"(closest: {nearest:%d %b %Y}), so its past experience may not apply."
        )
        return Novelty(True, distance, threshold, nearest, line)
    return Novelty(False, distance, threshold, nearest, f"The most similar past day was {nearest:%d %b %Y}.")
