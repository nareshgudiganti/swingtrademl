"""Horizon experiments: research ledger tables (design rev 3)

Additive only. No foreign key to any money or brain table. `experiment_selections` is append-only (a trigger
refuses UPDATE and DELETE). Follows P0 security (e1p0s2e3c4u5); B1 must follow this revision.

Revision ID: h0r1z5e7x3p1
Revises: e1p0s2e3c4u5
Create Date: 2026-10-17 20:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "h0r1z5e7x3p1"
down_revision: str | None = "e1p0s2e3c4u5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPEND_ONLY_FUNCTION = """
CREATE OR REPLACE FUNCTION experiment_selections_append_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'experiment_selections is append-only: % refused', TG_OP;
END;
$$ LANGUAGE plpgsql
"""
APPEND_ONLY_TRIGGER = """
CREATE TRIGGER experiment_selections_append_only
BEFORE UPDATE OR DELETE ON experiment_selections
FOR EACH ROW EXECUTE FUNCTION experiment_selections_append_only()
"""


def upgrade() -> None:
    op.create_table(
        "experiment_protocols",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("params", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("code", name="uq_experiment_protocols_code"),
    )
    op.create_table(
        "experiment_cohorts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "protocol_id",
            sa.Integer(),
            sa.ForeignKey(
                "experiment_protocols.id",
                ondelete="RESTRICT",
                name="fk_experiment_cohorts_protocol_id_experiment_protocols",
            ),
            nullable=False,
        ),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("protocol_id", "source", "name", name="uq_experiment_cohorts_key"),
    )
    op.create_index("ix_experiment_cohorts_protocol_id", "experiment_cohorts", ["protocol_id"])
    op.create_table(
        "experiment_selections",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "cohort_id",
            sa.Integer(),
            sa.ForeignKey(
                "experiment_cohorts.id",
                ondelete="RESTRICT",
                name="fk_experiment_selections_cohort_id_experiment_cohorts",
            ),
            nullable=False,
        ),
        sa.Column(
            "instrument_id",
            sa.Integer(),
            sa.ForeignKey(
                "instruments.id",
                ondelete="RESTRICT",
                name="fk_experiment_selections_instrument_id_instruments",
            ),
            nullable=True,
        ),
        sa.Column("symbol_at_entry", sa.String(64), nullable=False),
        sa.Column("intended_horizon", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submitted_by", sa.String(64), nullable=False),
        sa.Column("entry_session", sa.Date(), nullable=True),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.Column(
            "supersedes_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "experiment_selections.id",
                ondelete="RESTRICT",
                name="fk_experiment_selections_supersedes_id_experiment_selections",
            ),
            nullable=True,
        ),
    )
    for col in ("cohort_id", "instrument_id", "entry_session", "supersedes_id"):
        op.create_index(f"ix_experiment_selections_{col}", "experiment_selections", [col])
    op.execute(APPEND_ONLY_FUNCTION)
    op.execute(APPEND_ONLY_TRIGGER)
    op.create_table(
        "experiment_outcomes",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "selection_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "experiment_selections.id",
                ondelete="RESTRICT",
                name="fk_experiment_outcomes_selection_id_experiment_selections",
            ),
            nullable=False,
        ),
        sa.Column("horizon", sa.Integer(), nullable=False),
        sa.Column(
            "protocol_id",
            sa.Integer(),
            sa.ForeignKey(
                "experiment_protocols.id",
                ondelete="RESTRICT",
                name="fk_experiment_outcomes_protocol_id_experiment_protocols",
            ),
            nullable=False,
        ),
        sa.Column("state", sa.String(12), nullable=False),
        *[
            sa.Column(name, sa.Float(), nullable=True)
            for name in (
                "entry_price",
                "exit_price",
                "gross_return",
                "costs_inr",
                "slippage_inr",
                "net_return",
                "nifty_return",
                "universe_return",
                "buy_hold_return",
                "excess_vs_nifty",
                "excess_vs_universe",
            )
        ],
        sa.Column("exit_session", sa.Date(), nullable=True),
        sa.Column("mark_session", sa.Date(), nullable=True),
        sa.Column("universe_count", sa.Integer(), nullable=True),
        sa.Column("data_flags", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scorer_version", sa.String(32), nullable=False),
        sa.UniqueConstraint("selection_id", "horizon", "protocol_id", name="uq_experiment_outcomes_key"),
    )
    op.create_index("ix_experiment_outcomes_selection_id", "experiment_outcomes", ["selection_id"])
    op.create_table(
        "experiment_job_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("rows_scored", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_flagged", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("experiment_job_runs")
    op.drop_index("ix_experiment_outcomes_selection_id", table_name="experiment_outcomes")
    op.drop_table("experiment_outcomes")
    op.execute("DROP TRIGGER IF EXISTS experiment_selections_append_only ON experiment_selections")
    op.execute("DROP FUNCTION IF EXISTS experiment_selections_append_only()")
    for col in ("cohort_id", "instrument_id", "entry_session", "supersedes_id"):
        op.drop_index(f"ix_experiment_selections_{col}", table_name="experiment_selections")
    op.drop_table("experiment_selections")
    op.drop_index("ix_experiment_cohorts_protocol_id", table_name="experiment_cohorts")
    op.drop_table("experiment_cohorts")
    op.drop_table("experiment_protocols")
