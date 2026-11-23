"""Stock identity (#389, contract: docs/architecture/IDENTITY-CONTRACTS.md section 1).

One permanent `security_id` per real security. This package is the only place new code asks "which stock is
this?". Everything else (watchlists, the Groww tracker, reports, the score ledger) calls `resolve`.

    from swing_trade_ml.services.identity import resolve
    security_id = resolve(db, symbol="RELIANCE")            # None when the stock is not recognised

Rules (the contract, in plain words):
* An identifier that is given must be well formed. A malformed ISIN, token or symbol returns None: nothing is
  guessed and nothing is created.
* Each identifier is looked up on its own (ISIN, then the Kite token, then the symbol by date). An identifier
  that is unknown is ignored when another one resolves, but if two identifiers resolve to DIFFERENT securities
  the answer is None (a conflict is never settled by guessing).
* The symbol is looked up in the dated symbol history first (so an old symbol resolves for the dates it was
  valid), then in the current `instruments` row for the exchange and symbol.
* `resolve` never writes. It is safe to call from any read path.

The store behind it is replaceable (`use_store`) so tests need no database: `memory.InMemoryStore` is a
complete fake. Given a real session it reads the database; given None it knows nothing (every call returns
None).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol

from swing_trade_ml.core.market_session import IST

DEFAULT_EXCHANGE = "NSE"
PROVIDER_ISIN = "isin"
PROVIDER_KITE_TOKEN = "kite_token"
PROVIDER_GROWW = "groww"

_ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
_SYMBOL = re.compile(r"^[A-Z0-9&\-_.]{1,64}$")


@dataclass(frozen=True)
class SecurityRef:
    """What is known about one security on one date. `symbol` is the symbol valid on that date."""

    id: int
    isin: str | None
    name: str | None
    exchange: str
    symbol: str | None
    status: str = "active"  # active | delisted


class IdentityStore(Protocol):
    """Where identities live. Every method only reads."""

    def id_by_isin(self, isin: str) -> int | None: ...

    def id_by_alias(self, provider: str, external_id: str) -> int | None: ...

    def id_by_symbol_history(self, exchange: str, symbol: str, on_date: date) -> int | None: ...

    def id_by_instrument(self, exchange: str, symbol: str) -> int | None: ...

    def ref(self, security_id: int, exchange: str, on_date: date) -> SecurityRef | None: ...


class NullStore:
    """Knows nothing. The default until the database store exists."""

    def id_by_isin(self, isin: str) -> int | None:
        return None

    def id_by_alias(self, provider: str, external_id: str) -> int | None:
        return None

    def id_by_symbol_history(self, exchange: str, symbol: str, on_date: date) -> int | None:
        return None

    def id_by_instrument(self, exchange: str, symbol: str) -> int | None:
        return None

    def ref(self, security_id: int, exchange: str, on_date: date) -> SecurityRef | None:
        return None


_override: IdentityStore | None = None


def _store_for(db: Any) -> IdentityStore:
    if _override is not None:
        return _override
    if db is not None and hasattr(db, "execute"):  # a real session: read the database
        from swing_trade_ml.services.identity.db import DbStore

        return DbStore(db)
    return NullStore()


@contextmanager
def use_store(store: IdentityStore) -> Iterator[IdentityStore]:
    """Use this store for every `resolve` call inside the block (tests, and nothing else)."""
    global _override
    previous, _override = _override, store
    try:
        yield store
    finally:
        _override = previous


def normalize_isin(value: str) -> str | None:
    """Upper-case ISIN, or None when it is not 12 characters in the ISIN shape."""
    candidate = value.strip().upper()
    return candidate if _ISIN.match(candidate) else None


def normalize_symbol(value: str) -> str | None:
    candidate = value.strip().upper()
    return candidate if _SYMBOL.match(candidate) else None


def normalize_token(value: int | str) -> str | None:
    """A Kite instrument token as the text stored in an alias, or None when it is not a positive integer."""
    if isinstance(value, bool):
        return None
    try:
        number = int(str(value).strip())
    except ValueError:
        return None
    return str(number) if number > 0 else None


def _today() -> date:
    return datetime.now(IST).date()


def resolve(
    db: Any,
    *,
    symbol: str | None = None,
    isin: str | None = None,
    token: int | str | None = None,
    exchange: str = DEFAULT_EXCHANGE,
    on_date: date | None = None,
) -> int | None:
    """The `security_id` for these identifiers, or None when the stock is not recognised or they disagree."""
    if symbol is None and isin is None and token is None:
        return None
    store = _store_for(db)
    found: set[int] = set()

    if isin is not None:
        clean = normalize_isin(isin)
        if clean is None:
            return None
        sid = store.id_by_isin(clean) or store.id_by_alias(PROVIDER_ISIN, clean)
        if sid is not None:
            found.add(sid)

    if token is not None:
        clean_token = normalize_token(token)
        if clean_token is None:
            return None
        sid = store.id_by_alias(PROVIDER_KITE_TOKEN, clean_token)
        if sid is not None:
            found.add(sid)

    if symbol is not None:
        clean_symbol = normalize_symbol(symbol)
        if clean_symbol is None:
            return None
        day = on_date or _today()
        sid = store.id_by_symbol_history(exchange, clean_symbol, day) or store.id_by_instrument(
            exchange, clean_symbol
        )
        if sid is not None:
            found.add(sid)

    return next(iter(found)) if len(found) == 1 else None


def get_ref(
    db: Any, security_id: int, *, exchange: str = DEFAULT_EXCHANGE, on_date: date | None = None
) -> SecurityRef | None:
    """What is known about a security, with the symbol it had on `on_date` (today by default)."""
    return _store_for(db).ref(security_id, exchange, on_date or _today())
