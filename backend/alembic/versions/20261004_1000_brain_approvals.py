"""M18 go-live: brain ideas waiting for the owner's OK

Revision ID: e8b3f1a6c247
Revises: d2a7c4e9f150
Create Date: 2026-10-04 10:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e8b3f1a6c247"
down_revision: str | None = "d2a7c4e9f150"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "brain_approvals",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "signal_id",
            sa.BigInteger(),
            sa.ForeignKey("signals.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "strategy_id", sa.Integer(), sa.ForeignKey("strategies.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "instrument_id", sa.Integer(), sa.ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("decision_day", sa.Date(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("stop_loss", sa.Float(), nullable=True),
        sa.Column("take_profit", sa.Float(), nullable=True),
        sa.Column("suggested_qty", sa.Integer(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(12), nullable=False, server_default="pending"),
        sa.Column("decided_by", sa.String(128), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_note", sa.Text(), nullable=True),
        sa.Column(
            "position_id", sa.BigInteger(), sa.ForeignKey("positions.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("result_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_brain_approvals_status", "brain_approvals", ["status"])
    op.create_index("ix_brain_approvals_decision_day", "brain_approvals", ["decision_day"])


def downgrade() -> None:
    op.drop_index("ix_brain_approvals_decision_day", table_name="brain_approvals")
    op.drop_index("ix_brain_approvals_status", table_name="brain_approvals")
    op.drop_table("brain_approvals")
