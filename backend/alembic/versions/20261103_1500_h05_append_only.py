# ruff: noqa: E501 (long explanatory lines)
"""5-day lane (h05) tables: database-level append-only guards

No table or column is added or changed. Only triggers are created, and only on future writes: rows already
stored are never re-checked or touched.

What each guard allows (derived from every write the h05 code performs):

- h05_group_days, h05_events: written once. UPDATE, DELETE and TRUNCATE are refused.
- h05_runs: inserted once; the ONLY allowed update is status active -> closed (h05_service.close_run). Every other
  column is frozen. DELETE and TRUNCATE are refused.
- h05_signals: inserted once with the day's saved score, rank and top-five choice. Those columns are frozen.
  The two outcome blocks are written once each, while still "pending" (h05_service.evaluate): the label block
  (label_*) and the trade block (trade_*, exit_*, entry_*, net_return, stress columns). Once a block has left
  "pending" it is frozen. outcome_provenance and evaluated_at stay writable (evaluate refreshes them while the
  other block is still pending). DELETE and TRUNCATE are refused.

The downgrade drops only the triggers and functions this migration created; no data is touched.
The upgrade is safe to run twice.

Revision ID: h05ao7p2k9d1
Revises: lane5h4d0w1a
Create Date: 2026-11-03 15:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "h05ao7p2k9d1"
down_revision: str | None = "lane5h4d0w1a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Column partition of h05_signals. A test checks these three lists plus FREE cover every column of the model, so a
# future column forces a decision here.
SIGNAL_FROZEN = (
    "id",
    "run_id",
    "signal_day",
    "symbol",
    '"group"',
    "instrument_id",
    "status",
    "not_scored_reason",
    "model_id",
    "model_version",
    "trained_on_symbol",
    "score",
    "score_production_path",
    "group_rank",
    "selected",
    "repeat_blocked",
    "signal_close",
    "avg_volume_20",
    "flags",
    "recorded_at",
)
SIGNAL_LABEL = ("label_status", "label_day5", "label_close5", "label_hit", "label_note")
SIGNAL_TRADE = (
    "trade_status",
    "trade_note",
    "entry_day",
    "entry_open",
    "entry_fill",
    "exit_day",
    "exit_price",
    "exit_fill",
    "exit_reason",
    "sessions_held",
    "gap_fill",
    "ambiguous",
    "costs_inr",
    "net_return",
    "trade_flags",
    "trade_status_stress",
    "net_return_stress",
)
SIGNAL_FREE = ("outcome_provenance", "evaluated_at")
RUN_FROZEN = (
    "id",
    "run_no",
    "protocol_code",
    "protocol_hash",
    "start_day",
    "end_day",
    "models",
    "universe",
    "universe_hash",
    "parity",
    "created_at",
)

TRIGGERS = (
    ("h05_group_days", "h05_append_only"),
    ("h05_events", "h05_append_only"),
    ("h05_runs", "h05_runs_guard"),
    ("h05_signals", "h05_signals_guard"),
)
FUNCTIONS = ("h05_append_only", "h05_runs_guard", "h05_signals_guard")


def _changed(cols: Sequence[str]) -> str:
    return " OR ".join(f"OLD.{c} IS DISTINCT FROM NEW.{c}" for c in cols)


def function_sql() -> list[str]:
    append_only = """
CREATE OR REPLACE FUNCTION h05_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP;
END;
$$ LANGUAGE plpgsql
"""
    runs = f"""
CREATE OR REPLACE FUNCTION h05_runs_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP <> 'UPDATE' THEN
        RAISE EXCEPTION '% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP;
    END IF;
    IF {_changed(RUN_FROZEN)} THEN
        RAISE EXCEPTION 'h05_runs is append-only: a recorded run column cannot be changed';
    END IF;
    IF NEW.status IS DISTINCT FROM OLD.status AND NOT (OLD.status = 'active' AND NEW.status = 'closed') THEN
        RAISE EXCEPTION 'h05_runs is append-only: status may only go from active to closed';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""
    signals = f"""
CREATE OR REPLACE FUNCTION h05_signals_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP <> 'UPDATE' THEN
        RAISE EXCEPTION '% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP;
    END IF;
    IF {_changed(SIGNAL_FROZEN)} THEN
        RAISE EXCEPTION 'h05_signals is append-only: a recorded score, rank or selection cannot be changed';
    END IF;
    IF OLD.label_status <> 'pending' AND ({_changed(SIGNAL_LABEL)}) THEN
        RAISE EXCEPTION 'h05_signals is append-only: a final label outcome cannot be changed';
    END IF;
    IF OLD.trade_status <> 'pending' AND ({_changed(SIGNAL_TRADE)}) THEN
        RAISE EXCEPTION 'h05_signals is append-only: a final trade outcome cannot be changed';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""
    return [append_only, runs, signals]


def install_triggers(bind) -> None:
    for sql in function_sql():
        bind.execute(sa.text(sql))
    for table, fn in TRIGGERS:
        for op_name, level in (("UPDATE", "ROW"), ("DELETE", "ROW"), ("TRUNCATE", "STATEMENT")):
            name = f"trg_{table}_no_{op_name.lower()}"
            bind.execute(sa.text(f"DROP TRIGGER IF EXISTS {name} ON {table}"))
            bind.execute(
                sa.text(
                    f"CREATE TRIGGER {name} BEFORE {op_name} ON {table} "
                    f"FOR EACH {level} EXECUTE FUNCTION {fn}()"
                )
            )


def drop_triggers(bind) -> None:
    for table, _fn in TRIGGERS:
        for op_name in ("update", "delete", "truncate"):
            bind.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{table}_no_{op_name} ON {table}"))
    for fn in FUNCTIONS:
        bind.execute(sa.text(f"DROP FUNCTION IF EXISTS {fn}()"))


def upgrade() -> None:
    install_triggers(op.get_bind())


def downgrade() -> None:
    drop_triggers(op.get_bind())
