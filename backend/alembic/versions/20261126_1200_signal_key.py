# ruff: noqa: E501 (long plain-English docstring)
"""signals.signal_key: one row per scan decision (#360).

Additive only: one nullable column and one partial unique index (only where the key is set). Existing rows keep a
NULL key, are never backfilled and are ignored by the index. No row, limit or value is changed. Downgrade drops the
index and the column.

Revision ID: signalkey01
Revises: simulation02
Create Date: 2026-11-26 12:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "signalkey01"
down_revision: str | None = "simulation02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("signals", sa.Column("signal_key", sa.String(96), nullable=True))
    op.create_index(
        "uq_signals_signal_key",
        "signals",
        ["signal_key"],
        unique=True,
        postgresql_where=sa.text("signal_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_signals_signal_key", table_name="signals")
    op.drop_column("signals", "signal_key")
