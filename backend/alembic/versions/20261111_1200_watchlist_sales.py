"""Groww Tracker sold records: one row per sale, so history survives re-adding a stock

Revision ID: wlsales01
Revises: acctdelete01
Create Date: 2026-11-11 12:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "wlsales01"
down_revision: str | None = "acctdelete01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_watchlist_sales",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
        ),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("bought_on", sa.Date, nullable=False),
        sa.Column("entry_price", sa.Float, nullable=False),
        sa.Column("entry_source", sa.String(16), nullable=False),
        sa.Column("quantity", sa.Float),
        sa.Column("sell_price", sa.Float, nullable=False),
        sa.Column("sold_on", sa.Date, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("user_watchlist_sales")
