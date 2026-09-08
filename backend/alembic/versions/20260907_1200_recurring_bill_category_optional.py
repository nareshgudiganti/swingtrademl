"""recurring_bill_category_optional

Revision ID: a1b2c3d4e5f6
Revises: 7c2f9e1a4d3b
Create Date: 2026-09-07 12:00:00.000000+00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "7c2f9e1a4d3b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "finance_recurring_bills",
        "category",
        existing_type=sa.String(length=64),
        nullable=True,
    )


def downgrade() -> None:
    # Bills saved without a category since the upgrade would violate the old
    # NOT NULL constraint — back-fill them before restoring it.
    op.execute(
        "UPDATE finance_recurring_bills SET category = 'Uncategorised' WHERE category IS NULL"
    )
    op.alter_column(
        "finance_recurring_bills",
        "category",
        existing_type=sa.String(length=64),
        nullable=False,
    )
