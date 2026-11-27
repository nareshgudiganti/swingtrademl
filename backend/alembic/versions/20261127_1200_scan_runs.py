# ruff: noqa: E501 (long plain-English docstring)
"""scan_runs: one row per nightly scoring pass (#260).

New table only; no existing table is touched and nothing is backfilled. Add-only: a database trigger refuses UPDATE,
DELETE and TRUNCATE (the same rule as `horizon_records`). Not a hypertable. Approved in
docs/approvals/2026-11-26-260-migration-approval.md. Downgrade drops the triggers, the table and the function.

Revision ID: scanrank01
Revises: signalkey01
Create Date: 2026-11-27 12:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "scanrank01"
down_revision: str | None = "signalkey01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE_SQL = [
    """
    CREATE TABLE scan_runs (
        id             BIGSERIAL PRIMARY KEY,
        scan_key       VARCHAR(64)  NOT NULL,
        session_date   DATE         NOT NULL,
        horizon_days   SMALLINT     NOT NULL,
        pass_no        SMALLINT     NOT NULL DEFAULT 1,
        is_final       BOOLEAN      NOT NULL DEFAULT false,
        universe_count INTEGER      NOT NULL,
        scored_count   INTEGER      NOT NULL,
        stale_count    INTEGER      NOT NULL DEFAULT 0,
        missing_count  INTEGER      NOT NULL DEFAULT 0,
        skipped_count  INTEGER      NOT NULL DEFAULT 0,
        skipped_symbols TEXT,
        model_versions  TEXT,
        started_at     TIMESTAMPTZ,
        finished_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
        CONSTRAINT ck_scan_runs_horizon CHECK (horizon_days IN (5, 10, 15)),
        CONSTRAINT ck_scan_runs_pass    CHECK (pass_no >= 1),
        CONSTRAINT ck_scan_runs_counts  CHECK (
            universe_count >= 0 AND scored_count >= 0 AND stale_count >= 0
            AND missing_count >= 0 AND skipped_count >= 0
            AND scored_count + stale_count + missing_count + skipped_count <= universe_count)
    )
    """,
    "CREATE INDEX ix_scan_runs_session ON scan_runs (session_date, horizon_days)",
    "CREATE UNIQUE INDEX uq_scan_runs_key ON scan_runs (scan_key, horizon_days, pass_no)",
    """
    CREATE OR REPLACE FUNCTION scan_runs_append_only() RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION '% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP;
    END;
    $$ LANGUAGE plpgsql
    """,
    "CREATE TRIGGER trg_scan_runs_no_update   BEFORE UPDATE   ON scan_runs FOR EACH ROW       EXECUTE FUNCTION scan_runs_append_only()",
    "CREATE TRIGGER trg_scan_runs_no_delete   BEFORE DELETE   ON scan_runs FOR EACH ROW       EXECUTE FUNCTION scan_runs_append_only()",
    "CREATE TRIGGER trg_scan_runs_no_truncate BEFORE TRUNCATE ON scan_runs FOR EACH STATEMENT EXECUTE FUNCTION scan_runs_append_only()",
]

DOWNGRADE_SQL = [
    "DROP TRIGGER IF EXISTS trg_scan_runs_no_truncate ON scan_runs",
    "DROP TRIGGER IF EXISTS trg_scan_runs_no_delete ON scan_runs",
    "DROP TRIGGER IF EXISTS trg_scan_runs_no_update ON scan_runs",
    "DROP TABLE scan_runs",
    "DROP FUNCTION IF EXISTS scan_runs_append_only()",
]


def upgrade() -> None:
    for statement in UPGRADE_SQL:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_SQL:
        op.execute(statement)
