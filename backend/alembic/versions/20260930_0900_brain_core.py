"""brain_core: the brain's run log, its decisions, and per-module switches

Revision ID: 3e8b5c1d7a90
Revises: b7d1e94c2a58
Create Date: 2026-09-30 09:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3e8b5c1d7a90"
down_revision: str | None = "b7d1e94c2a58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "brain_runs",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("book", sa.String(8), nullable=False),
        sa.Column("live", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="done"),
        sa.Column("error", sa.Text()),
        sa.Column("banner_mode", sa.String(16)),
        sa.Column("banner_headline", sa.Text()),
        sa.Column("modules", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("trace", postgresql.JSONB(), nullable=False, server_default="[]"),
    )
    op.create_index("ix_brain_runs_kind", "brain_runs", ["kind"])
    op.create_index("ix_brain_runs_as_of", "brain_runs", ["as_of"])
    op.create_index("ix_brain_runs_started_at", "brain_runs", ["started_at"])

    op.create_table(
        "brain_decisions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "run_id", sa.String(40), sa.ForeignKey("brain_runs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("word", sa.String(8), nullable=False),
        sa.Column("entry_low", sa.Float()),
        sa.Column("entry_high", sa.Float()),
        sa.Column("target", sa.Float()),
        sa.Column("stop", sa.Float()),
        sa.Column("qty", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("horizon_days", sa.Integer(), nullable=False, server_default="15"),
        sa.Column("confidence", sa.Float()),
        sa.Column("evidence_text", sa.Text()),
        sa.Column("reasons", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("downgraded_from", sa.String(8)),
        sa.Column("downgrade_reason", sa.Text()),
    )
    op.create_index("ix_brain_decisions_run_id", "brain_decisions", ["run_id"])
    op.create_index("ix_brain_decisions_symbol", "brain_decisions", ["symbol"])
    op.create_index("ix_brain_decisions_word", "brain_decisions", ["word"])

    op.create_table(
        "brain_modules",
        sa.Column("module_id", sa.String(8), primary_key=True),
        sa.Column("mode", sa.String(8), nullable=False),
        sa.Column("changed_by", sa.String(128)),
        sa.Column("note", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("brain_modules")
    op.drop_index("ix_brain_decisions_word", table_name="brain_decisions")
    op.drop_index("ix_brain_decisions_symbol", table_name="brain_decisions")
    op.drop_index("ix_brain_decisions_run_id", table_name="brain_decisions")
    op.drop_table("brain_decisions")
    op.drop_index("ix_brain_runs_started_at", table_name="brain_runs")
    op.drop_index("ix_brain_runs_as_of", table_name="brain_runs")
    op.drop_index("ix_brain_runs_kind", table_name="brain_runs")
    op.drop_table("brain_runs")
