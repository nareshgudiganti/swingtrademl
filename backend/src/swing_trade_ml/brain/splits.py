# backend/src/swing_trade_ml/brain/splits.py
"""Results split by market type and by sector (ps8), so a win in a rising market or in one sector
is not mistaken for skill. Pure functions, used by the evidence reports.

Market type is the locked `evidence-defs-v1` definition (`walk_forward.classify_regime`: a 28-day
window's average stock move, over +3% rising, under -3% falling, else sideways), labelled after the
fact for reporting only. Sector is today's sector map (`ml/sector_map.get_sector_bucket`), so a stock
that changed sector is reported under its current one; unmapped stocks get their own row.

`results=False` gives counts only. The clean period (Hold-out A, prod from 2026-10-14) is reported
that way until its planned evaluation, because results split by type or sector would spend it.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable

from swing_trade_ml.brain.replay_scoring import StrictOutcome

UNMAPPED = "unmapped"
WEAK_TYPE_LIMIT = -0.01  # evidence plan section 4: no market type below -1% per trade after costs ...
WEAK_TYPE_MIN_FOLDS = 3  # ... counted only for types seen in at least this many windows
COUNTS_ONLY_NOTE = (
    "Counts only: results split by market type or sector stay hidden until the trial's planned "
    "evaluation, so the clean period (from 2026-10-14) is not used up by looking."
)


def sector_of(symbol: str) -> str:
    from swing_trade_ml.ml.sector_map import get_sector_bucket

    return get_sector_bucket(symbol) or UNMAPPED


def split(rows: Iterable[tuple[str, str, StrictOutcome | None]], *, results: bool = True) -> dict[str, dict]:
    """rows: (group, symbol, outcome or None). Per group: ideas and distinct stocks and, with
    `results`, the finished ideas, hit rate and average result per finished idea after costs."""
    groups: dict[str, list[tuple[str, StrictOutcome | None]]] = defaultdict(list)
    for group, sym, outcome in rows:
        groups[group].append((sym, outcome))
    out: dict[str, dict] = {}
    for group in sorted(groups):
        items = groups[group]
        done = [o for _, o in items if o is not None and o.net_return is not None]
        row: dict = {"ideas": len(items), "stocks": len({s for s, _ in items})}
        if results:
            row["finished"] = len(done)
            row["hit_rate"] = sum(o.status == "target" for o in done) / len(done) if done else None
            row["avg_net"] = sum(o.net_return for o in done) / len(done) if done else None
        out[group] = row
    return out


def by_market_type(
    rows: Iterable[tuple[str, str, StrictOutcome | None]],
    window_labels: Iterable[str],
    *,
    results: bool = True,
) -> dict[str, dict]:
    """`split` by market type, plus how many windows had each type (also types with no ideas)."""
    windows = Counter(window_labels)
    out = split(rows, results=results)
    for label, n in windows.items():
        out.setdefault(
            label,
            {"ideas": 0, "stocks": 0}
            | ({"finished": 0, "hit_rate": None, "avg_net": None} if results else {}),
        )
        out[label]["windows"] = n
    return dict(sorted(out.items()))


def by_sector(
    rows: Iterable[tuple[str, StrictOutcome | None]],
    *,
    results: bool = True,
    sector: Callable[[str], str] = sector_of,
) -> dict[str, dict]:
    """rows: (symbol, outcome or None), grouped by the symbol's sector."""
    return split(((sector(sym), sym, o) for sym, o in rows), results=results)


def weak_market_types(types: dict[str, dict]) -> list[str]:
    """Market types seen in enough windows whose average result per trade is below the limit."""
    return [
        label
        for label, r in types.items()
        if r.get("windows", 0) >= WEAK_TYPE_MIN_FOLDS
        and r.get("avg_net") is not None
        and r["avg_net"] < WEAK_TYPE_LIMIT
    ]
