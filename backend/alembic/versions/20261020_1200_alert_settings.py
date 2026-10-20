"""Owner's Telegram alert settings and the held-message outbox (tracker ux3)

Two new tables, nothing else touched. No row in alert_settings means the
defaults (every alert on, no quiet hours, no digest), so nothing is seeded.

Revision ID: a1e7r3s5t2u3
Revises: h0r1z5e7x3p1
Create Date: 2026-10-20 12:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1e7r3s5t2u3"
down_revision: str | None = "h0r1z5e7x3p1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "alert_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scope", sa.String(64), nullable=False),
        sa.Column("disabled_kinds", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("quiet_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("quiet_start", sa.String(5), nullable=False, server_default="22:00"),
        sa.Column("quiet_end", sa.String(5), nullable=False, server_default="07:00"),
        sa.Column("digest_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("digest_time", sa.String(5), nullable=False, server_default="18:00"),
        sa.Column("last_digest_on", sa.Date(), nullable=True),
        sa.Column("updated_by", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("scope", name="uq_alert_settings_scope"),
    )
    op.create_table(
        "alert_outbox",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("scope", sa.String(64), nullable=False, server_default="owner"),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_alert_outbox_created_at", "alert_outbox", ["created_at"])
    op.create_index("ix_alert_outbox_sent_at", "alert_outbox", ["sent_at"])


def downgrade() -> None:
    op.drop_index("ix_alert_outbox_sent_at", table_name="alert_outbox")
    op.drop_index("ix_alert_outbox_created_at", table_name="alert_outbox")
    op.drop_table("alert_outbox")
    op.drop_table("alert_settings")
