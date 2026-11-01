# ruff: noqa: E501 (long explanatory lines)
"""model registry phase 1: model_research_slots

One new table with nine seeded rows. No existing table is touched. The upgrade is safe to run twice (it
skips a table that already exists and never overwrites a seeded row). The downgrade deliberately does
NOT drop the table: rolling back means reverting the application code first, and the owner's research
notes must never be lost by a schema step. Dropping the table is a separate manual decision.

Revision ID: mrs5p1a8c3d2
Revises: h05l4n3e1a2b
Create Date: 2026-11-01 12:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "mrs5p1a8c3d2"
down_revision: str | None = "h05l4n3e1a2b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (slot_key, horizon, tier, research_status, priority) - the owner's order: 15D large, 15D mid, 10D large;
# the three existing 5-day models are being researched (the 5-day test is collecting evidence).
SEED = [
    ("15d-large", 15, "large", "not_started", 1),
    ("15d-midcap", 15, "midcap", "not_started", 2),
    ("15d-smallcap", 15, "smallcap", "not_started", None),
    ("10d-large", 10, "large", "not_started", 3),
    ("10d-midcap", 10, "midcap", "not_started", None),
    ("10d-smallcap", 10, "smallcap", "not_started", None),
    ("5d-large", 5, "large", "researching", None),
    ("5d-midcap", 5, "midcap", "researching", None),
    ("5d-smallcap", 5, "smallcap", "researching", None),
]


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("model_research_slots"):
        op.create_table(
            "model_research_slots",
            sa.Column("slot_key", sa.String(16), primary_key=True),
            sa.Column("horizon_days", sa.Integer(), nullable=False),
            sa.Column("cap_tier", sa.String(12), nullable=False),
            sa.Column("research_status", sa.String(16), nullable=False, server_default="not_started"),
            sa.Column("priority", sa.Integer()),
            sa.Column("note", sa.Text()),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_by", sa.String(128)),
        )
    for key, horizon, tier, status, priority in SEED:
        bind.execute(
            sa.text(
                "INSERT INTO model_research_slots (slot_key, horizon_days, cap_tier, research_status, priority, "
                "updated_by) VALUES (:k, :h, :t, :s, :p, 'migration') ON CONFLICT (slot_key) DO NOTHING"
            ),
            {"k": key, "h": horizon, "t": tier, "s": status, "p": priority},
        )


def downgrade() -> None:
    # Intentionally empty: keep the owner's notes. Revert the application code first; drop the table by hand only
    # if the owner decides to.
    pass
