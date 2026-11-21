"""Groww holdings sync: one row per sync, what each sync returned, and saved stock matches.

Display/tracking only. Nothing here places or changes an order, and nothing in trading,
sizing, exits or the brain reads it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from swing_trade_ml.db.base import Base, TimestampMixin

# groww_syncs.status
SYNC_COMPLETE = "complete"
SYNC_PARTIAL = "partial"
SYNC_FAILED = "failed"
SYNC_EMPTY = "empty_unconfirmed"

# groww_holdings.match_state
MATCH_CONFIRMED = "confirmed"
MATCH_SUGGESTED = "suggested"
MATCH_NEEDS = "needs_matching"

# user_watchlist_items.held_state
HELD = "held"
NOT_HELD = "not_held"
HELD_UNKNOWN = "unknown"

# user_watchlist_items.source
SOURCE_MANUAL = "manual"
SOURCE_GROWW = "groww"


class GrowwSync(Base):
    __tablename__ = "groww_syncs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trigger: Mapped[str] = mapped_column(String(16))  # scheduled | manual
    status: Mapped[str] = mapped_column(String(24))
    holdings_count: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(64))


class GrowwHolding(Base):
    __tablename__ = "groww_holdings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sync_id: Mapped[int] = mapped_column(ForeignKey("groww_syncs.id", ondelete="CASCADE"), index=True)
    isin: Mapped[str] = mapped_column(String(16), index=True)
    trading_symbol: Mapped[str | None] = mapped_column(String(64))
    quantity: Mapped[float | None] = mapped_column(Float)
    average_price: Mapped[float | None] = mapped_column(Float)
    # pledge / T1 / locked quantities as Groww reports them
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instruments.id"))
    match_state: Mapped[str] = mapped_column(String(16))


class StockAlias(Base, TimestampMixin):
    """A confirmed match between an outside stock id (Groww ISIN) and our instrument."""

    __tablename__ = "stock_aliases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(16))
    external_id: Mapped[str] = mapped_column(String(32))
    external_symbol: Mapped[str | None] = mapped_column(String(64))
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instruments.id"))
    confirmed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("provider", "external_id", name="uq_stock_aliases_provider_external_id"),
    )
