"""Each signed-in person's own watchlist (new look, wave 2: "My Watchlist").

A personal list of stocks to keep an eye on, nothing more. It is NOT the bot's
global watchlist (`instruments.is_watchlisted`, which decides which stocks get
prices and are scanned) and nothing in trading, sizing, exits or the brain reads
it. One row per (person, stock): removing a stock only stamps `removed_at` (so
it shows under "Removed"), and adding it again clears the stamp.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from swing_trade_ml.db.base import Base, TimestampMixin, utcnow


class UserWatchlistItem(Base, TimestampMixin):
    __tablename__ = "user_watchlist_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(64))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Null while the stock is on the list; set when the person removes it.
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(String(200))

    __table_args__ = (UniqueConstraint("user_id", "symbol", name="uq_user_watchlist_items_user_symbol"),)
