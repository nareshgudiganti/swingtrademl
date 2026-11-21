"""Groww holdings sync: sync log, holdings, stock aliases, watchlist link and change history

Additive only. Existing watchlist rows backfill to source 'manual' / held_state 'unknown'.

Revision ID: growwsync01
Revises: wlsales01
Create Date: 2026-11-21 12:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "growwsync01"
down_revision: str | None = "wlsales01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "groww_syncs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("trigger", sa.String(16), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("holdings_count", sa.Integer),
        sa.Column("error_code", sa.String(64)),
    )
    op.create_table(
        "groww_holdings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "sync_id",
            sa.Integer,
            sa.ForeignKey("groww_syncs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("isin", sa.String(16), nullable=False, index=True),
        sa.Column("trading_symbol", sa.String(64)),
        sa.Column("quantity", sa.Float),
        sa.Column("average_price", sa.Float),
        sa.Column("extra", postgresql.JSONB),
        sa.Column("instrument_id", sa.Integer, sa.ForeignKey("instruments.id")),
        sa.Column("match_state", sa.String(16), nullable=False),
    )
    op.create_table(
        "stock_aliases",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("external_id", sa.String(32), nullable=False),
        sa.Column("external_symbol", sa.String(64)),
        sa.Column("instrument_id", sa.Integer, sa.ForeignKey("instruments.id")),
        sa.Column("confirmed_by_user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("provider", "external_id", name="uq_stock_aliases_provider_external_id"),
    )
    op.add_column(
        "user_watchlist_items",
        sa.Column("source", sa.String(16), server_default="manual", nullable=False),
    )
    op.add_column("user_watchlist_items", sa.Column("groww_isin", sa.String(16)))
    op.add_column(
        "user_watchlist_items",
        sa.Column("held_state", sa.String(16), server_default="unknown", nullable=False),
    )
    op.add_column("user_watchlist_items", sa.Column("groww_synced_at", sa.DateTime(timezone=True)))
    op.create_table(
        "user_watchlist_item_changes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "item_id",
            sa.Integer,
            sa.ForeignKey("user_watchlist_items.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("field", sa.String(32), nullable=False),
        sa.Column("old_value", sa.Text),
        sa.Column("new_value", sa.Text),
        sa.Column("changed_by", sa.String(16), nullable=False),
        sa.Column("sync_id", sa.Integer, sa.ForeignKey("groww_syncs.id", ondelete="SET NULL")),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("user_watchlist_item_changes")
    op.drop_column("user_watchlist_items", "groww_synced_at")
    op.drop_column("user_watchlist_items", "held_state")
    op.drop_column("user_watchlist_items", "groww_isin")
    op.drop_column("user_watchlist_items", "source")
    op.drop_table("stock_aliases")
    op.drop_table("groww_holdings")
    op.drop_table("groww_syncs")
