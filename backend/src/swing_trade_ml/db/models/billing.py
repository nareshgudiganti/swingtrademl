"""Pro billing: provider subscriptions, webhook events (idempotency) and manual plan grants.

A subscription row mirrors what the payment provider says (we upsert from a fetch,
never from event order). `current_end` is the paid-through date. Grants are a
separate, owner-made thing with optional expiry. See services/billing/entitlement.py.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from swing_trade_ml.db.base import Base

SUBSCRIPTION_STATUSES = (
    "created",
    "authenticated",
    "active",
    "pending",
    "halted",
    "cancelled",
    "completed",
    "paused",
)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(16))
    provider_subscription_id: Mapped[str] = mapped_column(String(64), unique=True)
    provider_plan_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="created", server_default="created")
    current_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The paid-through date.
    current_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_at_cycle_end: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class BillingEvent(Base):
    """One webhook delivery, keyed by the provider's event id so a repeat changes nothing.
    No payload is stored (it carries personal data): a hash is enough to spot a mismatch."""

    __tablename__ = "billing_events"
    __table_args__ = (UniqueConstraint("provider", "event_id", name="uq_billing_events_provider_event"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(16))
    event_id: Mapped[str] = mapped_column(String(96))
    event_type: Mapped[str] = mapped_column(String(48))
    payload_hash: Mapped[str | None] = mapped_column(String(64))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str | None] = mapped_column(String(48))


class PlanGrant(Base):
    """A complimentary plan the owner gave to one person. Separate from payment."""

    __tablename__ = "plan_grants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    plan_key: Mapped[str] = mapped_column(String(16))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    granted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
