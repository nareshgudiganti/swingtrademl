"""users.full_name and users.mobile (unique, nullable, unverified)

Two nullable columns plus a unique index on mobile. Existing users have neither; Postgres
lets many NULLs share a unique index. Nothing in trading, sizing or the brain reads them.
Safe to run twice.

Revision ID: usernamemob01
Revises: wlquantity01
Create Date: 2026-11-10 10:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "usernamemob01"
down_revision: str | None = "wlquantity01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "ix_users_mobile"


def _state() -> tuple[set[str], set[str]]:
    insp = sa.inspect(op.get_bind())
    cols = {c["name"] for c in insp.get_columns("users")}
    idx = {i["name"] for i in insp.get_indexes("users")}
    return cols, idx


def upgrade() -> None:
    cols, idx = _state()
    if "full_name" not in cols:
        op.add_column("users", sa.Column("full_name", sa.String(80), nullable=True))
    if "mobile" not in cols:
        op.add_column("users", sa.Column("mobile", sa.String(10), nullable=True))
    if INDEX not in idx:
        op.create_index(INDEX, "users", ["mobile"], unique=True)


def downgrade() -> None:
    cols, idx = _state()
    if INDEX in idx:
        op.drop_index(INDEX, table_name="users")
    if "mobile" in cols:
        op.drop_column("users", "mobile")
    if "full_name" in cols:
        op.drop_column("users", "full_name")
