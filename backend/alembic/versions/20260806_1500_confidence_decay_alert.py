"""confidence_decay_alert

Revision ID: f1a2b3c4d5e6
Revises: e62313e04cc8
Create Date: 2026-08-06 15:00:00.000000+00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: str | None = "e62313e04cc8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("positions", sa.Column("entry_confidence", sa.Float(), nullable=True))
    op.add_column("positions", sa.Column("last_confidence", sa.Float(), nullable=True))
    op.add_column(
        "positions", sa.Column("confidence_alert_sent_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("positions", "confidence_alert_sent_at")
    op.drop_column("positions", "last_confidence")
    op.drop_column("positions", "entry_confidence")
