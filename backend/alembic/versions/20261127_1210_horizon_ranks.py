# ruff: noqa: E501 (long plain-English docstring)
"""horizon_ranks: where a stock ranked on a day, per horizon and rank revision (#260).

New table only; no existing table is touched and nothing is backfilled. Points at `horizon_records` by id (score,
model and version are not copied). Add-only: a database trigger refuses UPDATE, DELETE and TRUNCATE. Not a
hypertable. Approved in docs/approvals/2026-11-26-260-migration-approval.md. Downgrade drops the triggers, the table
and the function.

Revision ID: scanrank02
Revises: scanrank01
Create Date: 2026-11-27 12:10:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "scanrank02"
down_revision: str | None = "scanrank01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE_SQL = [
    """
    CREATE TABLE horizon_ranks (
        id                BIGSERIAL PRIMARY KEY,
        horizon_record_id BIGINT      NOT NULL REFERENCES horizon_records (id) ON DELETE RESTRICT,
        security_id       BIGINT      NOT NULL REFERENCES securities (id)      ON DELETE RESTRICT,
        session_date      DATE        NOT NULL,
        horizon_days      SMALLINT    NOT NULL,
        model_id          INTEGER,
        rank_no           INTEGER     NOT NULL,
        cohort_size       INTEGER     NOT NULL,
        rank_revision     INTEGER     NOT NULL DEFAULT 1,
        scan_run_id       BIGINT      REFERENCES scan_runs (id) ON DELETE RESTRICT,
        source            VARCHAR(12) NOT NULL DEFAULT 'live',
        ranked_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT ck_horizon_ranks_horizon  CHECK (horizon_days IN (5, 10, 15)),
        CONSTRAINT ck_horizon_ranks_rank     CHECK (rank_no >= 1 AND rank_no <= cohort_size),
        CONSTRAINT ck_horizon_ranks_revision CHECK (rank_revision >= 1),
        CONSTRAINT ck_horizon_ranks_source   CHECK (source IN ('live', 'backfill'))
    )
    """,
    "CREATE INDEX ix_horizon_ranks_security_id ON horizon_ranks (security_id)",
    "CREATE INDEX ix_horizon_ranks_session     ON horizon_ranks (session_date, horizon_days, rank_no)",
    "CREATE UNIQUE INDEX uq_horizon_ranks_key  ON horizon_ranks (horizon_record_id, rank_revision)",
    """
    CREATE OR REPLACE FUNCTION horizon_ranks_append_only() RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION '% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP;
    END;
    $$ LANGUAGE plpgsql
    """,
    "CREATE TRIGGER trg_horizon_ranks_no_update   BEFORE UPDATE   ON horizon_ranks FOR EACH ROW       EXECUTE FUNCTION horizon_ranks_append_only()",
    "CREATE TRIGGER trg_horizon_ranks_no_delete   BEFORE DELETE   ON horizon_ranks FOR EACH ROW       EXECUTE FUNCTION horizon_ranks_append_only()",
    "CREATE TRIGGER trg_horizon_ranks_no_truncate BEFORE TRUNCATE ON horizon_ranks FOR EACH STATEMENT EXECUTE FUNCTION horizon_ranks_append_only()",
]

DOWNGRADE_SQL = [
    "DROP TRIGGER IF EXISTS trg_horizon_ranks_no_truncate ON horizon_ranks",
    "DROP TRIGGER IF EXISTS trg_horizon_ranks_no_delete ON horizon_ranks",
    "DROP TRIGGER IF EXISTS trg_horizon_ranks_no_update ON horizon_ranks",
    "DROP TABLE horizon_ranks",
    "DROP FUNCTION IF EXISTS horizon_ranks_append_only()",
]


def upgrade() -> None:
    for statement in UPGRADE_SQL:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_SQL:
        op.execute(statement)
