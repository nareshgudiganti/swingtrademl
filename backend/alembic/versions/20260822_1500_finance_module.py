"""finance_module

Revision ID: 0a66750aa9bc
Revises: b8e4f2a91c67
Create Date: 2026-08-22 15:00:00.000000+00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0a66750aa9bc"
down_revision: str | None = "b8e4f2a91c67"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "finance_ingested_files",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("file_hash", sa.String(64), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("source_type", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="SUCCESS"),
        sa.Column("transaction_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_finance_ingested_files_file_hash", "finance_ingested_files", ["file_hash"], unique=True
    )
    op.create_index(
        "ix_finance_ingested_files_source_type", "finance_ingested_files", ["source_type"]
    )

    op.create_table(
        "finance_transactions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "ingested_file_id",
            sa.BigInteger(),
            sa.ForeignKey("finance_ingested_files.id", ondelete="CASCADE", name="fk_finance_transactions_ingested_file_id_finance_ingested_files"),
            nullable=True,
        ),
        sa.Column("dedup_key", sa.String(160), nullable=False),
        sa.Column("txn_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("month", sa.String(7), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("status", sa.String(16), nullable=True),
        sa.Column("transaction_id", sa.String(128), nullable=True),
        sa.Column("source", sa.String(32), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("category", sa.String(64), nullable=False, server_default="Uncategorised"),
        sa.Column("is_manual_override", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_finance_transactions_ingested_file_id", "finance_transactions", ["ingested_file_id"])
    op.create_index("ix_finance_transactions_dedup_key", "finance_transactions", ["dedup_key"], unique=True)
    op.create_index("ix_finance_transactions_txn_date", "finance_transactions", ["txn_date"])
    op.create_index("ix_finance_transactions_month", "finance_transactions", ["month"])
    op.create_index("ix_finance_transactions_direction", "finance_transactions", ["direction"])
    op.create_index("ix_finance_transactions_transaction_id", "finance_transactions", ["transaction_id"])
    op.create_index("ix_finance_transactions_category", "finance_transactions", ["category"])
    op.create_index("ix_finance_transactions_is_manual_override", "finance_transactions", ["is_manual_override"])
    op.create_index(
        "ix_finance_transactions_month_category", "finance_transactions", ["month", "category"]
    )


def downgrade() -> None:
    op.drop_table("finance_transactions")
    op.drop_table("finance_ingested_files")
