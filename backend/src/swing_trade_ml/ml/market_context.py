"""The NIFTY 50 benchmark's own candle history, cached in memory.

Every relative-strength/regime feature needs this same data, and it's
identical across all 49 watchlisted symbols on a given day — fetching it
fresh per instrument per call would mean up to ~49,000 extra DB queries
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

_index_cache: dict[str, pd.DataFrame] = {}


def clear_cache() -> None:
    _index_cache.clear()


def load_index_candles(
    db: Session, interval: str = "day", upto: pd.Timestamp | None = None
) -> pd.DataFrame:
    """The benchmark index's OHLCV history, ascending by ts, optionally
    bounded to `ts <= upto`.

    `upto` is how look-ahead safety is enforced for callers evaluating a
    specific historical "as of" date (live scanning and backtest both pass
    the max ts of their own already-safe instrument window) — the underlying
    fetch always loads the FULL cached history, so bounding happens by
    slicing in memory, not by re-querying with a different range each time.
    """
    if interval not in _index_cache:
        # Deferred import: ml.dataset also imports this module (to fetch the
        # index frame for training), so a module-level import here would be
        # circular.
        from swing_trade_ml.ml.dataset import load_candles

        instrument = db.execute(
            select(Instrument).where(Instrument.tradingsymbol == settings.BENCHMARK_INDEX_SYMBOL)
        ).scalar_one_or_none()
        if instrument is None:
            log.warning(
                "market_context.index_not_found", symbol=settings.BENCHMARK_INDEX_SYMBOL
            )
            _index_cache[interval] = pd.DataFrame(
                columns=["ts", "open", "high", "low", "close", "volume"]
            )
        else:
            _index_cache[interval] = load_candles(db, instrument.id, interval)

    full = _index_cache[interval]
    if upto is None or full.empty:
        return full
    return full[full["ts"] <= upto].reset_index(drop=True)
