"""The database-backed identity store (reads only). `resolve` uses it whenever it is given a real session."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.db.models.identity import Security, SecurityAlias, SecuritySymbol
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.services.identity import PROVIDER_KITE_TOKEN, SecurityRef


class DbStore:
    def __init__(self, db: Session) -> None:
        self.db = db

    def id_by_isin(self, isin: str) -> int | None:
        return self.db.scalar(select(Security.id).where(Security.isin == isin))

    def id_by_alias(self, provider: str, external_id: str) -> int | None:
        return self.db.scalar(
            select(SecurityAlias.security_id).where(
                SecurityAlias.provider == provider, SecurityAlias.external_id == external_id
            )
        )

    def id_by_symbol_history(self, exchange: str, symbol: str, on_date: date) -> int | None:
        return self.db.scalar(
            select(SecuritySymbol.security_id)
            .where(
                SecuritySymbol.exchange == exchange,
                SecuritySymbol.symbol == symbol,
                SecuritySymbol.valid_from <= on_date,
                (SecuritySymbol.valid_to.is_(None)) | (SecuritySymbol.valid_to >= on_date),
            )
            .order_by(SecuritySymbol.valid_from.desc())
            .limit(1)
        )

    def id_by_instrument(self, exchange: str, symbol: str) -> int | None:
        """The security of the current `instruments` row, found through that row's Kite token alias."""
        token = self.db.scalar(
            select(Instrument.instrument_token).where(
                Instrument.exchange == exchange, Instrument.tradingsymbol == symbol
            )
        )
        return None if token is None else self.id_by_alias(PROVIDER_KITE_TOKEN, str(token))

    def ref(self, security_id: int, exchange: str, on_date: date) -> SecurityRef | None:
        security = self.db.get(Security, security_id)
        if security is None:
            return None
        symbol = self.db.scalar(
            select(SecuritySymbol.symbol)
            .where(
                SecuritySymbol.security_id == security_id,
                SecuritySymbol.exchange == exchange,
                SecuritySymbol.valid_from <= on_date,
                (SecuritySymbol.valid_to.is_(None)) | (SecuritySymbol.valid_to >= on_date),
            )
            .order_by(SecuritySymbol.valid_from.desc())
            .limit(1)
        )
        return SecurityRef(security.id, security.isin, security.name, exchange, symbol, security.status)
