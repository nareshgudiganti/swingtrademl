"""Support Google sign-in alongside local username/password accounts.

Revision ID: 0002_user_auth_providers
Revises: 0001_initial
Create Date: 2026-08-04 11:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_user_auth_providers"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("auth_provider", sa.String(length=16), nullable=False, server_default="local"),
    )
    op.add_column("users", sa.Column("google_id", sa.String(length=64), nullable=True))
    op.create_index(op.f("ix_users_google_id"), "users", ["google_id"], unique=True)

    # Google-authenticated accounts have no local password to check.
    op.alter_column("users", "hashed_password", existing_type=sa.String(length=255), nullable=True)


def downgrade() -> None:
    op.alter_column("users", "hashed_password", existing_type=sa.String(length=255), nullable=False)
    op.drop_index(op.f("ix_users_google_id"), table_name="users")
    op.drop_column("users", "google_id")
    op.drop_column("users", "auth_provider")
