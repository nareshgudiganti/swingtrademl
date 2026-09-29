"""plan_settings

The owner's master switch for Free / Plus / Pro plans. It starts OFF: until
the owner turns it on in the Plans Manager, every signed-in account sees
the whole app exactly as before plans existed. A new table only, so the
code from before plans still runs on this database unchanged.

Revision ID: 5a2f9d4e8c13
Revises: 3e8a5c1d7b90
Create Date: 2026-09-29 15:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5a2f9d4e8c13"
down_revision: str | None = "3e8a5c1d7b90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "plan_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plan_settings")),
    )


def downgrade() -> None:
    op.drop_table("plan_settings")
