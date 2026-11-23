# ruff: noqa: E501 (long lines)
"""Horizon recommendation records and the model and run of a signal (#387, on the identity tables of #389)

Additive only: one new table with an append-only trigger, and three nullable columns on `signals`. No existing row is
rewritten and no existing column changes; old signals keep NULL there (unknown, never guessed).

Revision ID: horizon01
Revises: identity01
Create Date: 2026-11-24 12:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "horizon01"
down_revision: str | None = "identity01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "horizon_records"
FUNCTION = "horizon_records_append_only"
FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION {FUNCTION}() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP;
END;
$$ LANGUAGE plpgsql;
"""
SIGNAL_COLUMNS = (("model_id", sa.Integer()), ("model_version", sa.String(64)), ("run_id", sa.String(64)))


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "security_id", sa.BigInteger, sa.ForeignKey("securities.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("session_date", sa.Date, nullable=False),
        sa.Column("horizon_days", sa.SmallInteger, nullable=False),
        sa.Column("model_id", sa.Integer),
        sa.Column("model_name", sa.String(64), server_default="", nullable=False),
        sa.Column("model_version", sa.String(64), server_default="", nullable=False),
        sa.Column("revision", sa.Integer, server_default="1", nullable=False),
        sa.Column("supersedes_id", sa.BigInteger, sa.ForeignKey("horizon_records.id", ondelete="RESTRICT")),
        sa.Column("decision", sa.String(12), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("score", sa.Float),
        sa.Column("input_close", sa.Float),
        sa.Column("evaluation_due_session", sa.Date),
        sa.Column("policy_code", sa.String(32)),
        sa.Column("target_pct", sa.Float),
        sa.Column("stop_pct", sa.Float),
        sa.Column("half_out_pct", sa.Float),
        sa.Column("research_config_version", sa.String(32), nullable=False),
        sa.Column("research_config_sha256", sa.String(64), nullable=False),
        sa.Column("research_only", sa.Boolean, nullable=False),
        sa.Column("scan_key", sa.String(64)),
        sa.Column("run_ref", sa.String(64)),
        sa.Column("input_cutoff", sa.DateTime(timezone=True)),
        sa.Column("scored_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("horizon_days IN (5, 10, 15)", name="ck_horizon_records_horizon"),
        sa.CheckConstraint("revision >= 1", name="ck_horizon_records_revision"),
        sa.CheckConstraint("decision IN ('TRADE','WATCH','WAIT','NO_DECISION')", name="ck_horizon_records_decision"),
    )
    op.create_index("ix_horizon_records_security_id", TABLE, ["security_id"])
    op.create_index("ix_horizon_records_security_session", TABLE, ["security_id", "session_date"])
    op.create_index(
        "uq_horizon_records_key",
        TABLE,
        ["security_id", "session_date", "horizon_days", sa.text("coalesce(model_id, -1)"), "model_version", "revision"],
        unique=True,
    )
    install_triggers(op.get_bind())
    for name, kind in SIGNAL_COLUMNS:
        op.add_column("signals", sa.Column(name, kind, nullable=True))


def install_triggers(bind) -> None:
    """A record can never be edited or emptied: UPDATE, DELETE and TRUNCATE are refused by the database."""
    bind.execute(sa.text(FUNCTION_SQL))
    for op_name, level in (("UPDATE", "ROW"), ("DELETE", "ROW"), ("TRUNCATE", "STATEMENT")):
        name = f"trg_{TABLE}_no_{op_name.lower()}"
        bind.execute(sa.text(f"DROP TRIGGER IF EXISTS {name} ON {TABLE}"))
        bind.execute(
            sa.text(
                f"CREATE TRIGGER {name} BEFORE {op_name} ON {TABLE} "
                f"FOR EACH {level} EXECUTE FUNCTION {FUNCTION}()"
            )
        )


def downgrade() -> None:
    # The table and the three columns are new in this migration, so dropping them loses nothing that existed before.
    # (After the table has been used in production, back it up first: it is the recommendation evidence.)
    for name, _ in reversed(SIGNAL_COLUMNS):
        op.drop_column("signals", name)
    bind = op.get_bind()
    for op_name in ("update", "delete", "truncate"):
        bind.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{TABLE}_no_{op_name} ON {TABLE}"))
    op.drop_table(TABLE)
    bind.execute(sa.text(f"DROP FUNCTION IF EXISTS {FUNCTION}()"))
