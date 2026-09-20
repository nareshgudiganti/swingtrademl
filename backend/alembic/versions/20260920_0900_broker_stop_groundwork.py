"""broker_stop_groundwork

Revision ID: f1c93a7e2d58
Revises: d5b2c8a39e04
Create Date: 2026-09-20 09:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f1c93a7e2d58"
down_revision: str | None = "d5b2c8a39e04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Every column here is nullable or carries a server default, so code that
    # predates this migration keeps inserting orders and positions against the
    # migrated schema without knowing any of them exist.

    # Why an exit was placed, stamped at placement. Without it, reconciliation
    # had nothing to read back and recorded every filled sell as MANUAL — a
    # stop-loss, a target hit and a time stop all graded identically.
    op.add_column("orders", sa.Column("exit_reason", sa.String(length=24), nullable=True))

    # The sell-once latch. A timestamp rather than a flag so a process killed
    # between claiming and selling expires instead of stranding the position.
    op.add_column(
        "positions", sa.Column("exit_in_progress_at", sa.DateTime(timezone=True), nullable=True)
    )
    # No backfill: nothing has ever claimed a position, so NULL ("not being
    # sold") is already correct for every existing row.

    # The broker-held stop (Zerodha GTT). Nothing writes to these yet — they
    # ship with the latch above so the table is altered once rather than twice.
    op.add_column("positions", sa.Column("broker_stop_id", sa.String(length=64), nullable=True))
    op.add_column("positions", sa.Column("broker_stop_trigger", sa.Float(), nullable=True))
    op.add_column("positions", sa.Column("broker_stop_qty", sa.Integer(), nullable=True))
    op.add_column(
        "positions",
        sa.Column(
            "broker_stop_state",
            sa.String(length=16),
            nullable=False,
            # "no stop at the broker" is the truth for every existing row and
            # the safe reading of any row written by code that predates this.
            server_default="NONE",
        ),
    )
    op.add_column("positions", sa.Column("broker_stop_error", sa.Text(), nullable=True))
    op.add_column(
        "positions", sa.Column("broker_stop_synced_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(op.f("ix_positions_broker_stop_id"), "positions", ["broker_stop_id"], unique=False)
    op.create_index(
        op.f("ix_positions_broker_stop_state"), "positions", ["broker_stop_state"], unique=False
    )


def downgrade() -> None:
    # Safe in both directions: the older code neither reads nor writes any of
    # these. Losing exit_reason costs the grading label on orders still
    # unreconciled at the moment of the rollback — the exits themselves, and
    # every Trade row already written, are untouched. A stop actually held at
    # the broker would survive the rollback out there while its id is
    # forgotten here, which is the one thing to re-check before rolling back
    # once the GTT side is live.
    op.drop_index(op.f("ix_positions_broker_stop_state"), table_name="positions")
    op.drop_index(op.f("ix_positions_broker_stop_id"), table_name="positions")
    op.drop_column("positions", "broker_stop_synced_at")
    op.drop_column("positions", "broker_stop_error")
    op.drop_column("positions", "broker_stop_state")
    op.drop_column("positions", "broker_stop_qty")
    op.drop_column("positions", "broker_stop_trigger")
    op.drop_column("positions", "broker_stop_id")
    op.drop_column("positions", "exit_in_progress_at")
    op.drop_column("orders", "exit_reason")
