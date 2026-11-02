# ruff: noqa: E501 (long explanatory lines)
"""shared shadow lanes: lane_picks and lane_outcomes (append-only)

Two new tables. No existing table is touched. Triggers make both tables append-only at the database level:
UPDATE, DELETE and TRUNCATE raise an error, so a recorded pick or outcome can never be edited or removed.
The upgrade is safe to run twice (it skips tables that exist and recreates the triggers). The downgrade
deliberately does NOT drop anything: recorded evidence must never be lost by a schema step.

Revision ID: lane5h4d0w1a
Revises: mrs5p1a8c3d2
Create Date: 2026-11-02 12:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "lane5h4d0w1a"
down_revision: str | None = "mrs5p1a8c3d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("lane_picks", "lane_outcomes")

FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION lane_shadow_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP;
END;
$$ LANGUAGE plpgsql
"""


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table("lane_picks"):
        op.create_table(
            "lane_picks",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column(
                "model_id", sa.Integer(), sa.ForeignKey("ml_models.id", ondelete="RESTRICT"), nullable=False
            ),
            sa.Column("slot_key", sa.String(16), nullable=False),
            sa.Column("horizon_days", sa.Integer(), nullable=False),
            sa.Column("cap_group", sa.String(8), nullable=False),
            sa.Column("signal_day", sa.Date(), nullable=False),
            sa.Column("symbol", sa.String(32), nullable=False),
            sa.Column("rank", sa.Integer(), nullable=False),
            sa.Column("score", sa.Float(), nullable=False),
            sa.Column("model_version", sa.String(64), nullable=False),
            sa.Column(
                "recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
            ),
            sa.Column("entry_assumption", postgresql.JSONB(), nullable=False),
            sa.Column("target_pct", sa.Float(), nullable=False),
            sa.Column("stop_pct", sa.Float(), nullable=False),
            sa.Column("flags", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.UniqueConstraint("model_id", "signal_day", "symbol", name="uq_lane_picks_model_day_symbol"),
            sa.UniqueConstraint(
                "model_id", "signal_day", "cap_group", "rank", name="uq_lane_picks_model_day_group_rank"
            ),
        )
        op.create_index("ix_lane_picks_model_id", "lane_picks", ["model_id"])
        op.create_index("ix_lane_picks_slot_key", "lane_picks", ["slot_key"])
    if not insp.has_table("lane_outcomes"):
        op.create_table(
            "lane_outcomes",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column(
                "pick_id",
                sa.BigInteger(),
                sa.ForeignKey("lane_picks.id", ondelete="RESTRICT"),
                nullable=False,
                unique=True,
            ),
            sa.Column("matured_day", sa.Date(), nullable=False),
            sa.Column("status", sa.String(12), nullable=False),
            sa.Column("entry_fill", sa.Float()),
            sa.Column("exit_day", sa.Date()),
            sa.Column("exit_fill", sa.Float()),
            sa.Column("sessions_held", sa.Integer()),
            sa.Column("gross_return", sa.Float()),
            sa.Column("net_return", sa.Float()),
            sa.Column("baseline_net_return", sa.Float()),
            sa.Column("excess_return", sa.Float()),
            sa.Column("ambiguous", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column(
                "evaluated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
            ),
        )
    install_triggers(bind)


def install_triggers(bind) -> None:
    bind.execute(sa.text(FUNCTION_SQL))
    for table in TABLES:
        for op_name, level in (("UPDATE", "ROW"), ("DELETE", "ROW"), ("TRUNCATE", "STATEMENT")):
            name = f"trg_{table}_no_{op_name.lower()}"
            bind.execute(sa.text(f"DROP TRIGGER IF EXISTS {name} ON {table}"))
            bind.execute(
                sa.text(
                    f"CREATE TRIGGER {name} BEFORE {op_name} ON {table} "
                    f"FOR EACH {level} EXECUTE FUNCTION lane_shadow_append_only()"
                )
            )


def downgrade() -> None:
    # Intentionally empty: recorded evidence is kept. Revert the application code first; drop by hand only if the
    # owner decides to.
    pass
