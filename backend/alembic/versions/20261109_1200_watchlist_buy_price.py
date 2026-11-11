"""user_watchlist_items.buy_price: the person's own Groww buy price (display only)

One nullable column. Nothing in trading, sizing or the brain reads it. Safe to run twice.

Revision ID: wlbuyprice01
Revises: corpact1a2b3
Create Date: 2026-11-09 12:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "wlbuyprice01"
down_revision: str | None = "corpact1a2b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column() -> bool:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("user_watchlist_items")}
    return "buy_price" in cols


def upgrade() -> None:
    if not _has_column():
        op.add_column("user_watchlist_items", sa.Column("buy_price", sa.Float(), nullable=True))


def downgrade() -> None:
    if _has_column():
        op.drop_column("user_watchlist_items", "buy_price")
