"""max_daily_buys

Revision ID: a7c9d1e3f5b2
Revises: f1a2b3c4d5e6
Create Date: 2026-08-09 09:00:00.000000+00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7c9d1e3f5b2"
down_revision: str | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("strategies", sa.Column("max_daily_buys", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("strategies", "max_daily_buys")
