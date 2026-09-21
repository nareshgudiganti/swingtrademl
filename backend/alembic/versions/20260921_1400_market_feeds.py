"""market_feeds

Revision ID: 9c4b7e2a1f36
Revises: 3a8e5c1d9b70
Create Date: 2026-09-21 14:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9c4b7e2a1f36"
down_revision: str | None = "3a8e5c1d9b70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    # New tables only — nothing existing is altered.
    op.create_table(
        "daily_delivery",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("series", sa.String(length=8), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("close_price", sa.Float(), nullable=True),
        sa.Column("traded_qty", sa.BigInteger(), nullable=True),
        sa.Column("turnover_lacs", sa.Float(), nullable=True),
        sa.Column("trades", sa.Integer(), nullable=True),
        sa.Column("delivery_qty", sa.BigInteger(), nullable=True),
        sa.Column("delivery_pct", sa.Float(), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", "series", "trade_date", name="uq_daily_delivery"),
    )
    op.create_index(op.f("ix_daily_delivery_symbol"), "daily_delivery", ["symbol"], unique=False)
    op.create_index(op.f("ix_daily_delivery_trade_date"), "daily_delivery", ["trade_date"], unique=False)

    op.create_table(
        "block_deals",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("deal_key", sa.String(length=64), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("client_name", sa.String(length=255), nullable=False),
        sa.Column("side", sa.String(length=4), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_block_deals_deal_key"), "block_deals", ["deal_key"], unique=True)
    op.create_index(op.f("ix_block_deals_trade_date"), "block_deals", ["trade_date"], unique=False)
    op.create_index(op.f("ix_block_deals_symbol"), "block_deals", ["symbol"], unique=False)

    op.create_table(
        "institutional_flows",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("category", sa.String(length=8), nullable=False),
        sa.Column("buy_value", sa.Float(), nullable=False),
        sa.Column("sell_value", sa.Float(), nullable=False),
        sa.Column("net_value", sa.Float(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trade_date", "category", name="uq_institutional_flow"),
    )
    op.create_index(
        op.f("ix_institutional_flows_trade_date"), "institutional_flows", ["trade_date"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_institutional_flows_trade_date"), table_name="institutional_flows")
    op.drop_table("institutional_flows")
    op.drop_index(op.f("ix_block_deals_symbol"), table_name="block_deals")
    op.drop_index(op.f("ix_block_deals_trade_date"), table_name="block_deals")
    op.drop_index(op.f("ix_block_deals_deal_key"), table_name="block_deals")
    op.drop_table("block_deals")
    op.drop_index(op.f("ix_daily_delivery_trade_date"), table_name="daily_delivery")
    op.drop_index(op.f("ix_daily_delivery_symbol"), table_name="daily_delivery")
    op.drop_table("daily_delivery")
