"""Brain runs are queued: who asked, when it finished, progress, request

Revision ID: f4a2c8e1d930
Revises: e8b3f1a6c247
Create Date: 2026-10-04 16:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f4a2c8e1d930"
down_revision: str | None = "e8b3f1a6c247"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("brain_runs", sa.Column("requested_by", sa.String(128), nullable=True))
    op.add_column("brain_runs", sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("brain_runs", sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("brain_runs", sa.Column("progress", postgresql.JSONB(), nullable=True))
    op.add_column("brain_runs", sa.Column("request", postgresql.JSONB(), nullable=True))
    op.create_index("ix_brain_runs_status", "brain_runs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_brain_runs_status", table_name="brain_runs")
    for column in ("request", "progress", "finished_at", "requested_at", "requested_by"):
        op.drop_column("brain_runs", column)
