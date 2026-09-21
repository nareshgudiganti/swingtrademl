"""Every real buy and sell in the connected Zerodha account.

Kite's API only ever returns *today's* trades — there is no history endpoint —
so this table is the only way a buy/sell report can look back. It is filled
two ways that share one key: a daily capture of `kite.trades()`, and an import
of Zerodha's own tradebook file for the time before capture began. Both carry
Zerodha's trade_id, so the same trade arriving twice is stored once.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from swing_trade_ml.db.base import Base, TimestampMixin


class BrokerFill(Base, TimestampMixin):
    __tablename__ = "broker_fills"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    trade_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    order_id: Mapped[str | None] = mapped_column(String(64))
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    exchange: Mapped[str] = mapped_column(String(16), default="NSE")
    side: Mapped[str] = mapped_column(String(4))  # BUY | SELL
    quantity: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Float)
    product: Mapped[str | None] = mapped_column(String(8))
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source: Mapped[str] = mapped_column(String(8), default="api")  # api | csv
