"""subscription_plans

Adds users.plan and the subscription_plans table (the owner's edits to the
Free / Plus / Pro defaults in core/plans.py).

The owner is whoever is_superuser marks; they keep seeing everything. Every
other account starts on Free, including ones that could see the whole app
before (nothing was plan-gated then) — the owner reassigns them in the Plans
Manager. If no account is a superuser yet, the first one ever created (the
owner's own, in practice) is promoted, so the deploy can never lock the owner
out. `swingtrade make-owner <username>` fixes it by hand if that guess is
wrong.

Revision ID: 3e8a5c1d7b90
Revises: b7d1e94c2a58
Create Date: 2026-09-29 12:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3e8a5c1d7b90"
down_revision: str | None = "b7d1e94c2a58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("plan", sa.String(length=16), server_default="free", nullable=False),
    )
    op.execute(
        """
        UPDATE users SET is_superuser = true
        WHERE id = (SELECT min(id) FROM users)
          AND NOT EXISTS (SELECT 1 FROM users WHERE is_superuser)
        """
    )

    op.create_table(
        "subscription_plans",
        sa.Column("key", sa.String(length=16), nullable=False),
        sa.Column("features", sa.JSON(), nullable=False),
        sa.Column("limits", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_subscription_plans")),
    )


def downgrade() -> None:
    op.drop_table("subscription_plans")
    op.drop_column("users", "plan")
