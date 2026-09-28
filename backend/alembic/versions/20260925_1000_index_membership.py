"""Cap tier, sector, and dated index-membership snapshots.

Revision ID: c5e2a83f1b70
Revises: b7d1e94c2a58
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "c5e2a83f1b70"
down_revision: str | None = "b7d1e94c2a58"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("instruments", sa.Column("cap_tier", sa.String(16), nullable=True))
    op.add_column("instruments", sa.Column("sector", sa.String(64), nullable=True))
    op.create_index("ix_instruments_cap_tier", "instruments", ["cap_tier"])

    op.create_table(
        "index_membership_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("fetched_on", sa.Date(), nullable=False),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("tier", sa.String(16), nullable=False),
        sa.Column("industry", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("fetched_on", "symbol", name="uq_index_membership_day_symbol"),
    )
    op.create_index("ix_index_membership_fetched_on", "index_membership_snapshots", ["fetched_on"])
    op.create_index("ix_index_membership_symbol", "index_membership_snapshots", ["symbol"])


def downgrade() -> None:
    op.drop_table("index_membership_snapshots")
    op.drop_index("ix_instruments_cap_tier", table_name="instruments")
    op.drop_column("instruments", "sector")
    op.drop_column("instruments", "cap_tier")
