"""Daily strength score per held position

Revision ID: p5c0r3h1s7y1
Revises: w7h3a1t5h0c1
Create Date: 2026-10-08 12:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "p5c0r3h1s7y1"
down_revision: str | None = "w7h3a1t5h0c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "position_score_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "position_id", sa.BigInteger(), sa.ForeignKey("positions.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("band", sa.String(8), nullable=False),
        sa.Column("model_version", sa.String(64)),
        sa.Column("alerted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("position_id", "as_of", name="uq_position_score_day"),
    )
    op.create_index("ix_position_score_history_position_id", "position_score_history", ["position_id"])


def downgrade() -> None:
    op.drop_index("ix_position_score_history_position_id", table_name="position_score_history")
    op.drop_table("position_score_history")
