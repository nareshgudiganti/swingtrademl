"""When each daily bar first arrived (audit F-07, Service 1 gap #1)

A new table beside `candles`; the v1 candles table is not changed. Bars ingested
before this migration get no row: their arrival time is unknown.

Revision ID: c4a7r1v2l3s4
Revises: s7k5c0r3h1s9
Create Date: 2026-10-13 18:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4a7r1v2l3s4"
down_revision: str | None = "s7k5c0r3h1s9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candle_arrivals",
        sa.Column(
            "instrument_id", sa.Integer(), sa.ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("interval", sa.Text(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("instrument_id", "interval", "ts", name="pk_candle_arrivals"),
    )
    op.create_index("ix_candle_arrivals_received_at", "candle_arrivals", ["received_at"])


def downgrade() -> None:
    op.drop_index("ix_candle_arrivals_received_at", table_name="candle_arrivals")
    op.drop_table("candle_arrivals")
