"""M18 go-live: the owner's stage switch, one audited row per change

Revision ID: d2a7c4e9f150
Revises: b4e7a1c9d352
Create Date: 2026-10-04 09:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d2a7c4e9f150"
down_revision: str | None = "b4e7a1c9d352"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "brain_stage_changes",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("stage", sa.String(12), nullable=False),
        sa.Column("previous_stage", sa.String(12), nullable=False),
        sa.Column("changed_by", sa.String(128), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_brain_stage_changes_changed_at", "brain_stage_changes", ["changed_at"])


def downgrade() -> None:
    op.drop_index("ix_brain_stage_changes_changed_at", table_name="brain_stage_changes")
    op.drop_table("brain_stage_changes")
