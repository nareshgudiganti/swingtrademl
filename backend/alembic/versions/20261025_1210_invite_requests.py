"""Invite requests (New look wave 4): people ask for a place, the owner approves in Admin

One new table, nothing else touched. Sign-up stays closed (ALLOW_SIGNUP=False);
only an approved request's one-time code can create an ordinary account.

Revision ID: i4n5v1t3r2q7
Revises: u5w1l2s3t4i5
Create Date: 2026-10-25 12:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "i4n5v1t3r2q7"
down_revision: str | None = "u5w1l2s3t4i5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "invite_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("experience", sa.String(16), nullable=False),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.String(64), nullable=True),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("code_hash", sa.String(64), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_invite_requests_email", "invite_requests", ["email"])
    op.create_index(
        "uq_invite_requests_pending_email",
        "invite_requests",
        ["email"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("uq_invite_requests_pending_email", table_name="invite_requests")
    op.drop_index("ix_invite_requests_email", table_name="invite_requests")
    op.drop_table("invite_requests")
