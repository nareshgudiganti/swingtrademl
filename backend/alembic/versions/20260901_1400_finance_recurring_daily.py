"""finance_recurring_daily

Revision ID: 7c2f9e1a4d3b
Revises: ba6a19b7696e
Create Date: 2026-09-01 14:00:00.000000+00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7c2f9e1a4d3b"
down_revision: str | None = "ba6a19b7696e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "finance_recurring_bills",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("default_amount", sa.Float(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_finance_recurring_bills_is_active", "finance_recurring_bills", ["is_active"]
    )

    op.create_table(
        "finance_recurring_bill_payments",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("bill_id", sa.BigInteger(), nullable=False),
        sa.Column("month", sa.String(length=7), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("transaction_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["bill_id"], ["finance_recurring_bills.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["transaction_id"], ["finance_transactions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bill_id", "month", name="uq_recurring_bill_month"),
    )
    op.create_index(
        "ix_finance_recurring_bill_payments_bill_id",
        "finance_recurring_bill_payments",
        ["bill_id"],
    )
    op.create_index(
        "ix_finance_recurring_bill_payments_month", "finance_recurring_bill_payments", ["month"]
    )

    op.create_table(
        "finance_daily_categories",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(
        "ix_finance_daily_categories_is_active", "finance_daily_categories", ["is_active"]
    )


def downgrade() -> None:
    op.drop_index("ix_finance_daily_categories_is_active", table_name="finance_daily_categories")
    op.drop_table("finance_daily_categories")

    op.drop_index(
        "ix_finance_recurring_bill_payments_month", table_name="finance_recurring_bill_payments"
    )
    op.drop_index(
        "ix_finance_recurring_bill_payments_bill_id", table_name="finance_recurring_bill_payments"
    )
    op.drop_table("finance_recurring_bill_payments")

    op.drop_index("ix_finance_recurring_bills_is_active", table_name="finance_recurring_bills")
    op.drop_table("finance_recurring_bills")
