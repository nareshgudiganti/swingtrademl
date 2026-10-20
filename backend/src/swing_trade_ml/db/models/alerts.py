"""The owner's Telegram alert settings (tracker ux3) and the messages held back
for quiet hours or the daily digest.

Only informational messages are ever held or switched off; the always-on ones
(sells, real orders, safety stops, login and system problems) never reach these
tables. Nothing here is read by trading, sizing, exits or the brain.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from swing_trade_ml.db.base import Base, TimestampMixin, utcnow


class AlertSettings(Base, TimestampMixin):
    """One row per scope. Today only scope "owner" exists; a later per-user
    version (tracker mu6) adds rows like "user:12" without a schema change.
    No row means the defaults: every alert on, no quiet hours, no digest."""

    __tablename__ = "alert_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope: Mapped[str] = mapped_column(String(64), unique=True, default="owner")
    # Keys of switchable alert types the owner turned off (notifications/alert_policy.py).
    disabled_kinds: Mapped[list] = mapped_column(JSONB, default=list)
    quiet_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    quiet_start: Mapped[str] = mapped_column(String(5), default="22:00")  # "HH:MM" IST
    quiet_end: Mapped[str] = mapped_column(String(5), default="07:00")
    digest_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    digest_time: Mapped[str] = mapped_column(String(5), default="18:00")
    # IST day the last digest went out, so it is sent once a day.
    last_digest_on: Mapped[date | None] = mapped_column(Date)
    updated_by: Mapped[str | None] = mapped_column(String(128))


class AlertOutbox(Base):
    """One informational message held for later (quiet hours or the digest).
    `sent_at` is set once it really reached Telegram; unsent rows are retried."""

    __tablename__ = "alert_outbox"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    scope: Mapped[str] = mapped_column(String(64), default="owner")
    kind: Mapped[str] = mapped_column(String(32))
    text: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
