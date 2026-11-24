"""Module switches: the durable on/off state of the optional modules (#291)

Additive only: one new table. No row means the module keeps its declared default (on), so applying this
changes nothing. Downgrade drops the table (every module is then on again); no module data is touched either
way.

Revision ID: modswitch01
Revises: simulation01
Create Date: 2026-11-24 14:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "modswitch01"
down_revision: str | None = "simulation01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "module_switches",
        sa.Column("module_id", sa.String(64), primary_key=True),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("updated_by", sa.String(128), nullable=False),
        sa.Column("reason", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("module_switches")
