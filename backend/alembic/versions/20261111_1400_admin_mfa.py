"""admin_mfa, admin_recovery_codes (admin two-step sign-in)

New tables only; nothing existing is altered. Safe to run twice.

Revision ID: adminmfa01
Revises: billing01
Create Date: 2026-11-11 14:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "adminmfa01"
down_revision: str | None = "billing01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("now()")


def upgrade() -> None:
    have = set(sa.inspect(op.get_bind()).get_table_names())
    if "admin_mfa" not in have:
        op.create_table(
            "admin_mfa",
            sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("secret", sa.String(64), nullable=False),
            sa.Column("enabled_at", sa.DateTime(timezone=True)),
            sa.Column("last_step", sa.BigInteger, nullable=False, server_default="0"),
            sa.Column("failed_count", sa.Integer, nullable=False, server_default="0"),
            sa.Column("locked_until", sa.DateTime(timezone=True)),
        )
    if "admin_recovery_codes" not in have:
        op.create_table(
            "admin_recovery_codes",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("code_hash", sa.String(64), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        )
        op.create_index("ix_admin_recovery_codes_user_id", "admin_recovery_codes", ["user_id"])


def downgrade() -> None:
    have = set(sa.inspect(op.get_bind()).get_table_names())
    if "admin_recovery_codes" in have:
        op.drop_table("admin_recovery_codes")
    if "admin_mfa" in have:
        op.drop_table("admin_mfa")
