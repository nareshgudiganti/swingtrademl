"""One row per important Telegram message the app tries to send (today: SELL alerts).

SENT means Telegram's API accepted the message. It does not mean it was delivered to, or read on, a phone.
The row holds a reference to the trade, never the message text, and never a token. Nothing here is read by
trading, sizing, exits or the brain.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from swing_trade_ml.db.base import Base, utcnow

PENDING, SENT, FAILED, SKIPPED = "PENDING", "SENT", "FAILED", "SKIPPED"


class NotificationLog(Base):
    __tablename__ = "notification_log"
    __table_args__ = (Index("ix_notification_log_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # One message, once: e.g. "sell:1234" (the trade id). A second send for the same key is refused.
    dedupe_key: Mapped[str] = mapped_column(String(160), unique=True)
    message_type: Mapped[str] = mapped_column(String(32))  # sell_full | sell_partial
    book: Mapped[str] = mapped_column(String(16))  # Bot | Testing
    symbol: Mapped[str | None] = mapped_column(String(32))
    # Plain numbers, no foreign keys: logging must never be able to block or undo a trade.
    trade_id: Mapped[int | None] = mapped_column(Integer, index=True)
    position_id: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(8), index=True)  # PENDING | SENT | FAILED | SKIPPED
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    http_status: Mapped[int | None] = mapped_column(SmallInteger)
    error_kind: Mapped[str | None] = mapped_column(String(64))  # an exception class name, or "http_<status>"
    error_detail: Mapped[str | None] = mapped_column(
        String(160)
    )  # Telegram's own description, token-scrubbed
