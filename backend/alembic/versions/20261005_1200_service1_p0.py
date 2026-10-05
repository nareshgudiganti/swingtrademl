"""Service 1 P0: watchlist snapshots and candle correction log.

Revision ID: c7d8e9f0a1b2
Revises: p1a2n3s4f5r6
Create Date: 2026-10-05 12:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7d8e9f0a1b2"
down_revision: str | None = "p1a2n3s4f5r6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "watchlist_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_date", "symbol", name="uq_watchlist_snapshot_day_symbol"),
    )
    op.create_index("ix_watchlist_snapshots_snapshot_date", "watchlist_snapshots", ["snapshot_date"])
    op.create_index("ix_watchlist_snapshots_symbol", "watchlist_snapshots", ["symbol"])

    op.create_table(
        "candle_corrections",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("interval", sa.Text(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("old_open", sa.Float(), nullable=False),
        sa.Column("old_high", sa.Float(), nullable=False),
        sa.Column("old_low", sa.Float(), nullable=False),
        sa.Column("old_close", sa.Float(), nullable=False),
        sa.Column("old_volume", sa.BigInteger(), nullable=False),
        sa.Column("new_open", sa.Float(), nullable=False),
        sa.Column("new_high", sa.Float(), nullable=False),
        sa.Column("new_low", sa.Float(), nullable=False),
        sa.Column("new_close", sa.Float(), nullable=False),
        sa.Column("new_volume", sa.BigInteger(), nullable=False),
        sa.Column("corrected_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_candle_corrections_instrument_id", "candle_corrections", ["instrument_id"])
    op.create_index("ix_candle_corrections_ts", "candle_corrections", ["ts"])


def downgrade() -> None:
    op.drop_table("candle_corrections")
    op.drop_table("watchlist_snapshots")
