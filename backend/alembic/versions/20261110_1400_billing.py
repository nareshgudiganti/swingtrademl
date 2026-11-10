"""subscriptions, billing_events, plan_grants (Pro billing, sandbox)

New tables only; nothing existing is altered. Safe to run twice.

Revision ID: billing01
Revises: usernamemob01
Create Date: 2026-11-10 14:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "billing01"
down_revision: str | None = "usernamemob01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("now()")


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    have = _tables()
    if "subscriptions" not in have:
        op.create_table(
            "subscriptions",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("provider", sa.String(16), nullable=False),
            sa.Column("provider_subscription_id", sa.String(64), nullable=False, unique=True),
            sa.Column("provider_plan_id", sa.String(64)),
            sa.Column("status", sa.String(16), nullable=False, server_default="created"),
            sa.Column("current_start", sa.DateTime(timezone=True)),
            sa.Column("current_end", sa.DateTime(timezone=True)),
            sa.Column("cancel_at_cycle_end", sa.Boolean, nullable=False, server_default=sa.text("false")),
            sa.Column("cancelled_at", sa.DateTime(timezone=True)),
            sa.Column("cycle_end_requested_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        )
        op.create_index("ix_subscriptions_user_id", "subscriptions", ["user_id"])
    if "billing_events" not in have:
        op.create_table(
            "billing_events",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("provider", sa.String(16), nullable=False),
            sa.Column("event_id", sa.String(96), nullable=False),
            sa.Column("event_type", sa.String(48), nullable=False),
            sa.Column("payload_hash", sa.String(64)),
            sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
            sa.Column("processed_at", sa.DateTime(timezone=True)),
            sa.Column("outcome", sa.String(48)),
            sa.UniqueConstraint("provider", "event_id", name="uq_billing_events_provider_event"),
        )
    if "plan_grants" not in have:
        op.create_table(
            "plan_grants",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("plan_key", sa.String(16), nullable=False),
            sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True)),
            sa.Column("granted_by_user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("reason", sa.Text, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
            sa.Column("revoked_at", sa.DateTime(timezone=True)),
        )
        op.create_index("ix_plan_grants_user_id", "plan_grants", ["user_id"])


def downgrade() -> None:
    have = _tables()
    for name in ("plan_grants", "billing_events", "subscriptions"):
        if name in have:
            op.drop_table(name)
