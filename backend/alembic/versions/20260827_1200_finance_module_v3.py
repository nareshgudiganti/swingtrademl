"""finance_module_v3

Revision ID: ba6a19b7696e
Revises: 65e42028acce
Create Date: 2026-08-27 12:00:00.000000+00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ba6a19b7696e"
down_revision: str | None = "65e42028acce"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Soft delete: a statement's "Delete" action is reversible via /restore.
    # Only the separate typed-filename-confirmed "delete permanently" action
    # actually removes rows — see api/v1/endpoints/finance.py.
    op.add_column("finance_ingested_files", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_finance_ingested_files_deleted_at", "finance_ingested_files", ["deleted_at"])

    op.add_column("finance_transactions", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_finance_transactions_deleted_at", "finance_transactions", ["deleted_at"])

    # A PhonePe row demoted because a bank statement covers the same month —
    # see services/finance/ingestion.py::reconcile_source_priority.
    op.add_column(
        "finance_transactions",
        sa.Column("is_reference_only", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_finance_transactions_is_reference_only", "finance_transactions", ["is_reference_only"])


def downgrade() -> None:
    op.drop_index("ix_finance_transactions_is_reference_only", table_name="finance_transactions")
    op.drop_column("finance_transactions", "is_reference_only")

    op.drop_index("ix_finance_transactions_deleted_at", table_name="finance_transactions")
    op.drop_column("finance_transactions", "deleted_at")

    op.drop_index("ix_finance_ingested_files_deleted_at", table_name="finance_ingested_files")
    op.drop_column("finance_ingested_files", "deleted_at")
