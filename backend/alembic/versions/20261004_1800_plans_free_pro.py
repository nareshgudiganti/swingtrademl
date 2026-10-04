"""Drop Plus tier; migrate plus users to free.

Revision ID: a1b2c3d4e5f6
Revises: f4a2c8e1d930
Create Date: 2026-10-04 18:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "f4a2c8e1d930"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE users SET plan = 'free' WHERE plan = 'plus'")
    op.execute("DELETE FROM subscription_plans WHERE key = 'plus'")


def downgrade() -> None:
    pass
