"""avoid_lists

Revision ID: b7d1e94c2a58
Revises: 9c4b7e2a1f36
Create Date: 2026-09-21 16:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7d1e94c2a58"
down_revision: str | None = "9c4b7e2a1f36"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    # New tables only — nothing existing is altered.
    op.create_table(
        "upcoming_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("detail", sa.String(length=400), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", "kind", "event_date", name="uq_upcoming_event"),
    )
    op.create_index(op.f("ix_upcoming_events_symbol"), "upcoming_events", ["symbol"], unique=False)
    op.create_index(op.f("ix_upcoming_events_event_date"), "upcoming_events", ["event_date"], unique=False)

    op.create_table(
        "trading_restrictions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", "kind", "as_of", name="uq_trading_restriction"),
    )
    op.create_index(op.f("ix_trading_restrictions_symbol"), "trading_restrictions", ["symbol"], unique=False)
    op.create_index(op.f("ix_trading_restrictions_as_of"), "trading_restrictions", ["as_of"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_trading_restrictions_as_of"), table_name="trading_restrictions")
    op.drop_index(op.f("ix_trading_restrictions_symbol"), table_name="trading_restrictions")
    op.drop_table("trading_restrictions")
    op.drop_index(op.f("ix_upcoming_events_event_date"), table_name="upcoming_events")
    op.drop_index(op.f("ix_upcoming_events_symbol"), table_name="upcoming_events")
    op.drop_table("upcoming_events")
