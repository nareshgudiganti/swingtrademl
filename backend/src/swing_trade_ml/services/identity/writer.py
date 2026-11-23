"""The only code that creates or changes securities, symbol history and aliases (#389 S1).

Rules (IDENTITY-CONTRACTS.md section 1): a security is never deleted and its id never reused; a rename closes
the old symbol row and opens a new one; a re-issued Kite token is added as another alias of the SAME security;
an ISIN belongs to one security and a conflict is reported, never settled by guessing. Every function is
idempotent: calling it twice changes nothing the second time. None of them commits; the caller does.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.core.market_session import IST
from swing_trade_ml.db.models.identity import SECURITY_ACTIVE, Security, SecurityAlias, SecuritySymbol
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.services.identity import (
    PROVIDER_ISIN,
    PROVIDER_KITE_TOKEN,
    normalize_isin,
    normalize_symbol,
    resolve,
)

EARLIEST = date(2000, 1, 1)


class IdentityConflictError(Exception):
    """An id already belongs to a different security. Listed for the owner, never merged automatically."""


def create_security(db: Session, *, isin: str | None = None, name: str | None = None) -> int:
    clean = None
    if isin is not None:
        clean = normalize_isin(isin)
        if clean is None:
            raise ValueError("not a valid ISIN")
        existing = db.scalar(select(Security.id).where(Security.isin == clean))
        if existing is not None:
            return existing
    row = Security(isin=clean, name=name, status=SECURITY_ACTIVE)
    db.add(row)
    db.flush()
    return row.id


def attach_isin(db: Session, security_id: int, isin: str) -> None:
    """Give a security its ISIN (once). Another security already holding it is a conflict for the owner."""
    clean = normalize_isin(isin)
    if clean is None:
        raise ValueError("not a valid ISIN")
    row = db.get(Security, security_id)
    if row is None:
        raise ValueError("no such security")
    if row.isin == clean:
        return
    holder = db.scalar(select(Security.id).where(Security.isin == clean))
    if holder is not None and holder != security_id:
        raise IdentityConflictError(f"ISIN {clean} already belongs to security {holder}")
    if row.isin is not None:
        raise IdentityConflictError(f"security {security_id} already has the ISIN {row.isin}")
    row.isin = clean
    add_alias(db, security_id, PROVIDER_ISIN, clean)
    db.flush()


def add_alias(db: Session, security_id: int, provider: str, external_id: str) -> None:
    existing = db.scalar(
        select(SecurityAlias.security_id).where(
            SecurityAlias.provider == provider, SecurityAlias.external_id == external_id
        )
    )
    if existing is None:
        db.add(SecurityAlias(security_id=security_id, provider=provider, external_id=external_id))
        db.flush()
    elif existing != security_id:
        raise IdentityConflictError(f"{provider} id {external_id} already belongs to security {existing}")


def set_symbol(
    db: Session, security_id: int, symbol: str, valid_from: date, *, exchange: str = "NSE"
) -> None:
    """Make `symbol` the security's symbol from `valid_from`; a different open symbol ends the day before."""
    clean = normalize_symbol(symbol)
    if clean is None:
        raise ValueError("not a valid symbol")
    open_rows = list(
        db.scalars(
            select(SecuritySymbol).where(
                SecuritySymbol.security_id == security_id,
                SecuritySymbol.exchange == exchange,
                SecuritySymbol.valid_to.is_(None),
            )
        )
    )
    if any(r.symbol == clean for r in open_rows):
        return
    for row in open_rows:
        row.valid_to = max(row.valid_from, valid_from - timedelta(days=1))
    taken = db.scalar(
        select(SecuritySymbol.security_id).where(
            SecuritySymbol.exchange == exchange,
            SecuritySymbol.symbol == clean,
            SecuritySymbol.valid_to.is_(None),
        )
    )
    if taken is not None and taken != security_id:
        raise IdentityConflictError(f"{exchange}:{clean} is the current symbol of security {taken}")
    db.add(SecuritySymbol(security_id=security_id, exchange=exchange, symbol=clean, valid_from=valid_from))
    db.flush()


def mark_delisted(db: Session, security_id: int, on_date: date, *, exchange: str = "NSE") -> None:
    """The security stays, with its history; its open symbol ends on `on_date`. Its id is never reused."""
    row = db.get(Security, security_id)
    if row is None:
        raise ValueError("no such security")
    row.status = "delisted"
    for sym in db.scalars(
        select(SecuritySymbol).where(
            SecuritySymbol.security_id == security_id,
            SecuritySymbol.exchange == exchange,
            SecuritySymbol.valid_to.is_(None),
        )
    ):
        sym.valid_to = max(sym.valid_from, on_date)
    db.flush()


def ensure_for_instrument(db: Session, instrument: Instrument) -> int:
    """The security for one `instruments` row, creating it (without an ISIN yet) when there is none.

    Order: the token alias; else the symbol's history (a RE-ISSUED token: the new token becomes another alias
    of the same security); else a new security. Idempotent.
    """
    token = str(instrument.instrument_token)
    found = resolve(db, token=token)
    if found is not None:
        set_symbol(db, found, instrument.tradingsymbol, _since(instrument), exchange=instrument.exchange)
        return found
    found = resolve(db, symbol=instrument.tradingsymbol, exchange=instrument.exchange)
    if found is None:
        found = create_security(db, name=instrument.name)
    add_alias(db, found, PROVIDER_KITE_TOKEN, token)
    set_symbol(db, found, instrument.tradingsymbol, _since(instrument), exchange=instrument.exchange)
    return found


def _since(instrument: Instrument) -> date:
    created = instrument.created_at
    return created.astimezone(IST).date() if created is not None else EARLIEST


def backfill_instruments(db: Session, *, exchange: str = "NSE", limit: int | None = None) -> dict[str, int]:
    """Give every equity instrument a security. Idempotent; an instrument it cannot place stays untouched.

    Returns counts: added (a security was made or linked now), unchanged (it already resolved), skipped (a
    conflict: left alone, never guessed).
    """
    counts = {"added": 0, "unchanged": 0, "skipped": 0}
    query = select(Instrument).where(Instrument.exchange == exchange, Instrument.instrument_type == "EQ")
    for instrument in db.scalars(query.order_by(Instrument.id).limit(limit)):
        before = resolve(db, token=str(instrument.instrument_token))
        try:
            with db.begin_nested():
                sid = ensure_for_instrument(db, instrument)
        except IdentityConflictError:
            counts["skipped"] += 1
            continue
        counts["unchanged" if before == sid else "added"] += 1
    return counts
