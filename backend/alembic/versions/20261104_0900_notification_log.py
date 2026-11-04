"""notification_log: whether each SELL alert was queued, accepted by Telegram or failed

One new table, nothing else. No existing table or row is touched and there is no foreign key into trades or
orders. The upgrade is safe to run twice. The downgrade drops only this table.

Revision ID: notiflog1a2b3
Revises: corpact1a2b3
Create Date: 2026-11-04 09:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "notiflog1a2b3"
down_revision: str | None = "corpact1a2b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if "notification_log" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "notification_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dedupe_key", sa.String(160), nullable=False, unique=True),
        sa.Column("message_type", sa.String(32), nullable=False),
        sa.Column("book", sa.String(16), nullable=False),
        sa.Column("symbol", sa.String(32)),
        sa.Column("trade_id", sa.Integer()),
        sa.Column("position_id", sa.Integer()),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("attempts", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("http_status", sa.SmallInteger()),
        sa.Column("error_kind", sa.String(64)),
        sa.Column("error_detail", sa.String(160)),
    )
    op.create_index("ix_notification_log_created_at", "notification_log", ["created_at"])
    op.create_index("ix_notification_log_status", "notification_log", ["status"])
    op.create_index("ix_notification_log_trade_id", "notification_log", ["trade_id"])


def downgrade() -> None:
    if "notification_log" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table("notification_log")
