"""Market data ingestion: instrument master, historical backfill, live quotes.

Kite rate-limits historical requests to roughly 3/second and caps each call's
date span by interval. Both constraints are handled here so callers can request
"five years of daily bars" without knowing either.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from swing_trade_ml.brokers.kite import kite_broker
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.holidays import is_trading_holiday
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.market import Candle, Instrument, Quote

log = get_logger(__name__)

IST = ZoneInfo("Asia/Kolkata")

# Kite's per-request span limit by interval, in calendar days. Exceeding these
# returns an error rather than truncated data, so a long backfill must be
# chunked into windows this size.
MAX_DAYS_PER_REQUEST: dict[str, int] = {
    "minute": 60,
    "3minute": 100,
    "5minute": 100,
    "10minute": 100,
    "15minute": 200,
    "30minute": 200,
    "60minute": 400,
    "day": 2000,
}

# Kite allows ~3 historical calls/second; 0.35s keeps a margin.
RATE_LIMIT_SLEEP = 0.35


def is_market_open(now: datetime | None = None) -> bool:
    """NSE equity session check: weekday, clock, and known holidays.

    A holiday not yet in core.holidays.NSE_HOLIDAYS still degrades safely —
    the session just looks open and an ingestion run finds no new bars.
    """
    now = (now or datetime.now(UTC)).astimezone(IST)
    if now.weekday() >= 5:
        return False
    if is_trading_holiday(now.date()):
        return False
    return settings.market_open <= now.time() <= settings.market_close


def sync_instruments(db: Session, exchange: str = "NSE", equity_only: bool = True) -> int:
    """Refresh the instrument master from Kite's daily dump.

    Instrument tokens are reassigned on corporate actions, so this must be
    re-run periodically or historical requests start failing on stale tokens.
    """
    log.info("ingestion.instruments.start", exchange=exchange)
    raw = kite_broker.get_instruments(exchange)

    rows = []
    for item in raw:
        if equity_only and item.get("instrument_type") != "EQ":
            continue
        rows.append(
            {
                "instrument_token": item["instrument_token"],
                "exchange_token": item.get("exchange_token"),
                "tradingsymbol": item["tradingsymbol"],
                "name": item.get("name"),
                "exchange": item.get("exchange", exchange),
                "segment": item.get("segment"),
                "instrument_type": item.get("instrument_type"),
                "lot_size": item.get("lot_size") or 1,
                "tick_size": item.get("tick_size") or 0.05,
                "expiry": item.get("expiry") or None,
            }
        )

    if not rows:
        log.warning("ingestion.instruments.empty", exchange=exchange)
        return 0

    # Postgres caps a single query at 65535 bind parameters. NSE's "EQ" dump
    # (main board + SME + ETFs, all typed EQ) comfortably exceeds
    # 65535 / 10 columns ≈ 6553 rows in one INSERT, so this must be batched —
    # a single-statement bulk insert broke outright the first time this ran
    # against a real Kite instrument dump.
    batch_size = 3000
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        # Upsert on instrument_token: the same symbol may reappear with
        # updated metadata, and is_watchlisted must survive the refresh.
        stmt = pg_insert(Instrument).values(batch)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Instrument.instrument_token],
            set_={
                "tradingsymbol": stmt.excluded.tradingsymbol,
                "name": stmt.excluded.name,
                "segment": stmt.excluded.segment,
                "lot_size": stmt.excluded.lot_size,
                "tick_size": stmt.excluded.tick_size,
                "is_active": True,
            },
        )
        db.execute(stmt)
    db.commit()

    log.info("ingestion.instruments.done", exchange=exchange, count=len(rows))
    return len(rows)


def set_watchlist(db: Session, symbols: list[str], exchange: str = "NSE") -> list[str]:
    """Mark exactly these symbols as watchlisted, clearing any previous set."""
    db.query(Instrument).filter(Instrument.is_watchlisted.is_(True)).update(
        {"is_watchlisted": False}
    )

    wanted = [s.strip().upper() for s in symbols if s.strip()]
    matched = list(
        db.execute(
            select(Instrument).where(
                Instrument.tradingsymbol.in_(wanted), Instrument.exchange == exchange
            )
        )
        .scalars()
        .all()
    )
    for inst in matched:
        inst.is_watchlisted = True
    db.commit()

    found = {i.tradingsymbol for i in matched}
    missing = sorted(set(wanted) - found)
    if missing:
        log.warning("ingestion.watchlist.unmatched", symbols=missing)
    log.info("ingestion.watchlist.set", count=len(matched))
    return sorted(found)


def ensure_benchmark_index(db: Session, exchange: str = "NSE") -> Instrument:
    """Get (or create) the Instrument row for settings.BENCHMARK_INDEX_SYMBOL.

    Deliberately bypasses sync_instruments()/equity_only: Kite's own dump
    reports the index with instrument_type="EQ" (confirmed live — same value
    every real equity carries), so that filter can't distinguish it. Matched
    by exact tradingsymbol instead, which is unambiguous.

    Never watchlisted — is_watchlisted drives every automatic backfill/scan/
    training instrument loop in this codebase, and this index is a feature
    input, not a trading candidate.
    """
    symbol = settings.BENCHMARK_INDEX_SYMBOL
    existing = db.execute(
        select(Instrument).where(
            Instrument.tradingsymbol == symbol, Instrument.exchange == exchange
        )
    ).scalar_one_or_none()
    if existing is not None:
        # A prior plain sync-instruments run may already have this row —
        # Kite's own instrument_type for an index is an unhelpful "EQ" (same
        # as every real equity), so a row created that way needs correcting
        # rather than trusted as-is. Also guard against a stale accidental
        # watchlisting the same way.
        changed = False
        if existing.instrument_type != "INDEX":
            existing.instrument_type = "INDEX"
            changed = True
        if existing.is_watchlisted:
            existing.is_watchlisted = False
            changed = True
        if changed:
            db.commit()
            db.refresh(existing)
        return existing

    raw = kite_broker.get_instruments(exchange)
    match = next((item for item in raw if item.get("tradingsymbol") == symbol), None)
    if match is None:
        raise ValueError(f"'{symbol}' not found in Kite's {exchange} instrument dump")

    instrument = Instrument(
        instrument_token=match["instrument_token"],
        exchange_token=match.get("exchange_token"),
        tradingsymbol=symbol,
        name=match.get("name"),
        exchange=match.get("exchange", exchange),
        segment=match.get("segment"),
        # Distinct from Kite's own (unhelpful) "EQ" value, so any future
        # instrument_type != "INDEX" guard doesn't depend on Kite's quirk.
        instrument_type="INDEX",
        lot_size=match.get("lot_size") or 1,
        tick_size=match.get("tick_size") or 0.05,
        is_watchlisted=False,
        is_active=True,
    )
    db.add(instrument)
    db.commit()
    db.refresh(instrument)
    log.info("ingestion.benchmark_index.created", symbol=symbol, token=instrument.instrument_token)
    return instrument


def backfill_index(db: Session, interval: str = "day", days: int | None = None) -> int:
    """Top up the benchmark index's own candle history — same mechanics as a
    regular instrument (backfill_instrument doesn't check is_watchlisted),
    just reached by a dedicated call since this index is never watchlisted."""
    instrument = ensure_benchmark_index(db)
    return backfill_instrument(db, instrument, interval, days, incremental=True)


def _upsert_candles(db: Session, instrument_id: int, interval: str, bars: list[dict]) -> int:
    """Insert bars, updating any that already exist.

    Backfill windows overlap by design (the last stored bar is re-requested to
    catch a partially-formed candle), so this must be idempotent.
    """
    if not bars:
        return 0

    rows = [
        {
            "instrument_id": instrument_id,
            "interval": interval,
            "ts": bar["date"],
            "open": float(bar["open"]),
            "high": float(bar["high"]),
            "low": float(bar["low"]),
            "close": float(bar["close"]),
            "volume": int(bar.get("volume") or 0),
        }
        for bar in bars
    ]

    stmt = pg_insert(Candle).values(rows)
    stmt = stmt.on_conflict_do_update(
        # Conflict target is the primary key (instrument_id, interval, ts).
        index_elements=["instrument_id", "interval", "ts"],
        set_={
            "open": stmt.excluded.open,
            "high": stmt.excluded.high,
            "low": stmt.excluded.low,
            "close": stmt.excluded.close,
            "volume": stmt.excluded.volume,
        },
    )
    db.execute(stmt)
    db.commit()
    return len(rows)


def backfill_instrument(
    db: Session,
    instrument: Instrument,
    interval: str = "day",
    days: int | None = None,
    incremental: bool = True,
) -> int:
    """Fetch history for one instrument, chunked to respect Kite's span limits.

    With `incremental`, only the gap since the newest stored bar is requested —
    a daily top-up costs one small call instead of re-downloading five years.
    """
    days = days or settings.HISTORICAL_BACKFILL_DAYS
    to_date = datetime.now(IST)
    from_date = to_date - timedelta(days=days)

    if incremental:
        latest = db.execute(
            select(Candle.ts)
            .where(Candle.instrument_id == instrument.id, Candle.interval == interval)
            .order_by(Candle.ts.desc())
            .limit(1)
        ).scalar_one_or_none()
        if latest is not None:
            # Step back a day so the most recent (possibly incomplete) bar is
            # re-fetched and corrected rather than left stale.
            from_date = max(from_date, latest.astimezone(IST) - timedelta(days=1))

    if from_date >= to_date:
        return 0

    chunk_days = MAX_DAYS_PER_REQUEST.get(interval, 200)
    total = 0
    cursor = from_date

    while cursor < to_date:
        window_end = min(cursor + timedelta(days=chunk_days), to_date)
        try:
            bars = kite_broker.get_historical_data(
                instrument.instrument_token, cursor, window_end, interval, db
            )
        except Exception as exc:  # noqa: BLE001 — skip this window, keep the rest
            log.error(
                "ingestion.backfill.window_failed",
                symbol=instrument.tradingsymbol,
                start=cursor.date().isoformat(),
                error=str(exc),
            )
            cursor = window_end
            continue

        total += _upsert_candles(db, instrument.id, interval, bars)
        cursor = window_end
        time.sleep(RATE_LIMIT_SLEEP)

    log.info(
        "ingestion.backfill.done",
        symbol=instrument.tradingsymbol,
        interval=interval,
        bars=total,
    )
    return total


def backfill_watchlist(
    db: Session, interval: str = "day", days: int | None = None, incremental: bool = True
) -> dict[str, int]:
    """Backfill every watchlisted instrument. Long-running — call as a job."""
    instruments = list(
        db.execute(select(Instrument).where(Instrument.is_watchlisted.is_(True)))
        .scalars()
        .all()
    )
    if not instruments:
        log.warning("ingestion.backfill.no_watchlist")
        return {}

    return _backfill_many(db, instruments, interval, days, incremental)


def backfill_symbols(
    db: Session, symbols: list[str], interval: str = "day",
    days: int | None = None, incremental: bool = True,
) -> dict[str, int]:
    """Backfill an explicit symbol list, independent of the watchlist flag —
    the daily top-up for a strategy that deliberately keeps its own
    instruments unwatchlisted (see strategies/ml_swing.py's model_name param
    and the mid-cap strategy, which stays out of every is_watchlisted=True
    path — predict_watchlist/Recommendations, refresh_quotes, coverage — on
    purpose, so it's never scored with the wrong model)."""
    wanted = [s.strip().upper() for s in symbols if s.strip()]
    instruments = list(
        db.execute(select(Instrument).where(Instrument.tradingsymbol.in_(wanted)))
        .scalars()
        .all()
    )
    if not instruments:
        log.warning("ingestion.backfill.no_symbols_matched", symbols=wanted)
        return {}

    return _backfill_many(db, instruments, interval, days, incremental)


def _backfill_many(
    db: Session, instruments: list[Instrument], interval: str,
    days: int | None, incremental: bool,
) -> dict[str, int]:
    results: dict[str, int] = {}
    for inst in instruments:
        try:
            results[inst.tradingsymbol] = backfill_instrument(db, inst, interval, days, incremental)
        except Exception as exc:  # noqa: BLE001
            log.error("ingestion.backfill.failed", symbol=inst.tradingsymbol, error=str(exc))
            results[inst.tradingsymbol] = 0

    log.info("ingestion.backfill.batch_done", instruments=len(results), bars=sum(results.values()))
    return results


def refresh_quotes(db: Session) -> int:
    """Poll live quotes for the watchlist into the `quotes` table.

    One row per instrument, updated in place — this is the "what is it worth
    right now" source for mark-to-market and the dashboard.
    """
    if not kite_broker.is_authenticated:
        log.debug("ingestion.quotes.no_session")
        return 0

    instruments = list(
        db.execute(select(Instrument).where(Instrument.is_watchlisted.is_(True)))
        .scalars()
        .all()
    )
    if not instruments:
        return 0

    by_key = {i.symbol_key: i for i in instruments}
    try:
        quotes = kite_broker.get_quote(list(by_key), db)
    except Exception as exc:  # noqa: BLE001
        log.error("ingestion.quotes.failed", error=str(exc))
        return 0

    now = datetime.now(UTC)
    rows = []
    for key, data in quotes.items():
        inst = by_key.get(key)
        if inst is None:
            continue
        ohlc = data.get("ohlc", {})
        prev_close = ohlc.get("close") or 0
        last_price = float(data.get("last_price", 0))
        rows.append(
            {
                "instrument_id": inst.id,
                "last_price": last_price,
                "open": ohlc.get("open"),
                "high": ohlc.get("high"),
                "low": ohlc.get("low"),
                "close": prev_close,
                "volume": data.get("volume"),
                "change_pct": ((last_price / prev_close - 1) * 100) if prev_close else None,
                "ts": now,
            }
        )

    if not rows:
        return 0

    stmt = pg_insert(Quote).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Quote.instrument_id],
        set_={
            "last_price": stmt.excluded.last_price,
            "open": stmt.excluded.open,
            "high": stmt.excluded.high,
            "low": stmt.excluded.low,
            "close": stmt.excluded.close,
            "volume": stmt.excluded.volume,
            "change_pct": stmt.excluded.change_pct,
            "ts": stmt.excluded.ts,
        },
    )
    db.execute(stmt)
    db.commit()

    log.info("ingestion.quotes.refreshed", count=len(rows))
    return len(rows)
