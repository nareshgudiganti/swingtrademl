"""M09 learning loop, task 2: pure failure-pattern detection — among
stop-outs, which market situation or sector was over-represented relative to
its share of all rows.

Pure: takes a DataFrame with the columns `report.py` needs plus `market`
(market situation label or None) and `sector` (str or None); no side
effects, no database.
"""

from __future__ import annotations

import pandas as pd

from swing_trade_ml.brain.modules.m09_learn.report import one_per_day
from swing_trade_ml.brain.modules.m11_sector.ranking import plain_name
from swing_trade_ml.ml.sector_map import _SECTOR_INDEX


def _sector_name(bucket: str) -> str:
    index = _SECTOR_INDEX.get(bucket)
    return plain_name(index) if index else bucket


def _market_line(value: str, stop_count: int, total_stops: int, all_share: float) -> str:
    pct = round(all_share * 100)
    return (
        f"{stop_count} of {total_stops} stop-outs came when the market was in "
        f"a {value} ({value} was {pct}% of all ideas)."
    )


def _sector_line(value: str, stop_count: int, total_stops: int, all_share: float) -> str:
    name = _sector_name(value)
    pct = round(all_share * 100)
    return f"{stop_count} of {total_stops} stop-outs were {name} stocks ({name} were {pct}% of all ideas)."


def _candidates(
    rows: pd.DataFrame, stops: pd.DataFrame, column: str, min_stops: int, lift: float, line
) -> list[tuple[float, str]]:
    total_n, total_stops = len(rows), len(stops)
    out: list[tuple[float, str]] = []
    for value in stops[column].dropna().unique():
        stop_count = int((stops[column] == value).sum())
        if stop_count < min_stops:
            continue
        all_count = int((rows[column] == value).sum())
        if all_count <= 0:
            continue
        all_share = all_count / total_n
        stop_share = stop_count / total_stops
        if stop_share >= lift * all_share:
            out.append((stop_share / all_share, line(value, stop_count, total_stops, all_share)))
    return out


def failure_patterns(rows: pd.DataFrame, min_stops: int = 3, lift: float = 1.5) -> list[str]:
    """Among `outcome == "stop"` rows, flag any market situation or sector
    whose share of stop-outs is at least `lift` times its share of all rows,
    with at least `min_stops` stops backing it. Most striking (highest lift
    ratio) first."""
    rows = one_per_day(rows)
    stops = rows[rows["outcome"] == "stop"]
    if stops.empty:
        return []
    candidates = _candidates(rows, stops, "market", min_stops, lift, _market_line)
    candidates += _candidates(rows, stops, "sector", min_stops, lift, _sector_line)
    candidates.sort(key=lambda t: t[0], reverse=True)
    return [line for _, line in candidates]
