# ruff: noqa: E501 (long lines)
"""Stock identity and the score ledger (#389 phase 1: securities, symbol history, aliases, append-only ledger)

Additive only: four new tables and one trigger function. No existing table is touched, no row is rewritten.
`score_ledger` is protected in the database by triggers that refuse UPDATE, DELETE and TRUNCATE.

Revision ID: identity01
Revises: wlsales01
Create Date: 2026-11-23 12:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "identity01"
down_revision: str | None = "wlsales01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION score_ledger_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP;
END;
$$ LANGUAGE plpgsql;
"""
LEDGER = "score_ledger"


def upgrade() -> None:
    op.create_table(
        "securities",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("isin", sa.String(12), unique=True),
        sa.Column("name", sa.Text),
        sa.Column("status", sa.String(12), server_default="active", nullable=False),
        sa.Column("successor_of_id", sa.BigInteger, sa.ForeignKey("securities.id", ondelete="RESTRICT")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "security_symbols",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "security_id", sa.BigInteger, sa.ForeignKey("securities.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("exchange", sa.String(16), nullable=False),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("valid_from", sa.Date, nullable=False),
        sa.Column("valid_to", sa.Date),
        sa.UniqueConstraint("exchange", "symbol", "valid_from", name="uq_security_symbols_exchange_symbol_from"),
        sa.CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="ck_security_symbols_valid_range"),
    )
    op.create_index("ix_security_symbols_security_id", "security_symbols", ["security_id"])
    op.create_index("ix_security_symbols_lookup", "security_symbols", ["exchange", "symbol"])
    op.create_table(
        "security_aliases",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "security_id", sa.BigInteger, sa.ForeignKey("securities.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("external_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("provider", "external_id", name="uq_security_aliases_provider_external"),
    )
    op.create_index("ix_security_aliases_security_id", "security_aliases", ["security_id"])
    op.create_table(
        LEDGER,
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "security_id", sa.BigInteger, sa.ForeignKey("securities.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("session_date", sa.Date, nullable=False),
        sa.Column("horizon_days", sa.SmallInteger),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("model_id", sa.Integer),
        sa.Column("model_name", sa.String(64), server_default="", nullable=False),
        sa.Column("model_version", sa.String(64), server_default="", nullable=False),
        sa.Column("score", sa.Float),
        sa.Column("status", sa.String(12), server_default="scored", nullable=False),
        sa.Column("scan_key", sa.String(64)),
        sa.Column("revision", sa.Integer, server_default="1", nullable=False),
        sa.Column("supersedes_id", sa.BigInteger, sa.ForeignKey("score_ledger.id", ondelete="RESTRICT")),
        sa.Column("input_cutoff", sa.DateTime(timezone=True)),
        sa.Column("scored_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("run_ref", sa.String(64)),
        sa.Column("note", sa.Text),
        sa.CheckConstraint("status IN ('scored','missing','stale','late','no_score')", name="ck_score_ledger_status"),
        sa.CheckConstraint("revision >= 1", name="ck_score_ledger_revision"),
    )
    op.create_index("ix_score_ledger_security_id", LEDGER, ["security_id"])
    op.create_index("ix_score_ledger_security_session", LEDGER, ["security_id", "session_date"])
    op.create_index(
        "uq_score_ledger_key",
        LEDGER,
        [
            "security_id",
            "session_date",
            sa.text("coalesce(horizon_days, -1)"),
            "source",
            "model_name",
            "model_version",
            "revision",
        ],
        unique=True,
    )
    install_triggers(op.get_bind())


def install_triggers(bind) -> None:
    """The ledger can never be edited or emptied: UPDATE, DELETE and TRUNCATE are refused by the database."""
    bind.execute(sa.text(FUNCTION_SQL))
    for op_name, level in (("UPDATE", "ROW"), ("DELETE", "ROW"), ("TRUNCATE", "STATEMENT")):
        name = f"trg_{LEDGER}_no_{op_name.lower()}"
        bind.execute(sa.text(f"DROP TRIGGER IF EXISTS {name} ON {LEDGER}"))
        bind.execute(
            sa.text(
                f"CREATE TRIGGER {name} BEFORE {op_name} ON {LEDGER} "
                f"FOR EACH {level} EXECUTE FUNCTION score_ledger_append_only()"
            )
        )


def downgrade() -> None:
    # The four tables are new in this migration, so dropping them loses nothing that existed before it.
    # (After the ledger has been used in production, back it up first: it is the score evidence.)
    bind = op.get_bind()
    for op_name in ("update", "delete", "truncate"):
        bind.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{LEDGER}_no_{op_name} ON {LEDGER}"))
    op.drop_table(LEDGER)
    op.drop_table("security_aliases")
    op.drop_table("security_symbols")
    op.drop_table("securities")
    bind.execute(sa.text("DROP FUNCTION IF EXISTS score_ledger_append_only()"))
