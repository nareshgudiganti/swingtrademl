"""The stocks the brain looks at: the watchlist plus every stock version 1's
active auto-trading strategies scan, so the brain and version 1 are judged on
the same ground. Advisory trackers (e.g. real_trading) and staged strategies
(the brain itself) do not add stocks. Only known, active instruments count."""

from __future__ import annotations

from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from swing_trade_ml.core.strategy_policy import STAGED_TYPES
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Strategy
from swing_trade_ml.services.watchlist_snapshots import watchlist_as_of


def _strategy_scan_symbols(db: Session) -> tuple[str, ...]:
    lists = db.execute(
        select(Strategy.symbols).where(
            Strategy.is_active.is_(True),
            Strategy.execution_mode == "auto",
            Strategy.strategy_type.not_in(sorted(STAGED_TYPES)),
        )
    ).scalars()
    return tuple(sorted({s.upper() for symbols in lists for s in (symbols or [])}))


def brain_universe_live(db: Session) -> tuple[str, ...]:
    scanned = _strategy_scan_symbols(db)
    rows = db.execute(
        select(Instrument.tradingsymbol)
        .where(
            Instrument.is_active.is_(True),
            or_(Instrument.is_watchlisted.is_(True), Instrument.tradingsymbol.in_(scanned)),
        )
        .order_by(Instrument.tradingsymbol)
    ).scalars()
    return tuple(dict.fromkeys(rows))


def brain_universe(db: Session, *, as_of: date | None = None) -> tuple[str, ...]:
    """Live universe today, or point-in-time list for replays when `as_of` is set."""
    if as_of is None:
        return brain_universe_live(db)
    scanned = _strategy_scan_symbols(db)
    snap = set(watchlist_as_of(db, as_of))
    if not snap and not scanned:
        return ()
    rows = db.execute(
        select(Instrument.tradingsymbol)
        .where(
            Instrument.is_active.is_(True),
            or_(Instrument.tradingsymbol.in_(snap), Instrument.tradingsymbol.in_(scanned)),
        )
        .order_by(Instrument.tradingsymbol)
    ).scalars()
    return tuple(dict.fromkeys(rows))


# Back-compat alias used by older imports during rollout.
symbols_as_of = brain_universe
