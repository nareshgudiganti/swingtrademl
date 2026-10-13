"""One stored brain check per trading day

Revision ID: d8a1y2c3h4k5
Revises: c4a7r1v2l3s4
Create Date: 2026-10-13 22:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d8a1y2c3h4k5"
down_revision: str | None = "c4a7r1v2l3s4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "brain_daily_checks",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("checks", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("run", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("intraday", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("trial", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.UniqueConstraint("day", name="uq_brain_daily_checks_day"),
    )
    op.create_index("ix_brain_daily_checks_day", "brain_daily_checks", ["day"])


def downgrade() -> None:
    op.drop_index("ix_brain_daily_checks_day", table_name="brain_daily_checks")
    op.drop_table("brain_daily_checks")
