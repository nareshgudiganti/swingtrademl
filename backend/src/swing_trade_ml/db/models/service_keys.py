"""Scoped machine keys (uptime checks, watch workflows, smoke tests).

Only a SHA-256 hash of the key is stored; the key itself is shown once at creation.
A key can read a fixed set of things and can never write, see the real account or
reach /admin (see services/service_keys.py)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from swing_trade_ml.db.base import Base


class ServiceKey(Base):
    __tablename__ = "service_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # What it is for, e.g. "uptime-watch". Not unique: a rotation creates a second row with the same name.
    name: Mapped[str] = mapped_column(String(64), index=True)
    scope: Mapped[str] = mapped_column(String(24))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    # First characters of the key, so the owner can tell keys apart in the list. Not secret.
    prefix: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[str] = mapped_column(String(64))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rotated_from_id: Mapped[int | None] = mapped_column(ForeignKey("service_keys.id", ondelete="SET NULL"))
