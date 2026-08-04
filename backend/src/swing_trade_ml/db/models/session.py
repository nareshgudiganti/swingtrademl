"""Dashboard users and the daily Zerodha access token."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from swing_trade_ml.db.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    """Login for the React dashboard.

    Deliberately separate from the Zerodha broker session: the dashboard should
    stay reachable to check positions even on a day nobody has logged in to
    Kite yet.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<User {self.username}>"


class BrokerSession(Base, TimestampMixin):
    """A Kite access token.

    Kite invalidates tokens daily around 06:00 IST, so this table is an
    append-only log: the newest active row is loaded at startup, and a fresh
    login each trading morning adds a new one. Keeping history makes it
    possible to correlate an API failure with which token was in use.
    """

    __tablename__ = "broker_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    broker: Mapped[str] = mapped_column(String(32), default="zerodha", index=True)
    kite_user_id: Mapped[str | None] = mapped_column(String(64))
    user_name: Mapped[str | None] = mapped_column(String(128))

    access_token: Mapped[str] = mapped_column(String(512))
    public_token: Mapped[str | None] = mapped_column(String(512))
    refresh_token: Mapped[str | None] = mapped_column(String(512))

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<BrokerSession {self.broker} user={self.kite_user_id} active={self.is_active}>"
