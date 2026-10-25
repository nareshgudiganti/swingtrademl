"""Each person's own watchlist (new look, wave 2: "My Watchlist")

One new table, nothing else touched. It is not the bot's global watchlist
(instruments.is_watchlisted) and no trading, sizing or brain code reads it.

Revision ID: u5w1l2s3t4i5
Revises: a1e7r3s5t2u3
Create Date: 2026-10-25 12:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "u5w1l2s3t4i5"
down_revision: str | None = "a1e7r3s5t2u3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_watchlist_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_user_watchlist_items_user_id_users"),
            nullable=False,
        ),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "symbol", name="uq_user_watchlist_items_user_symbol"),
    )
    op.create_index("ix_user_watchlist_items_user_id", "user_watchlist_items", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_watchlist_items_user_id", table_name="user_watchlist_items")
    op.drop_table("user_watchlist_items")
