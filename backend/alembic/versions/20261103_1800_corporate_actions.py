# ruff: noqa: E501 (long explanatory lines)
"""corporate actions: corporate_actions and position_adjustments

Two new tables, nothing else. No existing table or row is touched, and neither table has a foreign key into orders
or trades. The upgrade is safe to run twice. The downgrade drops only these two tables.

Revision ID: corpact1a2b3
Revises: mdlrole1a2b3
Create Date: 2026-11-03 18:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "corpact1a2b3"
down_revision: str | None = "mdlrole1a2b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "corporate_actions" not in existing:
        op.create_table(
            "corporate_actions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "instrument_id",
                sa.Integer(),
                sa.ForeignKey("instruments.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("symbol", sa.String(32), nullable=False),
            sa.Column("kind", sa.String(16), nullable=False),
            sa.Column("ex_date", sa.Date(), nullable=False),
            sa.Column("ratio_numerator", sa.Integer(), nullable=True),
            sa.Column("ratio_denominator", sa.Integer(), nullable=True),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("status", sa.String(12), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("instrument_id", "kind", "ex_date", name="uq_corporate_action"),
        )
        op.create_index("ix_corporate_actions_instrument_id", "corporate_actions", ["instrument_id"])
    if "position_adjustments" not in existing:
        op.create_table(
            "position_adjustments",
            sa.Column("id", sa.BigInteger(), primary_key=True),
            sa.Column(
                "action_id",
                sa.Integer(),
                sa.ForeignKey("corporate_actions.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "position_id",
                sa.BigInteger(),
                sa.ForeignKey("positions.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("book", sa.String(8), nullable=False),
            sa.Column("status", sa.String(14), nullable=False),
            sa.Column("before", postgresql.JSONB(), nullable=False),
            sa.Column("after", postgresql.JSONB(), nullable=True),
            sa.Column("expected_exit", postgresql.JSONB(), nullable=True),
            sa.Column("explanation", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("action_id", "position_id", name="uq_position_adjustment"),
        )
        op.create_index("ix_position_adjustments_action_id", "position_adjustments", ["action_id"])
        op.create_index("ix_position_adjustments_position_id", "position_adjustments", ["position_id"])


def downgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "position_adjustments" in existing:
        op.drop_table("position_adjustments")
    if "corporate_actions" in existing:
        op.drop_table("corporate_actions")
