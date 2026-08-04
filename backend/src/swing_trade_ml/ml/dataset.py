"""Turn stored candles into a supervised learning dataset."""

from __future__ import annotations

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.ml.features import FEATURE_COLUMNS, build_features, build_label

log = get_logger(__name__)


def load_candles(
    db: Session, instrument_id: int, interval: str = "day", limit: int | None = None
) -> pd.DataFrame:
    """Read candles ascending by time — the order every indicator assumes."""
    stmt = (
        select(Candle.ts, Candle.open, Candle.high, Candle.low, Candle.close, Candle.volume)
        .where(Candle.instrument_id == instrument_id, Candle.interval == interval)
        .order_by(Candle.ts.asc())
    )
    if limit:
        # Take the newest `limit` bars, then restore ascending order.
        stmt = (
            select(Candle.ts, Candle.open, Candle.high, Candle.low, Candle.close, Candle.volume)
            .where(Candle.instrument_id == instrument_id, Candle.interval == interval)
            .order_by(Candle.ts.desc())
            .limit(limit)
        )
        rows = db.execute(stmt).all()
        rows = list(reversed(rows))
    else:
        rows = db.execute(stmt).all()

    if not rows:
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])

    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df["volume"] = df["volume"].astype("float64")
    return df


def build_training_dataset(
    db: Session,
    symbols: list[str] | None = None,
    interval: str = "day",
    horizon_days: int = 5,
    target_return: float = 0.02,
    min_rows: int = 300,
) -> pd.DataFrame:
    """Pool features and labels across instruments into one training frame.

    Training on many symbols at once is deliberate. A per-symbol model has a few
    thousand rows at best and overfits that symbol's recent regime; a pooled
    model learns patterns that generalise, which is the only kind worth trading.
    `symbol` and `ts` are carried through — not as features, but so the split
    can be made chronologically and errors traced back to a specific bar.
    """
    stmt = select(Instrument).where(Instrument.is_active.is_(True))
    if symbols:
        stmt = stmt.where(Instrument.tradingsymbol.in_([s.upper() for s in symbols]))
    else:
        stmt = stmt.where(Instrument.is_watchlisted.is_(True))

    instruments = list(db.execute(stmt).scalars().all())
    if not instruments:
        log.warning("dataset.no_instruments")
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    for inst in instruments:
        raw = load_candles(db, inst.id, interval)
        # Long moving averages need ~200 bars before any row is usable; a short
        # series would contribute only NaNs.
        if len(raw) < min_rows:
            log.debug("dataset.skip_short", symbol=inst.tradingsymbol, rows=len(raw))
            continue

        featured = build_features(raw)
        labelled = build_label(featured, horizon_days, target_return)
        labelled = labelled.dropna(subset=[*FEATURE_COLUMNS, "target"])
        if labelled.empty:
            continue

        labelled["symbol"] = inst.tradingsymbol
        labelled["instrument_id"] = inst.id
        frames.append(
            labelled[[*FEATURE_COLUMNS, "target", "forward_return", "symbol", "instrument_id", "ts"]]
        )

    if not frames:
        log.warning("dataset.empty", instruments=len(instruments))
        return pd.DataFrame()

    dataset = pd.concat(frames, ignore_index=True).sort_values("ts").reset_index(drop=True)
    log.info(
        "dataset.built",
        rows=len(dataset),
        symbols=dataset["symbol"].nunique(),
        positive_rate=round(float(dataset["target"].mean()), 4),
    )
    return dataset


def chronological_split(dataset: pd.DataFrame, test_size: float = 0.2) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split by time, never randomly.

    A random split lets the model train on next Tuesday and test on last
    Monday. With overlapping forward-return labels the leakage is severe, and
    the resulting accuracy is fiction. Splitting on a date reproduces the only
    situation that matters: predicting a future the model has never seen.
    """
    if dataset.empty:
        return dataset, dataset
    cutoff = int(len(dataset) * (1 - test_size))
    return dataset.iloc[:cutoff].copy(), dataset.iloc[cutoff:].copy()
