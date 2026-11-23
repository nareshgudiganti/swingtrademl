"""A complete in-memory identity store, for tests that must not need a database.

It follows the same rules as the database store: dated symbol history, aliases unique per provider, an ISIN
belongs to one security. Use it with `identity.use_store(InMemoryStore())`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from swing_trade_ml.services.identity import DEFAULT_EXCHANGE, SecurityRef


@dataclass
class _Security:
    id: int
    isin: str | None
    name: str | None
    status: str = "active"
    # (exchange, symbol, valid_from, valid_to)
    symbols: list[tuple[str, str, date, date | None]] = field(default_factory=list)


class InMemoryStore:
    def __init__(self) -> None:
        self._securities: dict[int, _Security] = {}
        self._aliases: dict[tuple[str, str], int] = {}
        self._instruments: dict[tuple[str, str], int] = {}
        self._next_id = 1

    # ------------------------------------------------------------------ building a fixture

    def add_security(
        self, isin: str | None = None, name: str | None = None, *, status: str = "active"
    ) -> int:
        if isin is not None and any(s.isin == isin for s in self._securities.values()):
            raise ValueError(f"ISIN {isin} already belongs to a security")
        sid = self._next_id
        self._next_id += 1
        self._securities[sid] = _Security(sid, isin, name, status)
        return sid

    def add_symbol(
        self,
        security_id: int,
        symbol: str,
        valid_from: date,
        valid_to: date | None = None,
        exchange: str = DEFAULT_EXCHANGE,
    ) -> None:
        self._securities[security_id].symbols.append((exchange, symbol, valid_from, valid_to))

    def add_alias(self, security_id: int, provider: str, external_id: str) -> None:
        key = (provider, external_id)
        if key in self._aliases and self._aliases[key] != security_id:
            raise ValueError(f"alias {key} already belongs to another security")
        self._aliases[key] = security_id

    def add_instrument(self, security_id: int, symbol: str, exchange: str = DEFAULT_EXCHANGE) -> None:
        """The current `instruments` row (no date): resolves a symbol that has no history row."""
        self._instruments[(exchange, symbol)] = security_id

    # ------------------------------------------------------------------ the store interface

    def id_by_isin(self, isin: str) -> int | None:
        return next((s.id for s in self._securities.values() if s.isin == isin), None)

    def id_by_alias(self, provider: str, external_id: str) -> int | None:
        return self._aliases.get((provider, external_id))

    def id_by_symbol_history(self, exchange: str, symbol: str, on_date: date) -> int | None:
        for security in self._securities.values():
            for ex, sym, start, end in security.symbols:
                if ex == exchange and sym == symbol and start <= on_date and (end is None or on_date <= end):
                    return security.id
        return None

    def has_symbol_history(self, exchange: str, symbol: str) -> bool:
        return any(
            ex == exchange and sym == symbol for s in self._securities.values() for ex, sym, _, _ in s.symbols
        )

    def id_by_instrument(self, exchange: str, symbol: str) -> int | None:
        return self._instruments.get((exchange, symbol))

    def ref(self, security_id: int, exchange: str, on_date: date) -> SecurityRef | None:
        security = self._securities.get(security_id)
        if security is None:
            return None
        symbol = next(
            (
                sym
                for ex, sym, start, end in security.symbols
                if ex == exchange and start <= on_date and (end is None or on_date <= end)
            ),
            None,
        )
        return SecurityRef(security.id, security.isin, security.name, exchange, symbol, security.status)
