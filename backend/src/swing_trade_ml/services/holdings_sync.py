"""Keep the tracked My Holdings book honest about what is actually owned.

Importing holdings only ever added rows, so a stock sold by hand in Zerodha
stayed OPEN in this app forever: it kept getting a daily model read, kept
breaching its stop, and kept raising both a Telegram alert and a "needs
attention" row for shares nobody held. Found live on 2026-09-28 — three of the
nine rows the app was asking the owner to act on had already been sold.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.core.enums import ExitReason, PositionStatus
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Position, Strategy
from swing_trade_ml.services.execution import manual_close_position

log = get_logger(__name__)


def held_quantity(holding: dict[str, Any]) -> int:
    """Shares actually owned, including ones bought in the last day or two
    that have not settled into demat yet.

    Kite's `quantity` is the *settled* (T+1) figure only — a stock bought
    today or yesterday sits entirely in `t1_quantity` and reads as
    `quantity: 0`. Counting only `quantity` would read a fresh buy as a
    holding that had been sold, and close it.
    """
    return holding["quantity"] + holding.get("t1_quantity", 0)


def held_symbols(holdings: list[dict[str, Any]]) -> set[str]:
    """The symbols genuinely owned right now, from raw Kite holdings."""
    return {h["tradingsymbol"] for h in holdings if held_quantity(h) != 0}


def close_positions_no_longer_held(
    db: Session, strategy: Strategy, held_symbols: set[str]
) -> list[dict[str, Any]]:
    """Close every OPEN position of `strategy` whose symbol is absent from
    `held_symbols` (the broker's own current holdings).

    The exit price is the last price this app saw: the real fill price is not
    knowable from the holdings endpoint, because the sale is simply gone from
    it. That is an estimate, and it is recorded as a MANUAL close so it reads
    as one — the alternative, leaving the row open, states something false
    about what is owned and keeps acting on it.

    Caller supplies `held_symbols` rather than this reaching for the broker
    itself, so a caller that already loaded holdings does not load them twice
    and an empty/failed load can never be mistaken for "everything was sold".
    """
    closed: list[dict[str, Any]] = []
    open_positions = db.execute(
        select(Position).where(
            Position.strategy_id == strategy.id, Position.status == PositionStatus.OPEN
        )
    ).scalars()

    for position in list(open_positions):
        instrument = db.get(Instrument, position.instrument_id)
        if instrument is None or instrument.tradingsymbol in held_symbols:
            continue
        exit_price = float(position.current_price or position.entry_price)
        manual_close_position(db, position, exit_price, ExitReason.MANUAL)
        log.info(
            "holdings_sync.closed_not_held",
            symbol=instrument.tradingsymbol,
            exit_price=exit_price,
        )
        closed.append(
            {
                "symbol": instrument.tradingsymbol,
                "status": "closed_not_held",
                "exit_price": exit_price,
                "reason": (
                    "no longer in your Zerodha holdings — closed at the last price this app "
                    "saw, so it stops being tracked and alerted on. Correct the exit price "
                    "from My Holdings if it matters."
                ),
            }
        )
    return closed
