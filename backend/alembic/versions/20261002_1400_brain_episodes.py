"""brain_episodes: market episodes for the brain's memory (M04)

Revision ID: 8d3f6a2b9e47
Revises: 5b7e2d9c3a11
Create Date: 2026-10-02 14:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8d3f6a2b9e47"
down_revision: str | None = "5b7e2d9c3a11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "brain_episodes",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("label", sa.String(32), nullable=False),
        sa.Column("start_day", sa.Date(), nullable=False),
        sa.Column("end_day", sa.Date(), nullable=True),
        sa.Column("state_key", sa.String(64), nullable=False, server_default=""),
        sa.Column("stats", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("scope", "start_day", name="uq_brain_episode_start"),
    )
    op.create_index("ix_brain_episodes_scope", "brain_episodes", ["scope"])
    op.create_index("ix_brain_episodes_start_day", "brain_episodes", ["start_day"])


def downgrade() -> None:
    op.drop_index("ix_brain_episodes_start_day", table_name="brain_episodes")
    op.drop_index("ix_brain_episodes_scope", table_name="brain_episodes")
    op.drop_table("brain_episodes")
