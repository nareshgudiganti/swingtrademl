"""Saturday brain health check: stored result

Revision ID: w7h3a1t5h0c1
Revises: m3r6e5p1s1v1
Create Date: 2026-10-08 10:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "w7h3a1t5h0c1"
down_revision: str | None = "m3r6e5p1s1v1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "brain_weekly_health",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("checks", postgresql.JSONB(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_table("brain_weekly_health")
