"""Dashboard users and the daily Zerodha access token."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Integer, String
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
    # Null for accounts created via Google — there is no local password to
    # check for those, sign-in happens entirely through Google's identity.
    hashed_password: Mapped[str | None] = mapped_column(String(255))
    # "local" | "google" — which flow created/authenticates this account.
    auth_provider: Mapped[str] = mapped_column(String(16), default="local")
    # Google's stable per-account identifier, used to find the local row on
    # repeat logins. Email alone isn't a safe join key long-term (Google lets
    # the same email be reused across accounts in edge cases); this is.
    google_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # "free" | "pro" — see core/plans.py. Ignored for superusers,
    # who always see everything.
    plan: Mapped[str] = mapped_column(String(16), default="free", server_default="free")

    def __repr__(self) -> str:
        return f"<User {self.username}>"


class PlanSettings(Base, TimestampMixin):
    """One row, id=1: the owner's master switch for plans. No row, or
    enabled=false, means plans are off and every signed-in account sees the
    whole app, as before plans existed."""

    __tablename__ = "plan_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class SubscriptionPlan(Base, TimestampMixin):
    """The owner's edits to one plan. A plan with no row here uses its
    defaults from core/plans.py, so a fresh database needs no seeding."""

    __tablename__ = "subscription_plans"

    key: Mapped[str] = mapped_column(String(16), primary_key=True)
    features: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    limits: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    def __repr__(self) -> str:
        return f"<SubscriptionPlan {self.key}>"


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
