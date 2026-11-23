"""Read-only adapters for consumers that hold a stock under a key `resolve` does not take (#389 slice 2).

Discover and Portfolio keep an `instrument_id`; the watchlist and Groww Tracker keep symbol text; the real and
weekly reports keep symbol text on fills and trades. Each adapter turns that key into the one `security_id`.
Nothing here writes, and none of it changes what a consumer shows: it only answers "which security is this?".
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.core.market_session import IST
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.services.identity import resolve


def security_for_instrument(db: Session, instrument_id: int) -> int | None:
    """Discover, Portfolio (a position's `instrument_id`) and every table keyed on `instruments.id`."""
    row = db.execute(
        select(Instrument.instrument_token, Instrument.tradingsymbol, Instrument.exchange).where(
            Instrument.id == instrument_id
        )
    ).one_or_none()
    if row is None:
        return None
    token, symbol, exchange = row
    # Token and symbol must agree: if they name different securities the answer is None, never the token's.
    return resolve(db, token=token, symbol=symbol, exchange=exchange)


def security_for_symbol(
    db: Session, symbol: str, *, on: date | datetime | None = None, exchange: str = "NSE"
) -> int | None:
    """Watchlist and Groww Tracker rows, fills, trades: symbol text, read as it was on the day the row refers
    to (a datetime is read as that IST day). A row written under an old symbol resolves through the rename."""
    day = on.astimezone(IST).date() if isinstance(on, datetime) else on
    return resolve(db, symbol=symbol, exchange=exchange, on_date=day)
