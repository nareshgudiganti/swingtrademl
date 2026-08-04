"""Historical candles, live quotes, and backfill triggers."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from sqlalchemy import select

from swing_trade_ml.api.deps import DbSession
from swing_trade_ml.brokers import get_broker
from swing_trade_ml.db.models.market import Candle, Instrument, Quote
from swing_trade_ml.db.session import session_scope
from swing_trade_ml.schemas import BackfillRequest, CandleOut, MessageResponse, QuoteOut
from swing_trade_ml.services import ingestion

router = APIRouter(prefix="/market-data", tags=["market-data"])


def _resolve(db, symbol: str, exchange: str = "NSE") -> Instrument:
    instrument = db.execute(
        select(Instrument).where(
            Instrument.tradingsymbol == symbol.upper(), Instrument.exchange == exchange
        )
    ).scalar_one_or_none()
    if instrument is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Unknown instrument {exchange}:{symbol.upper()} — run POST /instruments/sync",
        )
    return instrument


@router.get("/candles/{symbol}", response_model=list[CandleOut])
def get_candles(
    symbol: str,
    db: DbSession,
    interval: str = "day",
    limit: int = Query(500, le=5000),
    exchange: str = "NSE",
) -> list[Candle]:
    """Stored candles, newest last — the order charts and indicators expect."""
    instrument = _resolve(db, symbol, exchange)
    rows = list(
        db.execute(
            select(Candle)
            .where(Candle.instrument_id == instrument.id, Candle.interval == interval)
            .order_by(Candle.ts.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return list(reversed(rows))


@router.get("/quote/{symbol}", response_model=QuoteOut)
def get_quote(symbol: str, db: DbSession, exchange: str = "NSE") -> Quote:
    instrument = _resolve(db, symbol, exchange)
    quote = db.execute(
        select(Quote).where(Quote.instrument_id == instrument.id)
    ).scalar_one_or_none()
    if quote is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "No quote cached yet — the poller runs during market hours, "
            "or call POST /market-data/refresh-quotes",
        )
    return quote


@router.get("/ltp", response_model=dict[str, float])
def get_ltp(
    db: DbSession,
    symbols: str = Query(..., description="Comma-separated, e.g. NSE:INFY,NSE:TCS"),
) -> dict[str, float]:
    keys = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    return get_broker().get_ltp(keys, db)


@router.post("/refresh-quotes", response_model=MessageResponse)
def refresh_quotes(db: DbSession) -> MessageResponse:
    count = ingestion.refresh_quotes(db)
    return MessageResponse(message=f"Refreshed {count} quotes")


@router.post("/backfill", response_model=MessageResponse, status_code=status.HTTP_202_ACCEPTED)
def backfill(payload: BackfillRequest, background: BackgroundTasks) -> MessageResponse:
    """Fetch historical candles.

    Always backgrounded: five years of daily bars across a 10-symbol watchlist
    takes minutes once Kite's rate limit is respected, far past any sensible
    HTTP timeout.
    """

    def _run() -> None:
        with session_scope() as db:
            if payload.symbols:
                for symbol in payload.symbols:
                    instrument = db.execute(
                        select(Instrument).where(Instrument.tradingsymbol == symbol.upper())
                    ).scalar_one_or_none()
                    if instrument:
                        ingestion.backfill_instrument(
                            db, instrument, payload.interval, payload.days, payload.incremental
                        )
            else:
                ingestion.backfill_watchlist(
                    db, payload.interval, payload.days, payload.incremental
                )

    background.add_task(_run)
    target = ", ".join(payload.symbols) if payload.symbols else "the full watchlist"
    return MessageResponse(
        message=f"Backfill started for {target}",
        detail="This can take several minutes; watch the server logs for progress.",
    )


@router.get("/coverage", response_model=list[dict])
def coverage(db: DbSession, interval: str = "day") -> list[dict]:
    """Per-symbol candle counts and date ranges.

    The first thing to check when training complains about insufficient data.
    """
    from sqlalchemy import func

    rows = db.execute(
        select(
            Instrument.tradingsymbol,
            # candles has a composite natural key and no surrogate id column
            func.count(),
            func.min(Candle.ts),
            func.max(Candle.ts),
        )
        .join(Candle, Candle.instrument_id == Instrument.id)
        .where(Candle.interval == interval, Instrument.is_watchlisted.is_(True))
        .group_by(Instrument.tradingsymbol)
        .order_by(Instrument.tradingsymbol)
    ).all()

    return [
        {
            "symbol": symbol,
            "candles": count,
            "from": start.date().isoformat() if start else None,
            "to": end.date().isoformat() if end else None,
        }
        for symbol, count, start, end in rows
    ]
