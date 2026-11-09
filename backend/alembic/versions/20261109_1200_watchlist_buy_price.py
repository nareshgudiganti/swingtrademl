"""user_watchlist_items.buy_price and quantity: the person's own Groww entry (display only)

Two nullable columns. Nothing in trading, sizing or the brain reads them. Safe to run twice.

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

_COLUMNS = ("buy_price", "quantity")


def _have() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("user_watchlist_items")}


def upgrade() -> None:
    have = _have()
    for name in _COLUMNS:
        if name not in have:
            op.add_column("user_watchlist_items", sa.Column(name, sa.Float(), nullable=True))


def downgrade() -> None:
    have = _have()
    for name in reversed(_COLUMNS):
        if name in have:
            op.drop_column("user_watchlist_items", name)
