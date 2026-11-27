# ruff: noqa: E501 (long plain-English docstring)
"""saved_screens: each person's saved Discover filters (#310 slice A).

Additive only: one new table, no change to any existing table, row or limit. Names are unique per person ignoring
case (functional unique index). Rows are deleted with the person (foreign key, on delete cascade). Downgrade drops
the table.

Revision ID: savedscreen01
Revises: scanrank02
Create Date: 2026-11-27 12:00:00.000000+00:00

MERGE ORDER: `scanrank02` is added by the #260 PR (scanrank01, scanrank02 on top of signalkey01). This revision
must merge AFTER that PR, so the chain stays a single line.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "savedscreen01"
down_revision: str | None = "signalkey01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "saved_screens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("spec", postgresql.JSONB(), nullable=False),
        sa.Column("filters_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_saved_screens_user_id", "saved_screens", ["user_id"])
    op.create_index(
        "uq_saved_screens_user_name", "saved_screens", ["user_id", sa.text("lower(name)")], unique=True
    )


def downgrade() -> None:
    op.drop_index("uq_saved_screens_user_name", table_name="saved_screens")
    op.drop_index("ix_saved_screens_user_id", table_name="saved_screens")
    op.drop_table("saved_screens")
