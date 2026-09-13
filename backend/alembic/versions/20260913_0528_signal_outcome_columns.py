"""signal_outcome_columns

Revision ID: 24df8a18dfa3
Revises: a1b2c3d4e5f6
Create Date: 2026-09-13 05:28:12.819698+00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "24df8a18dfa3"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("signals", sa.Column("horizon_days", sa.Integer(), nullable=True))
    op.add_column("signals", sa.Column("outcome", sa.String(length=24), nullable=True))
    op.add_column("signals", sa.Column("outcome_pct", sa.Float(), nullable=True))
    op.add_column(
        "signals", sa.Column("outcome_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index("ix_signals_outcome", "signals", ["outcome"])


def downgrade() -> None:
    op.drop_index("ix_signals_outcome", table_name="signals")
    op.drop_column("signals", "outcome_at")
    op.drop_column("signals", "outcome_pct")
    op.drop_column("signals", "outcome")
    op.drop_column("signals", "horizon_days")
