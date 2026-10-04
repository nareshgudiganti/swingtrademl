"""brain_track: open trades day by day against similar trades (M15)

Revision ID: 6e1b4d8a2c73
Revises: 3c9a7e1f5b28
Create Date: 2026-10-02 20:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "6e1b4d8a2c73"
down_revision: str | None = "3c9a7e1f5b28"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "brain_track",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("book", sa.String(8), nullable=False),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("opened_on", sa.Date(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("day_n", sa.Integer(), nullable=False),
        sa.Column("ret", sa.Float(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("stop", sa.Float(), nullable=True),
        sa.Column("band", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("book", "symbol", "opened_on", "day", name="uq_brain_track_day"),
    )
    op.create_index("ix_brain_track_symbol", "brain_track", ["symbol"])
    op.create_index("ix_brain_track_day", "brain_track", ["day"])


def downgrade() -> None:
    op.drop_index("ix_brain_track_day", table_name="brain_track")
    op.drop_index("ix_brain_track_symbol", table_name="brain_track")
    op.drop_table("brain_track")
