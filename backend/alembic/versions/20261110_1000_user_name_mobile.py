"""users.full_name, users.mobile (optional, unverified, NOT unique), users.email_verified_at

Three nullable columns. Mobile is a profile detail only: not unique, not a login key.
email_verified_at stays NULL for everyone except Google accounts that have an email
(Google already verified it), which get now(). Nothing enforces verification here, so
every existing login works as before. Nothing in trading, sizing or the brain reads these.
Also drops the unique ix_users_mobile index if an earlier draft of this migration made it.
Safe to run twice.

Revision ID: usernamemob01
Revises: mergeheads01
Create Date: 2026-11-10 10:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "usernamemob01"
down_revision: str | None = "mergeheads01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_INDEX = "ix_users_mobile"


def _state() -> tuple[set[str], set[str]]:
    insp = sa.inspect(op.get_bind())
    cols = {c["name"] for c in insp.get_columns("users")}
    idx = {i["name"] for i in insp.get_indexes("users")}
    return cols, idx


def upgrade() -> None:
    cols, idx = _state()
    if OLD_INDEX in idx:
        op.drop_index(OLD_INDEX, table_name="users")
    if "full_name" not in cols:
        op.add_column("users", sa.Column("full_name", sa.String(80), nullable=True))
    if "mobile" not in cols:
        op.add_column("users", sa.Column("mobile", sa.String(10), nullable=True))
    if "email_verified_at" not in cols:
        op.add_column("users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))
        # Google already verified these addresses. Only on first add, so a re-run never
        # overwrites anything.
        op.execute(
            "UPDATE users SET email_verified_at = now() "
            "WHERE auth_provider = 'google' AND email IS NOT NULL AND email <> ''"
        )


def downgrade() -> None:
    cols, idx = _state()
    if OLD_INDEX in idx:
        op.drop_index(OLD_INDEX, table_name="users")
    for name in ("email_verified_at", "mobile", "full_name"):
        if name in cols:
            op.drop_column("users", name)
