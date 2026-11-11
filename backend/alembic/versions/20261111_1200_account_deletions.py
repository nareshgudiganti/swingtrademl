"""account_deletions (customer account-deletion requests)

New table only; nothing existing is altered. Safe to run twice.

Revision ID: acctdelete01
Revises: servicekeys01, adminmfa01
Create Date: 2026-11-11 12:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "acctdelete01"
down_revision: str | Sequence[str] | None = ("servicekeys01", "adminmfa01")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if "account_deletions" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "account_deletions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="pending"),
        sa.Column(
            "requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("scheduled_for", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("note", sa.String(64)),
    )
    op.create_index("ix_account_deletions_user_id", "account_deletions", ["user_id"])
    op.create_index(
        "uq_account_deletions_one_open",
        "account_deletions",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'scheduled')"),
    )


def downgrade() -> None:
    if "account_deletions" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table("account_deletions")
