"""mutual_fund_holding_source

Revision ID: 8f3d2a9c6b41
Revises: 06b7f1c1db82
Create Date: 2026-09-13 12:30:00.000000+00:00
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '8f3d2a9c6b41'
down_revision: str | None = '06b7f1c1db82'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mutual_fund_holdings",
        sa.Column("source", sa.String(length=16), nullable=False, server_default="manual"),
    )
    op.add_column(
        "mutual_fund_holdings",
        sa.Column("folio_number", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mutual_fund_holdings", "folio_number")
    op.drop_column("mutual_fund_holdings", "source")
