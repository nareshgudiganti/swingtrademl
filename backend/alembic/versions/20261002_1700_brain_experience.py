"""brain_experience: past stock-days and their outcomes, for recall (M05)

Revision ID: 3c9a7e1f5b28
Revises: 8d3f6a2b9e47
Create Date: 2026-10-02 17:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3c9a7e1f5b28"
down_revision: str | None = "8d3f6a2b9e47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "brain_experience",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("market", sa.String(32), nullable=False),
        sa.Column("stock", sa.String(16), nullable=False),
        sa.Column("trend", sa.String(16), nullable=False),
        sa.Column("vol", sa.String(16), nullable=False),
        sa.Column("outcome", sa.String(8), nullable=False),
        sa.Column("exit_return", sa.Float(), nullable=False),
        sa.Column("days", sa.Integer(), nullable=False),
        sa.Column("outcome_day", sa.Date(), nullable=False),
        sa.Column("path_day", sa.Date(), nullable=False),
        sa.Column("path", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.UniqueConstraint("symbol", "day", name="uq_brain_experience"),
    )
    op.create_index("ix_brain_experience_symbol", "brain_experience", ["symbol"])
    op.create_index("ix_brain_experience_day", "brain_experience", ["day"])
    op.create_index("ix_brain_experience_outcome_day", "brain_experience", ["outcome_day"])


def downgrade() -> None:
    op.drop_index("ix_brain_experience_outcome_day", table_name="brain_experience")
    op.drop_index("ix_brain_experience_day", table_name="brain_experience")
    op.drop_index("ix_brain_experience_symbol", table_name="brain_experience")
    op.drop_table("brain_experience")
