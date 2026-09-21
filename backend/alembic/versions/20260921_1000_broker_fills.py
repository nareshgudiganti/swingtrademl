"""broker_fills

Revision ID: 3a8e5c1d9b70
Revises: f1c93a7e2d58
Create Date: 2026-09-21 10:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3a8e5c1d9b70"
down_revision: str | None = "f1c93a7e2d58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A new table only — nothing existing is altered, so code that predates it
    # keeps working against the migrated schema.
    op.create_table(
        "broker_fills",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("trade_id", sa.String(length=64), nullable=False),
        sa.Column("order_id", sa.String(length=64), nullable=True),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("exchange", sa.String(length=16), nullable=False),
        sa.Column("side", sa.String(length=4), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("product", sa.String(length=8), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_broker_fills_trade_id"), "broker_fills", ["trade_id"], unique=True)
    op.create_index(op.f("ix_broker_fills_symbol"), "broker_fills", ["symbol"], unique=False)
    op.create_index(op.f("ix_broker_fills_executed_at"), "broker_fills", ["executed_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_broker_fills_executed_at"), table_name="broker_fills")
    op.drop_index(op.f("ix_broker_fills_symbol"), table_name="broker_fills")
    op.drop_index(op.f("ix_broker_fills_trade_id"), table_name="broker_fills")
    op.drop_table("broker_fills")
