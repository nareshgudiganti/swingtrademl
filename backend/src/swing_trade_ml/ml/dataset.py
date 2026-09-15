"""Turn stored candles into a supervised learning dataset."""

from __future__ import annotations

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.ml.features import FEATURE_COLUMNS, build_features, build_label
from swing_trade_ml.ml.market_context import (
    load_index_candles,
    load_market_breadth,
    load_sector_candles,
    load_vix_candles,
)
from swing_trade_ml.ml.sector_map import get_sector_index

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
    horizon_days: int = 15,
    target_return: float = 0.08,
    stop_return: float = 0.04,
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

    # Loaded once, outside the loop — the same benchmark/VIX/breadth history
    # joins onto every symbol, and this is real historical training data (not
    # a simulated "as of" date), so no upto bound is needed here. Sector
    # history is also cached per sector after its first fetch, so pooling
    # many symbols from the same sector costs one load, not one per symbol.
    index_df = load_index_candles(db, interval)
    vix_df = load_vix_candles(db, interval)
    breadth_df = load_market_breadth(db, interval)

    frames: list[pd.DataFrame] = []
    for inst in instruments:
        raw = load_candles(db, inst.id, interval)
        # Long moving averages need ~200 bars before any row is usable; a short
        # series would contribute only NaNs.
        if len(raw) < min_rows:
            log.debug("dataset.skip_short", symbol=inst.tradingsymbol, rows=len(raw))
            continue

        sector_df = load_sector_candles(db, get_sector_index(inst.tradingsymbol), interval)
        featured = build_features(raw, index_df, sector_df, vix_df, breadth_df)
        labelled = build_label(featured, horizon_days, target_return, stop_return)
        labelled = labelled.dropna(subset=[*FEATURE_COLUMNS, "target"])
        if labelled.empty:
            continue

        labelled["symbol"] = inst.tradingsymbol
        labelled["instrument_id"] = inst.id
        frames.append(
            labelled[[*FEATURE_COLUMNS, "target", "forward_return", "label_end_ts", "symbol", "instrument_id", "ts"]]
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


def chronological_split(
    dataset: pd.DataFrame, test_size: float = 0.2, embargo_days: int = 0
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split by time, never randomly, and purge every training row whose
    label window reaches into the test period.

    A random split lets the model train on next Tuesday and test on last
    Monday. With overlapping forward-return labels the leakage is severe, and
    the resulting accuracy is fiction. Splitting on a date reproduces the only
    situation that matters: predicting a future the model has never seen.

    The cut lands on a date boundary, not a row count — the pooled frame
    holds one row per symbol per bar, so a positional cut can put half of one
    day's symbols in train and the other half in test.

    Purging prefers the exact per-row `label_end_ts` (the barrier label's own
    forward-window boundary, stamped by build_label) when the dataset carries
    it — every frame build_training_dataset produces does, and it is exact
    regardless of horizon_days, unlike counting a fixed number of dates.
    `embargo_days` (drop the last N distinct trading dates instead) is the
    fallback for a frame that predates that column — a synthetic one in a
    test, say — where it should be set to the label horizon.

    The two purges disagree deliberately on what an empty training set after
    purging means. With `label_end_ts` there is a real answer being purged
    away, so an empty result means "no usable data" — a hard error. Without
    it, `embargo_days` is a blunter, caller-supplied instrument that can
    legitimately be asked for more embargo than the data has; returning an
    empty frame lets a caller who wants to see that happen see it.
    """
    if not 0 < test_size < 1:
        raise ValueError("test_size must be strictly between 0 and 1")
    if dataset.empty:
        return dataset, dataset

    ordered = dataset.sort_values("ts", kind="stable")
    timestamps = ordered["ts"].drop_duplicates().sort_values()
    cutoff = int(len(timestamps) * (1 - test_size))
    if cutoff < 1 or cutoff >= len(timestamps):
        raise ValueError("Insufficient timestamps for a chronological split; ingest more history")
    test_start = timestamps.iloc[cutoff]
    before = ordered[ordered["ts"] < test_start]
    test = ordered[ordered["ts"] >= test_start].copy()

    if "label_end_ts" in ordered.columns:
        train = before[before["label_end_ts"] < test_start].copy()
        if train.empty or test.empty:
            raise ValueError(
                "No usable rows after label-window purging; ingest more history or shorten the horizon"
            )
        train.attrs["split"] = {
            "method": "timestamp_purged",
            "train_start": train["ts"].min().isoformat(),
            "train_end": train["ts"].max().isoformat(),
            "test_start": test_start.isoformat(),
            "test_end": test["ts"].max().isoformat(),
            "purged_rows": len(before) - len(train),
        }
        return train, test

    return apply_embargo(before, embargo_days).copy(), test


def apply_embargo(train_df: pd.DataFrame, embargo_days: int) -> pd.DataFrame:
    """Drop the last `embargo_days` distinct dates of an already-cut train frame.

    Counted in distinct dates present in the data, not calendar days — a label
    horizon is measured in trading bars, and weekends and holidays have none.
    The fallback purge for a frame with no `label_end_ts` column; see
    chronological_split.
    """
    if embargo_days <= 0 or train_df.empty:
        return train_df
    dates = train_df["ts"].drop_duplicates().sort_values()
    if embargo_days >= len(dates):
        return train_df.iloc[0:0]
    first_embargoed = dates.iloc[-embargo_days]
    return train_df[train_df["ts"] < first_embargoed]
