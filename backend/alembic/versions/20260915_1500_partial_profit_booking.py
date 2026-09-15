"""partial_profit_booking

Revision ID: b95286c2ad43
Revises: c4a1f7b28d93
Create Date: 2026-09-15 15:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b95286c2ad43"
down_revision: str | None = "c4a1f7b28d93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Both columns are nullable, so no server_default is needed. `quantity`
    # keeps meaning "shares held now" (see the Position model for why that,
    # rather than a new quantity_remaining column, was chosen); these two only
    # add what a partial exit needs on top of it.
    op.add_column("positions", sa.Column("initial_quantity", sa.Integer(), nullable=True))
    op.add_column(
        "positions", sa.Column("scaled_out_at", sa.DateTime(timezone=True), nullable=True)
    )

    # Every existing position — open or closed — predates partial exits, so
    # nothing has ever been sold from one piecemeal: what it holds (or held at
    # close) is exactly what was bought.
    op.execute("UPDATE positions SET initial_quantity = quantity WHERE initial_quantity IS NULL")


def downgrade() -> None:
    # An OPEN position that has already scaled out holds fewer shares than it
    # bought, and its first slice lives on as a Trade row. Dropping these
    # columns leaves `quantity` as the shares still held, which is what the
    # pre-partial-exit code reads it as, so cash and valuation stay correct;
    # only the record of the original size is lost.
    op.drop_column("positions", "scaled_out_at")
    op.drop_column("positions", "initial_quantity")
