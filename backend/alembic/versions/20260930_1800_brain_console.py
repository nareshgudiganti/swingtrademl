"""brain_console: stored data quality per run, and owner overrules

Revision ID: 7c2d9e4f1b63
Revises: 3e8b5c1d7a90
Create Date: 2026-09-30 18:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7c2d9e4f1b63"
down_revision: str | None = "3e8b5c1d7a90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("brain_runs", sa.Column("quality", postgresql.JSONB(), nullable=False, server_default="{}"))
    op.add_column("brain_decisions", sa.Column("overruled_word", sa.String(8)))
    op.add_column("brain_decisions", sa.Column("overrule_reason", sa.Text()))
    op.add_column("brain_decisions", sa.Column("overruled_by", sa.String(128)))
    op.add_column("brain_decisions", sa.Column("overruled_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("brain_decisions", "overruled_at")
    op.drop_column("brain_decisions", "overruled_by")
    op.drop_column("brain_decisions", "overrule_reason")
    op.drop_column("brain_decisions", "overruled_word")
    op.drop_column("brain_runs", "quality")
