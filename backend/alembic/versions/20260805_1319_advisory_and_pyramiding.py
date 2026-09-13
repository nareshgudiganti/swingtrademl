"""advisory_and_pyramiding

Revision ID: e62313e04cc8
Revises: 0002_user_auth_providers
Create Date: 2026-08-05 13:19:36.978265+00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e62313e04cc8"
down_revision: str | None = "0002_user_auth_providers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Server defaults are required, not cosmetic — strategies/signals already
    # have rows in every real deployment (including this dev DB), and these
    # columns are NOT NULL.
    op.add_column(
        "strategies",
        sa.Column("execution_mode", sa.String(length=16), nullable=False, server_default="auto"),
    )
    op.add_column(
        "strategies",
        sa.Column("allow_pyramiding", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(
        op.f("ix_strategies_execution_mode"), "strategies", ["execution_mode"], unique=False
    )

    op.add_column(
        "signals",
        sa.Column("advisory_only", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(op.f("ix_signals_advisory_only"), "signals", ["advisory_only"], unique=False)

    op.add_column(
        "positions", sa.Column("advisory_alert_sent_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("positions", "advisory_alert_sent_at")
    op.drop_index(op.f("ix_signals_advisory_only"), table_name="signals")
    op.drop_column("signals", "advisory_only")
    op.drop_index(op.f("ix_strategies_execution_mode"), table_name="strategies")
    op.drop_column("strategies", "allow_pyramiding")
    op.drop_column("strategies", "execution_mode")
