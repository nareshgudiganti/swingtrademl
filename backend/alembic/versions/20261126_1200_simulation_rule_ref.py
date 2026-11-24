# ruff: noqa: E501 (long lines)
"""Simulation rows trace to a rule reference when there is no horizon record (#321 momentum picks)

Additive only: two nullable columns on `sim_runs` (`momentum_universe`, `momentum_universe_sha256`: the security ids
Momentum ranks, declared by the run), one nullable column `rule_ref` on `sim_fills`, `sim_exits` and `sim_blocks`, and one check on each saying
where a row traces to: a momentum row to the rule and version that made the pick (`rule_ref`), every other row to its
horizon record (and to no rule reference). No existing table is created or dropped and no existing row is rewritten. The
checks assume these tables hold no momentum row without a rule reference, which is true while nothing has written to them
outside tests; if an earlier run was stored, fill `rule_ref` on its momentum rows first.

Revision ID: simulation02
Revises: modswitch01
Create Date: 2026-11-26 12:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "simulation02"
down_revision: str | None = "modswitch01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("sim_fills", "sim_exits", "sim_blocks")
TRACE_CHECK = (
    "(policy = 'momentum' AND rule_ref IS NOT NULL) "
    "OR (policy <> 'momentum' AND horizon_record_id IS NOT NULL AND rule_ref IS NULL)"
)


def upgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column("rule_ref", sa.String(64), nullable=True))
        op.create_check_constraint(f"ck_{table}_trace", table, sa.text(TRACE_CHECK))
    # Momentum's declared universe is part of the run spec: the security ids (sorted JSON) and their sha256.
    op.add_column("sim_runs", sa.Column("momentum_universe", sa.Text, nullable=True))
    op.add_column("sim_runs", sa.Column("momentum_universe_sha256", sa.String(64), nullable=True))
    # A declared Momentum stock that was not ranked is recorded with its reason, never silently dropped.
    op.create_table(
        "sim_not_ranked",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("run_id", sa.BigInteger, sa.ForeignKey("sim_runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column(
            "security_id", sa.BigInteger, sa.ForeignKey("securities.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("reason", sa.String(255), nullable=False),
        sa.UniqueConstraint("run_id", "security_id", name="uq_sim_not_ranked_key"),
    )
    op.create_index("ix_sim_not_ranked_run_id", "sim_not_ranked", ["run_id"])
    op.create_index("ix_sim_not_ranked_security_id", "sim_not_ranked", ["security_id"])


def downgrade() -> None:
    # The columns, checks and table are new in this migration. Dropping `rule_ref` loses the momentum rule references, and
    # dropping the universe columns and `sim_not_ranked` loses each run's declared universe and its not-ranked stocks, of any
    # rows stored since; export them first if they are still wanted.
    op.drop_table("sim_not_ranked")
    op.drop_column("sim_runs", "momentum_universe_sha256")
    op.drop_column("sim_runs", "momentum_universe")
    for table in reversed(TABLES):
        op.drop_constraint(f"ck_{table}_trace", table, type_="check")
        op.drop_column(table, "rule_ref")
