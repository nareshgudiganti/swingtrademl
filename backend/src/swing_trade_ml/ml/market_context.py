"""Shared market-wide context: the benchmark index, sector indices, INDIA VIX,
and cross-sectional watchlist breadth — all cached in memory.

Every relative-strength/regime/breadth feature needs one of these, and each is
identical across every symbol that shares it on a given day — fetching any of
them fresh per instrument per call would mean thousands of extra DB queries
across a multi-year backtest for data that never changes within one process
lifetime (except the trailing edge, which a fresh cache load picks up).

Mirrors the `_artifact_cache`/`clear_cache()` pattern already established in
ml/predict.py.
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.market import Instrument

log = get_logger(__name__)

# Keyed by (tradingsymbol, interval) — covers the benchmark, every sector
# index, and INDIA VIX with one cache and one code path.
_symbol_cache: dict[tuple[str, str], pd.DataFrame] = {}
# Keyed by interval only — one breadth series per interval, computed across
# the full watchlist.
_breadth_cache: dict[str, pd.DataFrame] = {}


def clear_cache() -> None:
    _symbol_cache.clear()
    _breadth_cache.clear()


def load_symbol_candles(
    db: Session, symbol: str, interval: str = "day", upto: pd.Timestamp | None = None
) -> pd.DataFrame:
    """One index-like instrument's OHLCV history (benchmark, a sector index,
    or INDIA VIX), ascending by ts, optionally bounded to `ts <= upto`.

    `upto` is how look-ahead safety is enforced for callers evaluating a
    specific historical "as of" date (live scanning and backtest both pass
    the max ts of their own already-safe instrument window) — the underlying
    fetch always loads the FULL cached history, so bounding happens by
    slicing in memory, not by re-querying with a different range each time.
    """
    key = (symbol, interval)
    if key not in _symbol_cache:
        # Deferred import: ml.dataset also imports this module (to fetch
        # these frames for training), so a module-level import here would be
        # circular.
        from swing_trade_ml.ml.dataset import load_candles

        instrument = db.execute(
            select(Instrument).where(Instrument.tradingsymbol == symbol)
        ).scalar_one_or_none()
        if instrument is None:
            log.warning("market_context.symbol_not_found", symbol=symbol)
            _symbol_cache[key] = pd.DataFrame(
                columns=["ts", "open", "high", "low", "close", "volume"]
            )
        else:
            _symbol_cache[key] = load_candles(db, instrument.id, interval)

    full = _symbol_cache[key]
    if upto is None or full.empty:
        return full
    return full[full["ts"] <= upto].reset_index(drop=True)


def load_index_candles(
    db: Session, interval: str = "day", upto: pd.Timestamp | None = None
) -> pd.DataFrame:
    """The primary benchmark's own candle history — settings.BENCHMARK_INDEX_SYMBOL."""
    return load_symbol_candles(db, settings.BENCHMARK_INDEX_SYMBOL, interval, upto)


def load_sector_candles(
    db: Session, sector_symbol: str, interval: str = "day", upto: pd.Timestamp | None = None
) -> pd.DataFrame:
    """One sector index's own candle history — see ml.sector_map.get_sector_index()
    for how a stock's sector_symbol is chosen."""
    return load_symbol_candles(db, sector_symbol, interval, upto)


def load_vix_candles(
    db: Session, interval: str = "day", upto: pd.Timestamp | None = None
) -> pd.DataFrame:
    """INDIA VIX's own candle history — a macro/regime feature input, not a
    trading candidate."""
    return load_symbol_candles(db, "INDIA VIX", interval, upto)


def load_market_breadth(
    db: Session, interval: str = "day", upto: pd.Timestamp | None = None
) -> pd.DataFrame:
    """Cross-sectional breadth across the watchlist: what fraction of
    watchlisted stocks are above their own 50-day SMA, and what fraction
    advanced (closed up) on the day, per day.

    Zero-cost relative to sector/VIX/index features — it needs no new
    instrument, only the candles already ingested for the watchlist — and it
    answers a question no single stock's own indicators can: is the *market*
    broadly participating in a move, or is one stock rallying while most of
    its peers aren't.

    Deliberately built from watchlist candles rather than an index's own
    advance/decline count (Kite exposes no such series directly), so this is
    an approximation scoped to this app's own universe, not the full NSE.
    """
    if interval not in _breadth_cache:
        from swing_trade_ml.ml.dataset import load_candles

        instruments = list(
            db.execute(select(Instrument).where(Instrument.is_watchlisted.is_(True)))
            .scalars()
            .all()
        )
        closes: dict[str, pd.Series] = {}
        for inst in instruments:
            df = load_candles(db, inst.id, interval)
            if df.empty:
                continue
            closes[inst.tradingsymbol] = df.set_index("ts")["close"]

        if not closes:
            log.warning("market_context.breadth_no_watchlist")
            _breadth_cache[interval] = pd.DataFrame(
                columns=["ts", "breadth_pct_above_sma50", "breadth_advance_pct"]
            )
        else:
            # Outer-joined on ts: a listing gap or missing bar in one symbol
            # must not drop that day for every other symbol. NaN entries are
            # excluded from that day's mean via skipna, not treated as "below
            # SMA" or "declined".
            wide = pd.DataFrame(closes).sort_index()
            above_sma = wide > wide.rolling(50, min_periods=50).mean()
            advanced = wide.diff() > 0
            _breadth_cache[interval] = pd.DataFrame(
                {
                    "ts": wide.index,
                    "breadth_pct_above_sma50": above_sma.mean(axis=1, skipna=True).to_numpy(),
                    "breadth_advance_pct": advanced.mean(axis=1, skipna=True).to_numpy(),
                }
            ).reset_index(drop=True)

    full = _breadth_cache[interval]
    if upto is None or full.empty:
        return full
    return full[full["ts"] <= upto].reset_index(drop=True)


def classify_regime(close: pd.Series) -> dict:
    """Pure: trend regime + volatility level from a benchmark close-price
    series. No DB — fully testable on a synthetic Series.

    Same formulas ml/features.py's _index_context_frame already computes as
    model features (nifty_trend_regime, nifty_volatility_20) — this just
    exposes the latest value directly, human-readably, rather than leaving
    it buried inside a training column nobody outside the model ever sees.
    """
    if len(close) < 200:
        return {
            "regime": "unknown",
            "volatility_level": "unknown",
            "nifty_close": None,
            "sma_50": None,
            "sma_200": None,
        }

    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    trend_regime = "bullish" if float(sma50.iloc[-1]) >= float(sma200.iloc[-1]) else "bearish"

    vol20 = close.pct_change().rolling(20).std() * (252**0.5)
    if vol20.dropna().shape[0] < 252:
        volatility_level = "unknown"
    else:
        percentile = float(vol20.rolling(252).rank(pct=True).iloc[-1])
        if percentile >= 0.75:
            volatility_level = "elevated"
        elif percentile <= 0.25:
            volatility_level = "low"
        else:
            volatility_level = "normal"

    return {
        "regime": trend_regime,
        "volatility_level": volatility_level,
        "nifty_close": float(close.iloc[-1]),
        "sma_50": float(sma50.iloc[-1]),
        "sma_200": float(sma200.iloc[-1]),
    }


def current_regime(db: Session, interval: str = "day") -> dict:
    """A human-readable read of the broad market right now, for the
    dashboard — not a new signal, just surfacing what the model already
    computes internally as a feature."""
    index_df = load_index_candles(db, interval)
    close = index_df["close"] if not index_df.empty else pd.Series(dtype=float)
    result = classify_regime(close)
    result["as_of"] = index_df["ts"].iloc[-1].isoformat() if not index_df.empty else None
    return result
