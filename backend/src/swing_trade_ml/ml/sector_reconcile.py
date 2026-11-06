"""Row reconciliation for the sector experiments SX5 / SX10 (PREPARATION ONLY: reads, counts, writes reports).

Every raw stock-day row is counted ONCE, against the FIRST reason that applies, in this stated order:

  1. warm_up           the first `min_history` sessions of each stock (not enough history)
  2. label_incomplete  the last `horizon` sessions (the outcome is not known yet)
  3. event             a corporate-action window removed by the exclusion report (base policy)
  4. existing_gap      any existing model input (or the label) is missing for another reason
  5. sector_gap        the stock is unmapped or a sector input is missing (only where sector inputs are required)

Rows that also satisfy a LATER reason are listed in an overlap table ("removed for stage X, would also have been
removed for stage Y"), so nothing is hidden and nothing is added twice. Pure functions; the CLI at the bottom reads
local candles with SELECT only. Nothing here trains, writes to the database or is imported by production code.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

STAGES = ("warm_up", "label_incomplete", "event", "existing_gap", "sector_gap")
FINAL = "final"


@dataclass
class StockReconciliation:
    dates: list[date]
    stage: pd.Series  # per position: the first reason, or "final"
    counts: dict[str, int]
    overlap: dict[tuple[str, str], int]  # (stage it was counted at, later reason it also satisfied) -> rows
    event_rows: dict[str, int]  # event id -> rows attributed to it (earliest event wins)
    event_overlap: dict[
        tuple[str, str], int
    ]  # (event it was attributed to, other event also hitting) -> rows
    event_kind: dict[str, Counter] = field(default_factory=dict)  # event id -> Counter(window type)

    def final_keys(self, symbol: str) -> list[str]:
        return [
            f"{symbol}|{self.dates[i].isoformat()}" for i in np.flatnonzero(self.stage.to_numpy() == FINAL)
        ]


def reconcile_stock(
    dates: Sequence[date],
    event_hits: Iterable[Mapping[str, str]],
    feat_ok: np.ndarray,
    sec_ok: np.ndarray | None,
    *,
    horizon: int,
    min_history: int = 252,
) -> StockReconciliation:
    """`event_hits`: exclusion_report.excluded_rows() output for THIS stock (decision_date, event_id,
    window_type). `feat_ok`: all existing inputs present and the label known. `sec_ok`: all four sector inputs
    present, or None when sector inputs are not required (the full-49 baseline)."""
    dates = list(dates)
    n = len(dates)
    pos_of = {d.isoformat(): i for i, d in enumerate(dates)}
    feat_ok = np.asarray(feat_ok, dtype=bool)

    warm = np.arange(n) < min_history
    tail = np.arange(n) >= max(n - horizon, 0)
    ev_by_pos: dict[int, list[tuple[str, str]]] = {}
    for h in event_hits:
        p = pos_of.get(h["decision_date"])
        if p is not None:
            ev_by_pos.setdefault(p, []).append((h["event_id"], h.get("window_type", "")))
    ev = np.zeros(n, dtype=bool)
    for p in ev_by_pos:
        ev[p] = True
    gap = ~feat_ok
    sec = np.zeros(n, dtype=bool) if sec_ok is None else ~np.asarray(sec_ok, dtype=bool)

    masks = {"warm_up": warm, "label_incomplete": tail, "event": ev, "existing_gap": gap, "sector_gap": sec}
    stage = np.full(n, FINAL, dtype=object)
    for name in reversed(STAGES):  # earlier stages overwrite later ones: the first reason wins
        stage[masks[name]] = name

    counts = {"raw": n, **{s: int((stage == s).sum()) for s in STAGES}}
    counts[FINAL] = int((stage == FINAL).sum())
    overlap: dict[tuple[str, str], int] = {}
    for i, s in enumerate(STAGES):
        at = stage == s
        for later in STAGES[i + 1 :]:
            k = int((at & masks[later]).sum())
            if k:
                overlap[(s, later)] = k

    # events: attribute each event-stage row to the earliest event (by the date in its id)
    event_rows: Counter = Counter()
    event_overlap: Counter = Counter()
    kinds: dict[str, Counter] = {}
    for p, items in ev_by_pos.items():
        if stage[p] != "event":
            continue
        ids = sorted({e for e, _ in items}, key=lambda x: (x.split(":")[-1], x))
        first = ids[0]
        event_rows[first] += 1
        for other in ids[1:]:
            event_overlap[(first, other)] += 1
        kinds.setdefault(first, Counter())[next(k for e, k in items if e == first)] += 1
    return StockReconciliation(
        dates=dates,
        stage=pd.Series(stage),
        counts=counts,
        overlap=overlap,
        event_rows=dict(event_rows),
        event_overlap=dict(event_overlap),
        event_kind=kinds,
    )


def keys_sha256(keys: Iterable[str]) -> str:
    """Same canonical hash as exclusion_report.dataset_hash: sha256 of the sorted keys, newline separated."""
    return hashlib.sha256("\n".join(sorted(keys)).encode("utf-8")).hexdigest()


def is_subset(smaller: Iterable[str], larger: Iterable[str]) -> bool:
    return set(smaller) <= set(larger)


def add_counts(total: dict[str, int], part: Mapping[str, int]) -> None:
    for k, v in part.items():
        total[k] = total.get(k, 0) + v
