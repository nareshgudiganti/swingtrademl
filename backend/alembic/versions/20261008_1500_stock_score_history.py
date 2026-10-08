"""Daily strength score per stock

Revision ID: s7k5c0r3h1s9
Revises: p5c0r3h1s7y1
Create Date: 2026-10-08 15:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "s7k5c0r3h1s9"
down_revision: str | None = "p5c0r3h1s7y1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stock_score_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "instrument_id", sa.Integer(), sa.ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("band", sa.String(8), nullable=False),
        sa.Column("model_version", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("instrument_id", "as_of", name="uq_stock_score_day"),
    )
    op.create_index("ix_stock_score_history_instrument_id", "stock_score_history", ["instrument_id"])


def downgrade() -> None:
    op.drop_index("ix_stock_score_history_instrument_id", table_name="stock_score_history")
    op.drop_table("stock_score_history")
