"""trailing_stop

Revision ID: b8e4f2a91c67
Revises: a7c9d1e3f5b2
Create Date: 2026-08-22 09:00:00.000000+00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8e4f2a91c67"
down_revision: str | None = "a7c9d1e3f5b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # stop_loss becomes the ACTIVE stop (ratcheted up as highest_price
    # advances — see services/execution.py's trail_stop()). initial_stop_loss
    # freezes the ATR-based distance the strategy set at entry, which the
    # trail needs as its fixed anchor: once stop_loss itself starts moving,
    # you cannot recover "how far below the high should this trail" from it
    # alone.
    op.add_column("positions", sa.Column("initial_stop_loss", sa.Float(), nullable=True))
    op.execute("UPDATE positions SET initial_stop_loss = stop_loss WHERE stop_loss IS NOT NULL")


def downgrade() -> None:
    op.drop_column("positions", "initial_stop_loss")
