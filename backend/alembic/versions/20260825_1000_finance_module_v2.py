"""finance_module_v2

Revision ID: 65e42028acce
Revises: 0a66750aa9bc
Create Date: 2026-08-25 10:00:00.000000+00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "65e42028acce"
down_revision: str | None = "0a66750aa9bc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "finance_loans",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("account_number", sa.String(64), nullable=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("principal", sa.Float(), nullable=False),
        sa.Column("annual_rate", sa.Float(), nullable=False),
        sa.Column("tenure_months", sa.Integer(), nullable=False),
        sa.Column("emi", sa.Float(), nullable=False),
        sa.Column("extra_payment", sa.Float(), nullable=False, server_default="0"),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "finance_custom_rules",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("keyword", sa.String(128), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="90"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_finance_custom_rules_keyword", "finance_custom_rules", ["keyword"], unique=True)


def downgrade() -> None:
    op.drop_table("finance_custom_rules")
    op.drop_table("finance_loans")
