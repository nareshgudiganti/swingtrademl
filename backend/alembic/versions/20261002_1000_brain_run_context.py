"""brain_runs.context: what a run knew beyond its decisions (M11 sector table)

Revision ID: 5b7e2d9c3a11
Revises: 2f8c1a7e5d40
Create Date: 2026-10-02 10:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "5b7e2d9c3a11"
down_revision: str | None = "2f8c1a7e5d40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("brain_runs", sa.Column("context", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("brain_runs", "context")
