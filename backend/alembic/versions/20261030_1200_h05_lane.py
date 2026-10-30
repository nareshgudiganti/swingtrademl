"""h05 lane: four new tables for the 5-trading-day evaluation of the existing models

New tables only (h05_runs, h05_group_days, h05_signals, h05_events); no existing table is touched and nothing
references a money table. The lane is disabled by default, so the tables stay empty until the owner
accepts the protocol.

Revision ID: h05l4n3e1a2b
Revises: f9c3o7m1p5n2
Create Date: 2026-10-30 12:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "h05l4n3e1a2b"
down_revision: str | None = "f9c3o7m1p5n2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "h05_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_no", sa.SmallInteger(), nullable=False, unique=True),
        sa.Column("protocol_code", sa.String(64), nullable=False),
        sa.Column("protocol_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="active"),
        sa.Column("start_day", sa.Date(), nullable=False),
        sa.Column("end_day", sa.Date(), nullable=False),
        sa.Column("models", postgresql.JSONB(), nullable=False),
        sa.Column("universe", postgresql.JSONB(), nullable=False),
        sa.Column("universe_hash", sa.String(64), nullable=False),
        sa.Column("parity", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "h05_group_days",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("h05_runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("signal_day", sa.Date(), nullable=False),
        sa.Column("group", sa.String(8), nullable=False),
        sa.Column("universe_n", sa.Integer(), nullable=False),
        sa.Column("scored_n", sa.Integer(), nullable=False),
        sa.Column("not_scored_n", sa.Integer(), nullable=False),
        sa.Column("selected_n", sa.Integer(), nullable=False),
        sa.Column("shortfall", sa.Integer(), nullable=False),
        sa.Column("provenance", postgresql.JSONB()),
        sa.Column("recorded_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("run_id", "signal_day", "group", name="uq_h05_group_days_key"),
    )
    op.create_index("ix_h05_group_days_run_id", "h05_group_days", ["run_id"])
    op.create_table(
        "h05_signals",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("h05_runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("signal_day", sa.Date(), nullable=False),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("group", sa.String(8), nullable=False),
        sa.Column("instrument_id", sa.Integer()),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("not_scored_reason", sa.String(80)),
        sa.Column("model_id", sa.Integer()),
        sa.Column("model_version", sa.String(32)),
        sa.Column("trained_on_symbol", sa.Boolean()),
        sa.Column("score", sa.Float()),
        sa.Column("score_production_path", sa.Float()),
        sa.Column("group_rank", sa.Integer()),
        sa.Column("selected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("repeat_blocked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("signal_close", sa.Float()),
        sa.Column("avg_volume_20", sa.Float()),
        sa.Column("flags", postgresql.JSONB()),
        sa.Column("label_status", sa.String(14), nullable=False, server_default="pending"),
        sa.Column("label_day5", sa.Date()),
        sa.Column("label_close5", sa.Float()),
        sa.Column("label_hit", sa.SmallInteger()),
        sa.Column("label_note", sa.Text()),
        sa.Column("trade_status", sa.String(10), nullable=False, server_default="pending"),
        sa.Column("trade_note", sa.Text()),
        sa.Column("entry_day", sa.Date()),
        sa.Column("entry_open", sa.Float()),
        sa.Column("entry_fill", sa.Float()),
        sa.Column("exit_day", sa.Date()),
        sa.Column("exit_price", sa.Float()),
        sa.Column("exit_fill", sa.Float()),
        sa.Column("exit_reason", sa.String(10)),
        sa.Column("sessions_held", sa.SmallInteger()),
        sa.Column("gap_fill", sa.Boolean()),
        sa.Column("ambiguous", sa.Boolean()),
        sa.Column("costs_inr", sa.Float()),
        sa.Column("net_return", sa.Float()),
        sa.Column("trade_flags", postgresql.JSONB()),
        sa.Column("trade_status_stress", sa.String(10)),
        sa.Column("net_return_stress", sa.Float()),
        sa.Column("outcome_provenance", postgresql.JSONB()),
        sa.Column("evaluated_at", sa.DateTime(timezone=True)),
        sa.Column("recorded_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("run_id", "signal_day", "symbol", name="uq_h05_signals_key"),
    )
    op.create_index("ix_h05_signals_run_id", "h05_signals", ["run_id"])
    op.create_table(
        "h05_events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("h05_runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("signal_day", sa.Date()),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
    )
    op.create_index("ix_h05_events_run_id", "h05_events", ["run_id"])


def downgrade() -> None:
    op.drop_table("h05_events")
    op.drop_table("h05_signals")
    op.drop_table("h05_group_days")
    op.drop_table("h05_runs")
