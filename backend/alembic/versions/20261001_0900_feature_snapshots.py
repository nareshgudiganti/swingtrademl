"""feature_snapshots: what the brain saw for each stock each night (M02)

Revision ID: 9a4e6b2c8d15
Revises: 7c2d9e4f1b63
Create Date: 2026-10-01 09:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9a4e6b2c8d15"
down_revision: str | None = "7c2d9e4f1b63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feature_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("bar_date", sa.Date(), nullable=False),
        sa.Column("feature_set_version", sa.String(16), nullable=False),
        sa.Column("run_id", sa.String(40), sa.ForeignKey("brain_runs.id", ondelete="SET NULL")),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("atr_14", sa.Float()),
        sa.Column("adv_inr_20", sa.Float()),
        sa.Column("features", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("symbol", "bar_date", "feature_set_version", name="uq_feature_snapshots_symbol"),
    )
    op.create_index("ix_feature_snapshots_symbol", "feature_snapshots", ["symbol"])
    op.create_index("ix_feature_snapshots_bar_date", "feature_snapshots", ["bar_date"])


def downgrade() -> None:
    op.drop_index("ix_feature_snapshots_bar_date", table_name="feature_snapshots")
    op.drop_index("ix_feature_snapshots_symbol", table_name="feature_snapshots")
    op.drop_table("feature_snapshots")
