"""Stock score trail keyed by model: one row per stock, day and model

Revision ID: f11m0d3l5c0r3
Revises: wlquantity01
Create Date: 2026-11-10 16:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f11m0d3l5c0r3"
down_revision: str | None = "wlquantity01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "stock_score_history",
        sa.Column("model_name", sa.String(64), nullable=False, server_default=""),
    )
    # Old rows: the name is whatever sits before the first colon of "name:version".
    op.execute(
        "UPDATE stock_score_history SET model_name = split_part(model_version, ':', 1) "
        "WHERE model_version IS NOT NULL"
    )
    op.drop_constraint("uq_stock_score_day", "stock_score_history", type_="unique")
    op.create_unique_constraint(
        "uq_stock_score_day_model", "stock_score_history", ["instrument_id", "as_of", "model_name"]
    )


def downgrade() -> None:
    # Keep the newest row per stock and day, then restore the old one-per-day key.
    op.execute(
        "DELETE FROM stock_score_history a USING stock_score_history b "
        "WHERE a.instrument_id = b.instrument_id AND a.as_of = b.as_of AND a.id < b.id"
    )
    op.drop_constraint("uq_stock_score_day_model", "stock_score_history", type_="unique")
    op.create_unique_constraint("uq_stock_score_day", "stock_score_history", ["instrument_id", "as_of"])
    op.drop_column("stock_score_history", "model_name")
