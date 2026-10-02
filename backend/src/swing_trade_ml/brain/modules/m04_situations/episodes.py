"""Market episodes: stretches of days under one market label — the start of
the brain's market memory ("past corrections, with start and end dates").

A new label starts an episode only after it has held for MIN_DAYS trading
days in a row (a crash starts one on its first day), so a market wobbling
across the -5% line does not leave dozens of one-day episodes. The episode
starts on the first of those days; the previous one ends the day before.
"unlabelled" days (too little history) belong to no episode. Pure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

MIN_DAYS = 3
IMMEDIATE = frozenset({"crash"})


@dataclass(frozen=True, slots=True)
class Episode:
    label: str
    start: date
    end: date | None  # None while it is still going
    days: int
    stats: dict = field(default_factory=dict)


def episodes_from_labels(labels: pd.Series, closes: pd.Series) -> list[Episode]:
    days = list(labels.index)
    raw = list(labels)
    starts: list[tuple[int, str]] = []  # (index where it starts, label)
    current: str | None = None
    run_label, run_start = None, 0
    for i, lab in enumerate(raw):
        if lab != run_label:
            run_label, run_start = lab, i
        if lab == "unlabelled" or lab == current:
            continue
        if lab in IMMEDIATE or i - run_start + 1 >= MIN_DAYS:
            starts.append((run_start, lab))
            current = lab

    episodes = []
    for k, (start, lab) in enumerate(starts):
        last = starts[k + 1][0] - 1 if k + 1 < len(starts) else len(days) - 1
        first_close, last_close = float(closes.iloc[start]), float(closes.iloc[last])
        episodes.append(
            Episode(
                label=lab,
                start=days[start],
                end=days[last] if k + 1 < len(starts) else None,
                days=last - start + 1,
                stats={"nifty_change": last_close / first_close - 1 if first_close else None},
            )
        )
    return episodes
