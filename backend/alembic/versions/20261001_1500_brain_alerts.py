"""brain_alerts: what the owner was told after brain runs (M16)

Revision ID: 2f8c1a7e5d40
Revises: 9a4e6b2c8d15
Create Date: 2026-10-01 15:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2f8c1a7e5d40"
down_revision: str | None = "9a4e6b2c8d15"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "brain_alerts",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("alert_key", sa.String(96), nullable=False),
        sa.Column("alert_date", sa.Date(), nullable=False),
        sa.Column("run_id", sa.String(40), sa.ForeignKey("brain_runs.id", ondelete="SET NULL")),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False, server_default="telegram"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("alert_key", "alert_date", name="uq_brain_alerts_alert_key"),
    )
    op.create_index("ix_brain_alerts_alert_date", "brain_alerts", ["alert_date"])
    op.add_column("brain_runs", sa.Column("alerts_checked_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("brain_runs", "alerts_checked_at")
    op.drop_index("ix_brain_alerts_alert_date", table_name="brain_alerts")
    op.drop_table("brain_alerts")
