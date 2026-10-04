"""Which stocks move together, and how concentrated the book is.

Correlation uses the daily returns of the last 60 trading days, aligned by
date; a pair needs at least 40 shared days or nothing is claimed. Two stocks
above 0.7 have moved closely together — owning both is close to doubling one
position. Concentration names the largest single position and the largest
sector as shares of the whole portfolio. Pure.
"""

from __future__ import annotations

import pandas as pd

from swing_trade_ml.ml.sector_map import get_sector_bucket

WINDOW = 60
MIN_OVERLAP = 40
CLOSE = 0.7


def correlations(closes: dict[str, pd.Series]) -> pd.DataFrame:
    if not closes:
        return pd.DataFrame()
    frame = pd.DataFrame({s: c for s, c in closes.items() if len(c)}).sort_index()
    returns = frame.tail(WINDOW + 1).pct_change(fill_method=None).iloc[1:]
    return returns.corr(min_periods=MIN_OVERLAP)


def close_pairs(corr: pd.DataFrame, threshold: float = CLOSE) -> list[tuple[str, str, float]]:
    names = list(corr.columns)
    pairs = [
        (a, b, float(corr.loc[a, b]))
        for i, a in enumerate(names)
        for b in names[i + 1 :]
        if pd.notna(corr.loc[a, b]) and corr.loc[a, b] > threshold
    ]
    return sorted(pairs, key=lambda p: -p[2])


def concentration(values: dict[str, float], portfolio_value: float | None) -> dict:
    """{"largest_position": (symbol, share), "top_sector": (bucket, share)};
    None for either when there is nothing to measure."""
    if not values or not portfolio_value or portfolio_value <= 0:
        return {"largest_position": None, "top_sector": None}
    symbol, value = max(values.items(), key=lambda kv: kv[1])
    sectors: dict[str, float] = {}
    for s, v in values.items():
        bucket = get_sector_bucket(s)
        if bucket is not None:
            sectors[bucket] = sectors.get(bucket, 0.0) + v
    top = max(sectors.items(), key=lambda kv: kv[1]) if sectors else None
    return {
        "largest_position": (symbol, value / portfolio_value),
        "top_sector": (top[0], top[1] / portfolio_value) if top else None,
    }
