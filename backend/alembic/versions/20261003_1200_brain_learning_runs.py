"""M09 learning loop: stored weekly drift check, and the source of a
decision's confidence score

Revision ID: b4e7a1c9d352
Revises: 9f2a6c3e7d10
Create Date: 2026-10-03 12:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b4e7a1c9d352"
down_revision: str | None = "9f2a6c3e7d10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("brain_decisions", sa.Column("score_source", sa.String(16), nullable=True))

    op.create_table(
        "brain_learning_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("drift", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("drift_lines", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("drift_note", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("brain_learning_runs")
    op.drop_column("brain_decisions", "score_source")
