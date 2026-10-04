"""The stocks the brain looks at: the watchlist plus every stock version 1's
active auto-trading strategies scan, so the brain and version 1 are judged on
the same ground. Advisory trackers (e.g. real_trading) and staged strategies
(the brain itself) do not add stocks. Only known, active instruments count."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from swing_trade_ml.core.strategy_policy import STAGED_TYPES
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Strategy


def brain_universe(db: Session) -> tuple[str, ...]:
    lists = db.execute(
        select(Strategy.symbols).where(
            Strategy.is_active.is_(True),
            Strategy.execution_mode == "auto",
            Strategy.strategy_type.not_in(sorted(STAGED_TYPES)),
        )
    ).scalars()
    scanned = sorted({s.upper() for symbols in lists for s in (symbols or [])})
    rows = db.execute(
        select(Instrument.tradingsymbol)
        .where(
            Instrument.is_active.is_(True),
            or_(Instrument.is_watchlisted.is_(True), Instrument.tradingsymbol.in_(scanned)),
        )
        .order_by(Instrument.tradingsymbol)
    ).scalars()
    return tuple(dict.fromkeys(rows))
