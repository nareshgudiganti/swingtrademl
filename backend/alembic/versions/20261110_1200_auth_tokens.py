"""auth_tokens: one-time email tokens (verify email, reset password), hash only

Revision ID: authtokens01
Revises: usernamemob01
Create Date: 2026-11-10 12:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "authtokens01"
down_revision: str | None = "usernamemob01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if "auth_tokens" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "auth_tokens",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_ip", sa.String(64), nullable=True),
    )
    op.create_index("ix_auth_tokens_user_id", "auth_tokens", ["user_id"])


def downgrade() -> None:
    if "auth_tokens" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("auth_tokens")
