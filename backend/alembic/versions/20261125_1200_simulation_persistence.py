# ruff: noqa: E501 (long lines)
"""Research simulation persistence (#321, #379): synthetic portfolios, daily ledger rows, fills, exits, blocked
decisions and the rules that were not applied.

Additive only: eight new tables. No existing table, column or row is touched. Nothing reads these tables except the
simulation store, and no job writes to them until the owner approves one. Every table is synthetic: none has a user or
account column, and `synthetic` is checked true.

Revision ID: simulation01
Revises: horizon01
Create Date: 2026-11-25 12:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "simulation01"
down_revision: str | None = "horizon01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY_CHECK = "policy IN ('momentum','model_only','brain_filtered')"


def _pk() -> sa.Column:
    return sa.Column("id", sa.BigInteger, primary_key=True)


def _portfolio_fk() -> sa.Column:
    return sa.Column(
        "portfolio_id", sa.BigInteger, sa.ForeignKey("sim_portfolios.id", ondelete="RESTRICT"), nullable=False
    )


def _security_fk() -> sa.Column:
    return sa.Column(
        "security_id", sa.BigInteger, sa.ForeignKey("securities.id", ondelete="RESTRICT"), nullable=False
    )


def _record_fk() -> sa.Column:
    return sa.Column(
        "horizon_record_id",
        sa.BigInteger,
        sa.ForeignKey("horizon_records.id", ondelete="RESTRICT"),
        nullable=True,
    )


def upgrade() -> None:
    op.create_table(
        "sim_runs",
        _pk(),
        sa.Column("run_key", sa.String(64), nullable=False, unique=True),
        sa.Column("schema_version", sa.SmallInteger, server_default="1", nullable=False),
        sa.Column("rule_version", sa.String(32), nullable=False),
        sa.Column("research_config_version", sa.String(32), nullable=False),
        sa.Column("research_only", sa.Boolean, nullable=False),
        sa.Column("horizon_days", sa.SmallInteger, nullable=False),
        sa.Column("synthetic", sa.Boolean, server_default=sa.text("true"), nullable=False),
        sa.Column("first_session", sa.Date),
        sa.Column("last_session", sa.Date),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("horizon_days IN (5, 10, 15)", name="ck_sim_runs_horizon"),
        sa.CheckConstraint("synthetic", name="ck_sim_runs_synthetic"),
    )
    op.create_table(
        "sim_portfolios",
        _pk(),
        sa.Column("run_id", sa.BigInteger, sa.ForeignKey("sim_runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("persona_key", sa.String(16), nullable=False),
        sa.Column("setup_key", sa.String(16), nullable=False),
        sa.Column("policy", sa.String(16), nullable=False),
        sa.Column("balance_inr", sa.BigInteger, nullable=False),
        sa.Column("start_offset", sa.SmallInteger, nullable=False),
        sa.Column("counts_in_comparison", sa.Boolean, nullable=False),
        sa.Column("rule_version", sa.String(32), nullable=False),
        sa.Column("research_only", sa.Boolean, nullable=False),
        sa.Column("synthetic", sa.Boolean, server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("run_id", "persona_key", name="uq_sim_portfolios_persona"),
        sa.CheckConstraint(POLICY_CHECK, name="ck_sim_portfolios_policy"),
        sa.CheckConstraint("balance_inr > 0", name="ck_sim_portfolios_balance"),
        sa.CheckConstraint("start_offset >= 0", name="ck_sim_portfolios_offset"),
        sa.CheckConstraint("synthetic", name="ck_sim_portfolios_synthetic"),
    )
    op.create_index("ix_sim_portfolios_run_id", "sim_portfolios", ["run_id"])
    op.create_index(
        "uq_sim_portfolios_one_validation",
        "sim_portfolios",
        ["run_id"],
        unique=True,
        postgresql_where=sa.text("NOT counts_in_comparison"),
    )
    op.create_table(
        "sim_not_applied",
        _pk(),
        _portfolio_fk(),
        sa.Column("rule_text", sa.String(255), nullable=False),
        sa.UniqueConstraint("portfolio_id", "rule_text", name="uq_sim_not_applied"),
    )
    op.create_index("ix_sim_not_applied_portfolio_id", "sim_not_applied", ["portfolio_id"])
    op.create_table(
        "sim_days",
        _pk(),
        _portfolio_fk(),
        sa.Column("session_date", sa.Date, nullable=False),
        sa.Column("cash", sa.Float, nullable=False),
        sa.Column("equity", sa.Float, nullable=False),
        sa.Column("halted", sa.Boolean, nullable=False),
        sa.Column("market_mode", sa.String(24), server_default="", nullable=False),
        sa.Column("rule_version", sa.String(32), nullable=False),
        sa.Column("research_only", sa.Boolean, nullable=False),
        sa.UniqueConstraint("portfolio_id", "session_date", name="uq_sim_days_key"),
        sa.CheckConstraint("cash >= 0", name="ck_sim_days_cash_not_negative"),
    )
    op.create_table(
        "sim_fills",
        _pk(),
        _portfolio_fk(),
        sa.Column("session_date", sa.Date, nullable=False),
        _security_fk(),
        sa.Column("symbol", sa.String(64), nullable=False),
        _record_fk(),
        sa.Column("policy", sa.String(16), nullable=False),
        sa.Column("rule_version", sa.String(32), nullable=False),
        sa.Column("qty", sa.Integer, nullable=False),
        sa.Column("price", sa.Float, nullable=False),
        sa.Column("charges", sa.Float, nullable=False),
        sa.Column("cost", sa.Float, nullable=False),
        sa.UniqueConstraint("portfolio_id", "session_date", "security_id", name="uq_sim_fills_key"),
        sa.CheckConstraint("qty > 0", name="ck_sim_fills_qty"),
        sa.CheckConstraint(POLICY_CHECK, name="ck_sim_fills_policy"),
    )
    op.create_index("ix_sim_fills_security_id", "sim_fills", ["security_id"])
    op.create_index("ix_sim_fills_horizon_record_id", "sim_fills", ["horizon_record_id"])
    op.create_table(
        "sim_exits",
        _pk(),
        _portfolio_fk(),
        sa.Column("session_date", sa.Date, nullable=False),
        _security_fk(),
        sa.Column("symbol", sa.String(64), nullable=False),
        _record_fk(),
        sa.Column("policy", sa.String(16), nullable=False),
        sa.Column("rule_version", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(12), nullable=False),
        sa.Column("qty", sa.Integer, nullable=False),
        sa.Column("price", sa.Float, nullable=False),
        sa.Column("proceeds", sa.Float, nullable=False),
        sa.Column("stale", sa.Boolean, server_default=sa.text("false"), nullable=False),
        sa.UniqueConstraint("portfolio_id", "session_date", "security_id", "reason", name="uq_sim_exits_key"),
        sa.CheckConstraint("qty > 0", name="ck_sim_exits_qty"),
        sa.CheckConstraint("reason IN ('stop','half_out','target','horizon')", name="ck_sim_exits_reason"),
    )
    op.create_index("ix_sim_exits_security_id", "sim_exits", ["security_id"])
    op.create_table(
        "sim_blocks",
        _pk(),
        _portfolio_fk(),
        sa.Column("session_date", sa.Date, nullable=False),
        sa.Column("seq", sa.SmallInteger, nullable=False),
        _security_fk(),
        sa.Column("symbol", sa.String(64), nullable=False),
        _record_fk(),
        sa.Column("policy", sa.String(16), nullable=False),
        sa.Column("rule_version", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(255), nullable=False),
        sa.UniqueConstraint("portfolio_id", "session_date", "seq", name="uq_sim_blocks_key"),
    )
    op.create_index("ix_sim_blocks_security_id", "sim_blocks", ["security_id"])
    op.create_table(
        "sim_marks",
        _pk(),
        _portfolio_fk(),
        sa.Column("session_date", sa.Date, nullable=False),
        _security_fk(),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("qty", sa.Integer, nullable=False),
        sa.Column("mark", sa.Float, nullable=False),
        sa.Column("value", sa.Float, nullable=False),
        sa.Column("half_done", sa.Boolean, nullable=False),
        sa.Column("stale", sa.Boolean, nullable=False),
        sa.UniqueConstraint("portfolio_id", "session_date", "security_id", name="uq_sim_marks_key"),
        sa.CheckConstraint("qty > 0", name="ck_sim_marks_qty"),
    )
    op.create_index("ix_sim_marks_security_id", "sim_marks", ["security_id"])


def downgrade() -> None:
    # All eight tables are new in this migration, so dropping them loses nothing that existed before. They hold only
    # synthetic simulation rows; after a run has been stored, export it first if it is still wanted.
    for table in (
        "sim_marks",
        "sim_blocks",
        "sim_exits",
        "sim_fills",
        "sim_days",
        "sim_not_applied",
        "sim_portfolios",
        "sim_runs",
    ):
        op.drop_table(table)
