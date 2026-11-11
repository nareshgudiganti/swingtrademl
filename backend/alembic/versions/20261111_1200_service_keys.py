"""service_keys (scoped machine keys, hashed)

New table only; nothing existing is altered. Safe to run twice.

Revision ID: servicekeys01
Revises: billing01
Create Date: 2026-11-11 12:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "servicekeys01"
down_revision: str | None = "billing01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if "service_keys" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "service_keys",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(24), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("prefix", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("rotated_from_id", sa.Integer, sa.ForeignKey("service_keys.id", ondelete="SET NULL")),
    )
    op.create_index("ix_service_keys_name", "service_keys", ["name"])


def downgrade() -> None:
    if "service_keys" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("service_keys")
