"""M09 learning loop: outcome columns on brain_decisions, brain_proposals

Revision ID: 9f2a6c3e7d10
Revises: 6e1b4d8a2c73
Create Date: 2026-10-03 09:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9f2a6c3e7d10"
down_revision: str | None = "6e1b4d8a2c73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("brain_decisions", sa.Column("outcome", sa.String(8), nullable=True))
    op.add_column("brain_decisions", sa.Column("outcome_return", sa.Float(), nullable=True))
    op.add_column("brain_decisions", sa.Column("outcome_days", sa.Integer(), nullable=True))
    op.add_column("brain_decisions", sa.Column("max_up", sa.Float(), nullable=True))
    op.add_column("brain_decisions", sa.Column("max_down", sa.Float(), nullable=True))
    op.add_column("brain_decisions", sa.Column("resolved_on", sa.Date(), nullable=True))

    op.create_table(
        "brain_proposals",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("change", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(12), nullable=False, server_default="open"),
        sa.Column("decided_by", sa.String(128), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_brain_proposals_status", "brain_proposals", ["status"])


def downgrade() -> None:
    op.drop_index("ix_brain_proposals_status", table_name="brain_proposals")
    op.drop_table("brain_proposals")

    op.drop_column("brain_decisions", "resolved_on")
    op.drop_column("brain_decisions", "max_down")
    op.drop_column("brain_decisions", "max_up")
    op.drop_column("brain_decisions", "outcome_days")
    op.drop_column("brain_decisions", "outcome_return")
    op.drop_column("brain_decisions", "outcome")
