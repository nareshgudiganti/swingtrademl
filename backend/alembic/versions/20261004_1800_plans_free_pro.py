"""Drop Plus tier; migrate plus users to free.

Revision ID: p1a2n3s4f5r6
Revises: f4a2c8e1d930
Create Date: 2026-10-04 18:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "p1a2n3s4f5r6"
down_revision: str | None = "f4a2c8e1d930"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # This revision sits on the main branch, but users.plan and subscription_plans
    # are created on the plans branch (3e8a5c1d7b90), which the merge revision only
    # joins afterwards. On a database that has not run the plans branch yet there
    # is nothing to migrate: the plans branch starts everyone on Free with no Plus.
    inspector = sa.inspect(op.get_bind())
    if "plan" in {c["name"] for c in inspector.get_columns("users")}:
        op.execute("UPDATE users SET plan = 'free' WHERE plan = 'plus'")
    if inspector.has_table("subscription_plans"):
        op.execute("DELETE FROM subscription_plans WHERE key = 'plus'")


def downgrade() -> None:
    pass
