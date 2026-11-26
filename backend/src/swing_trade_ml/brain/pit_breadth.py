"""Point-in-time market breadth for the Brain (#488).

v1's breadth (`ml.market_context.load_market_breadth`) counts today's watchlist on every past day,
so adding or removing a stock later moves past days. The Brain's dated reader uses this module
instead: each day is counted over the stocks on that day's watchlist snapshot (the same
`WatchlistSnapshot` source `brain/universe.py` uses).

It sits next to v1 and is read only by the Brain (CLAUDE.md principle 8): v1 models, strategies
and the h05 lane keep calling `market_context` unchanged, and `market_context.py` stays
byte-for-byte as pinned by the h05 protocol.

Days before the first snapshot (snapshots began about 5 Oct 2026) have no record of the list, so
they keep v1's answer (today's watchlist) rather than going empty, which would force every earlier
replay DEFENSIVE.
"""

from __future__ import annotations

import time
from datetime import date
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from swing_trade_ml.db.models.market import Instrument, WatchlistSnapshot
from swing_trade_ml.ml import market_context

IST = ZoneInfo("Asia/Kolkata")
COLUMNS = ["ts", "breadth_pct_above_sma50", "breadth_advance_pct"]
TTL_SECONDS = 6 * 3600

# Closes of every stock that was ever on a snapshot, one column per stock, per interval.
_closes_cache: dict[str, tuple[float, pd.DataFrame]] = {}


def clear_cache() -> None:
    _closes_cache.clear()


def _ist_day(ts) -> date:
    t = pd.Timestamp(ts)
    return t.tz_convert(IST).date() if t.tzinfo is not None else t.date()


def breadth_with_membership(wide: pd.DataFrame, member: pd.DataFrame) -> pd.DataFrame:
    """v1's breadth formula (`market_context.compute_breadth`), with each day's count limited to
    the stocks that were on the watchlist that day (`member`, same shape, True = on the list).
    The 50-day average still uses each stock's full price history; only who is counted changes."""
    sma = wide.rolling(50, min_periods=50).mean()
    prev = wide.shift(1)
    above = (wide > sma).where(wide.notna() & sma.notna() & member)
    advanced = (wide > prev).where(wide.notna() & prev.notna() & member)
    return pd.DataFrame(
        {
            "ts": wide.index,
            "breadth_pct_above_sma50": above.mean(axis=1, skipna=True).values,
            "breadth_advance_pct": advanced.mean(axis=1, skipna=True).values,
        }
    ).reset_index(drop=True)


def _snapshot_closes(db: Session, interval: str) -> pd.DataFrame:
    hit = _closes_cache.get(interval)
    if hit is not None and time.monotonic() - hit[0] < TTL_SECONDS:
        return hit[1]
    from swing_trade_ml.ml.dataset import load_candles

    symbols = sorted(set(db.execute(select(WatchlistSnapshot.symbol).distinct()).scalars()))
    closes: dict[str, pd.Series] = {}
    for inst in db.execute(select(Instrument).where(Instrument.tradingsymbol.in_(symbols))).scalars():
        df = load_candles(db, inst.id, interval)
        if not df.empty:
            closes[inst.tradingsymbol] = df.set_index("ts")["close"]
    wide = pd.DataFrame(closes).sort_index()
    _closes_cache[interval] = (time.monotonic(), wide)
    return wide


def load_breadth(db: Session, upto: pd.Timestamp, interval: str = "day") -> pd.DataFrame:
    """Breadth up to `upto`: snapshot days counted over that day's list, earlier days as v1 counts them."""
    legacy = market_context.load_market_breadth(db, interval, upto=upto)
    first = db.execute(select(func.min(WatchlistSnapshot.snapshot_date))).scalar()
    if first is None:
        return legacy  # no snapshot ever recorded: v1's answer, as before
    cut = _ist_day(upto)
    by_day: dict[date, set[str]] = {}
    for day, symbol in db.execute(
        select(WatchlistSnapshot.snapshot_date, WatchlistSnapshot.symbol).where(
            WatchlistSnapshot.snapshot_date <= cut
        )
    ):
        by_day.setdefault(day, set()).add(symbol)
    wide = _snapshot_closes(db, interval)
    wide = wide[wide.index <= upto]
    if wide.empty or not by_day:
        return legacy
    snap_days = sorted(by_day)
    bar_days = np.array([_ist_day(ts) for ts in wide.index])
    # latest snapshot on or before each bar
    which = np.searchsorted(np.array(snap_days), bar_days, side="right") - 1
    member = pd.DataFrame(False, index=wide.index, columns=wide.columns)
    for k, day in enumerate(snap_days):
        cols = [c for c in wide.columns if c in by_day[day]]
        if cols:
            member.loc[which == k, cols] = True
    pit = breadth_with_membership(wide, member)
    before = legacy[[_ist_day(t) < first for t in legacy["ts"]]] if not legacy.empty else legacy
    after = pit[[_ist_day(t) >= first for t in pit["ts"]]]
    parts = [p for p in (before, after) if not p.empty]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=COLUMNS)
