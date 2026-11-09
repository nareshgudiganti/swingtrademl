"""user_watchlist_items.quantity: how many shares the person bought (display only)

One nullable column. Nothing in trading, sizing or the brain reads it. Safe to run twice.

Revision ID: wlquantity01
Revises: wlbuyprice01
Create Date: 2026-11-09 21:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "wlquantity01"
down_revision: str | None = "wlbuyprice01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column() -> bool:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("user_watchlist_items")}
    return "quantity" in cols


def upgrade() -> None:
    if not _has_column():
        op.add_column("user_watchlist_items", sa.Column("quantity", sa.Float(), nullable=True))


def downgrade() -> None:
    if _has_column():
        op.drop_column("user_watchlist_items", "quantity")
