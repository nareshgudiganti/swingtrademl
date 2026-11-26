# ruff: noqa: E501 (long plain-English docstring)
"""Nullable security_id on instruments and user_watchlist_items (#389 decision 4).

Additive only: one nullable integer column per table, a foreign key to securities.id (ON DELETE RESTRICT, so a
security that is still in use cannot be deleted) and an index. No row is changed and nothing is backfilled here:
existing rows keep NULL until the separate, owner-approved backfill links them. Nothing reads the columns yet.
Downgrade drops the indexes, keys and columns.

Revision ID: secid01
Revises: signalkey01
Create Date: 2026-11-26 13:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "secid01"
down_revision: str | None = "signalkey01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("instruments", "user_watchlist_items")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column("security_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_security_id", table, "securities", ["security_id"], ["id"], ondelete="RESTRICT"
        )
        op.create_index(f"ix_{table}_security_id", table, ["security_id"])


def downgrade() -> None:
    for table in TABLES:
        op.drop_index(f"ix_{table}_security_id", table_name=table)
        op.drop_constraint(f"fk_{table}_security_id", table, type_="foreignkey")
        op.drop_column(table, "security_id")
