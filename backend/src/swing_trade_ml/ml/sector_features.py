"""The four sector inputs (B1-5..B1-8), ONE definition for training and serving.

Plain English and the full rules: docs/brain/SECTOR-FEATURES-SPEC.md.

Lesson from the obv_slope incident (docs/superpowers/specs/2026-10-30-obv-slope-incident.md): training and
serving must call the SAME function. There is exactly one builder here, `build_sector_features`. Training calls
it on the full history; serving calls `sector_features_asof`, which cuts every input at the decision day and
calls the same builder. A parity test asserts the two agree on every date.

Pure functions over series. No database, no clock, no randomness. Nothing here reads a value dated after the
decision day: every number is a backward-looking ratio or a same-day rank.

Rule used (the official-index rule): the sector is the stock's OFFICIAL NSE sector index (a price series we
hold). The alternative, a leave-one-stock-out average over the stocks in our universe, is NOT used and is never
combined with this rule. (Reason: the local stock set has survivors only, so an average over it would be biased.)
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

import numpy as np
import pandas as pd

IST = "Asia/Kolkata"

SHORT_WINDOW = 10  # sessions
LONG_WINDOW = 20  # sessions
# An index or stock close missing on a session may be carried forward from the previous session ONCE
# (so at most one session stale). A second missing session in a row stays missing. Never 0.
MAX_FFILL = 1
# A per-day rank among fewer than this many sector indices is not meaningful: missing.
MIN_RANK_SECTORS = 5

SECTOR_RET_10D = "sector_ret_10d_vs_nifty"
SECTOR_RET_20D = "sector_ret_20d_vs_nifty"
SECTOR_RANK_10D = "sector_rank_10d"
STOCK_VS_SECTOR_10D = "stock_vs_sector_10d"
FEATURE_NAMES: tuple[str, ...] = (SECTOR_RET_10D, SECTOR_RET_20D, SECTOR_RANK_10D, STOCK_VS_SECTOR_10D)
# Dropped from the RESEARCH challenger on 2026-11-06 (C_56): `sector_ret_20d_vs_nifty` is, by its definition, the
# difference of two inputs that already exist (relative_strength_20d - sector_relative_strength_20d). The two agree
# on 45,917 of 45,930 audited rows to 1e-9; the other 13 differ only because NIFTY HEALTHCARE lacks sessions and the
# existing inputs count 20 ROWS of an index while this builder counts 20 SESSIONS of the shared calendar (a
# definition difference, no new information: docs/brain/evidence/sector_prep/c56_decision_v3.json).
# The builder still computes it (serving and the parity tests are unchanged); the research path does not use it.
REDUNDANT_WITH_EXISTING: tuple[str, ...] = (SECTOR_RET_20D,)
RESEARCH_FEATURE_NAMES: tuple[str, ...] = tuple(n for n in FEATURE_NAMES if n not in REDUNDANT_WITH_EXISTING)
# Sessions before the first row where all four can exist (the longest window).
WARMUP_SESSIONS = LONG_WINDOW

# Index series the per-day rank is taken over: the distinct sector indices behind ml/sector_map.py.
# NIFTY CHEMICALS is left out on purpose: it only exists from 2025-11-24, so it would change the rank scale
# part-way through the history.
DEFAULT_RANK_UNIVERSE: tuple[str, ...] = (
    "NIFTY AUTO",
    "NIFTY BANK",
    "NIFTY CAPITAL MKT",
    "NIFTY COMMODITIES",
    "NIFTY CONSR DURBL",
    "NIFTY CONSUMPTION",
    "NIFTY ENERGY",
    "NIFTY FIN SERVICE",
    "NIFTY FMCG",
    "NIFTY HEALTHCARE",
    "NIFTY INFRA",
    "NIFTY IT",
    "NIFTY METAL",
    "NIFTY PHARMA",
    "NIFTY REALTY",
)

# Stocks with no label in ml/sector_map.py. Proposed official indices; NOT yet confirmed against an official
# NSE factsheet (see the spec). Treated as "no sector" unless the caller opts in with include_unverified=True.
PROPOSED_UNVERIFIED: dict[str, str] = {
    "ASIANPAINT": "NIFTY CONSR DURBL",
    "BHARTIARTL": "NIFTY INFRA",
}


def resolve_sector_index(symbol: str, include_unverified: bool = False) -> str | None:
    """The official sector index name for a stock, or None (= no sector: the four inputs stay missing)."""
    from swing_trade_ml.ml.sector_map import SECTOR_INDEX_MAP  # frozen file; read only

    s = symbol.upper()
    if s in SECTOR_INDEX_MAP:
        return SECTOR_INDEX_MAP[s]
    if include_unverified:
        return PROPOSED_UNVERIFIED.get(s)
    return None


def close_series_from_candles(df: pd.DataFrame) -> pd.Series:
    """Candles (columns ts, close; ts timezone-aware, daily bars stamped IST midnight) -> close indexed by
    the IST calendar date (naive, midnight). Duplicates keep the last; ascending; non-positive closes dropped."""
    if df is None or len(df) == 0:
        return pd.Series(dtype="float64")
    ts = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(IST).dt.tz_localize(None).dt.normalize()
    s = pd.Series(df["close"].to_numpy(dtype="float64"), index=pd.DatetimeIndex(ts))
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s[s > 0]


def _clean(s: pd.Series | None, as_of: pd.Timestamp | None) -> pd.Series:
    if s is None or len(s) == 0:
        return pd.Series(dtype="float64")
    s = s.astype("float64").sort_index()
    s = s[~s.index.duplicated(keep="last")]
    if as_of is not None:
        s = s[s.index <= as_of]  # the ONLY place the decision day cuts the data
    return s[s > 0]


def _window_return(close_on_calendar: pd.Series, n: int) -> pd.Series:
    """close[t] / close[t-n sessions] - 1 on the shared calendar. Missing if either end is missing."""
    r = close_on_calendar / close_on_calendar.shift(n) - 1.0
    return r.replace([np.inf, -np.inf], np.nan)


def build_sector_features(
    stock_close: pd.Series,
    nifty_close: pd.Series,
    sector_closes: Mapping[str, pd.Series],
    sector_index: str | None,
    *,
    rank_universe: Iterable[str] = DEFAULT_RANK_UNIVERSE,
    max_ffill: int = MAX_FFILL,
    as_of: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """The four inputs for one stock, one row per session on the shared calendar. THE one definition.

    Shared calendar = every date on which NIFTY 50 or any supplied sector index has a close (not dependent on
    the stock). The stock and each index are placed on it; a missing close is carried forward at most
    `max_ffill` session(s), otherwise stays missing (NaN, never 0).

    With `as_of`, every input is first cut to dates <= as_of, so nothing later can influence any row.
    """
    cut = pd.Timestamp(as_of).normalize() if as_of is not None else None
    stock = _clean(stock_close, cut)
    nifty = _clean(nifty_close, cut)
    universe = list(dict.fromkeys(rank_universe))
    needed = set(universe) | ({sector_index} if sector_index else set())
    sectors = {k: _clean(v, cut) for k, v in sector_closes.items() if k in needed}

    cal = nifty.index
    for s in sectors.values():
        cal = cal.union(s.index)
    cal = cal.sort_values()

    def on_cal(s: pd.Series) -> pd.Series:
        placed = s.reindex(cal)
        return placed.ffill(limit=max_ffill) if max_ffill > 0 else placed  # pandas rejects limit=0

    nif = on_cal(nifty)
    stk = on_cal(stock)
    sec_on = {k: on_cal(v) for k, v in sectors.items()}

    nif10, nif20 = _window_return(nif, SHORT_WINDOW), _window_return(nif, LONG_WINDOW)
    stk10 = _window_return(stk, SHORT_WINDOW)

    out = pd.DataFrame(index=cal, columns=list(FEATURE_NAMES), dtype="float64")
    out.index.name = "date"

    # Per-day rank over the sector indices that have a 10-day return that day (0 = weakest, 1 = strongest).
    ranked = [u for u in universe if u in sec_on]
    if ranked:
        ret10_all = pd.DataFrame({u: _window_return(sec_on[u], SHORT_WINDOW) for u in ranked})
        n_avail = ret10_all.notna().sum(axis=1)
        rank = ret10_all.rank(axis=1, method="average")
        rank01 = rank.sub(1.0).div((n_avail - 1.0).where(n_avail >= MIN_RANK_SECTORS), axis=0)
    else:
        rank01 = pd.DataFrame(index=cal)

    if sector_index and sector_index in sec_on:
        sec10 = _window_return(sec_on[sector_index], SHORT_WINDOW)
        sec20 = _window_return(sec_on[sector_index], LONG_WINDOW)
        out[SECTOR_RET_10D] = sec10 - nif10
        out[SECTOR_RET_20D] = sec20 - nif20
        out[STOCK_VS_SECTOR_10D] = stk10 - sec10
        if sector_index in rank01.columns:
            out[SECTOR_RANK_10D] = rank01[sector_index]
    return out


def sector_features_asof(
    stock_close: pd.Series,
    nifty_close: pd.Series,
    sector_closes: Mapping[str, pd.Series],
    sector_index: str | None,
    as_of: pd.Timestamp,
    **kwargs,
) -> pd.Series:
    """Serving path: the four inputs on the decision day `as_of`, from history up to and including it.
    Same builder as training. All NaN if `as_of` is not a session on the shared calendar."""
    day = pd.Timestamp(as_of).normalize()
    frame = build_sector_features(stock_close, nifty_close, sector_closes, sector_index, as_of=day, **kwargs)
    if day in frame.index:
        return frame.loc[day]
    return pd.Series(np.nan, index=list(FEATURE_NAMES), name=day)
