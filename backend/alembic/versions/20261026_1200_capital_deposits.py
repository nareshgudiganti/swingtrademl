"""Capital deposits: money added to the paper account after it was first funded

One new table, nothing else touched. A top-up is recorded here so it is never read as profit.

Revision ID: c8d2p9s1t4k6
Revises: i4n5v1t3r2q7
Create Date: 2026-10-26 12:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c8d2p9s1t4k6"
down_revision: str | None = "i4n5v1t3r2q7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "capital_deposits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mode", sa.String(8), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("note", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_capital_deposits_mode", "capital_deposits", ["mode"])
    op.create_index("ix_capital_deposits_ts", "capital_deposits", ["ts"])


def downgrade() -> None:
    op.drop_index("ix_capital_deposits_ts", table_name="capital_deposits")
    op.drop_index("ix_capital_deposits_mode", table_name="capital_deposits")
    op.drop_table("capital_deposits")
