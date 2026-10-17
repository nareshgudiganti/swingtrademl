"""Horizon experiments (design rev 3, docs/superpowers/specs/2026-10-17-horizon-experiments-design.md).

A research ledger beside the 15-day brain trial: owner-selected stocks scored over 5 and 30 trading days from
daily candles. Simulated only. Deliberately no foreign key to any money table (orders, positions, trades,
signals, brain): nothing here can reach the bot's cash, slots or the trial.

`experiment_selections` is append-only. A trigger (installed on create, and by the migration) refuses UPDATE
and DELETE; a correction is a new row that names the row it replaces.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    DDL,
    BigInteger,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from swing_trade_ml.db.base import Base, utcnow


class ExperimentProtocol(Base):
    """One frozen protocol version. Never edited: a change of rules is a new code (horizon-v2)."""

    __tablename__ = "experiment_protocols"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    frozen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)


class ExperimentCohort(Base):
    """Who chooses the stocks: 'owner' now; 'model' is allowed by the schema but has no flow yet."""

    __tablename__ = "experiment_cohorts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    protocol_id: Mapped[int] = mapped_column(
        ForeignKey("experiment_protocols.id", ondelete="RESTRICT"), index=True
    )
    source: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(12), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("protocol_id", "source", "name", name="uq_experiment_cohorts_key"),)


class ExperimentSelection(Base):
    """One recorded pick, append-only."""

    __tablename__ = "experiment_selections"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    cohort_id: Mapped[int] = mapped_column(
        ForeignKey("experiment_cohorts.id", ondelete="RESTRICT"), index=True
    )
    instrument_id: Mapped[int | None] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT"), index=True
    )
    symbol_at_entry: Mapped[str] = mapped_column(String(64))
    intended_horizon: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    submitted_by: Mapped[str] = mapped_column(String(64))
    entry_session: Mapped[date | None] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(12))  # accepted | rejected
    reject_reason: Mapped[str | None] = mapped_column(Text)
    supersedes_id: Mapped[int | None] = mapped_column(
        ForeignKey("experiment_selections.id", ondelete="RESTRICT"), index=True
    )


class ExperimentOutcome(Base):
    """One scored (selection, horizon, protocol). Written only by the scorer, as an upsert."""

    __tablename__ = "experiment_outcomes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    selection_id: Mapped[int] = mapped_column(
        ForeignKey("experiment_selections.id", ondelete="RESTRICT"), index=True
    )
    horizon: Mapped[int] = mapped_column(Integer)
    protocol_id: Mapped[int] = mapped_column(ForeignKey("experiment_protocols.id", ondelete="RESTRICT"))
    state: Mapped[str] = mapped_column(String(12))  # pending | open | closed | data_issue | void
    entry_price: Mapped[float | None] = mapped_column(Float)
    exit_session: Mapped[date | None] = mapped_column(Date)
    exit_price: Mapped[float | None] = mapped_column(Float)
    mark_session: Mapped[date | None] = mapped_column(Date)
    gross_return: Mapped[float | None] = mapped_column(Float)
    costs_inr: Mapped[float | None] = mapped_column(Float)
    slippage_inr: Mapped[float | None] = mapped_column(Float)
    net_return: Mapped[float | None] = mapped_column(Float)
    nifty_return: Mapped[float | None] = mapped_column(Float)
    universe_return: Mapped[float | None] = mapped_column(Float)
    universe_count: Mapped[int | None] = mapped_column(Integer)
    buy_hold_return: Mapped[float | None] = mapped_column(Float)
    excess_vs_nifty: Mapped[float | None] = mapped_column(Float)
    excess_vs_universe: Mapped[float | None] = mapped_column(Float)
    data_flags: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    scorer_version: Mapped[str] = mapped_column(String(32))

    __table_args__ = (
        UniqueConstraint("selection_id", "horizon", "protocol_id", name="uq_experiment_outcomes_key"),
    )


class ExperimentJobRun(Base):
    """Audit of every scorer run, including runs that stepped aside or failed."""

    __tablename__ = "experiment_job_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))  # running | done | skipped_locked | failed
    rows_scored: Mapped[int] = mapped_column(Integer, default=0)
    rows_flagged: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)


# The append-only guard. Installed with the table so the create_all path (tests, fresh databases) has it too;
# the migration installs the same function and trigger.
APPEND_ONLY_FUNCTION = """
CREATE OR REPLACE FUNCTION experiment_selections_append_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'experiment_selections is append-only: %% refused', TG_OP;
END;
$$ LANGUAGE plpgsql
"""
APPEND_ONLY_TRIGGER = """
CREATE TRIGGER experiment_selections_append_only
BEFORE UPDATE OR DELETE ON experiment_selections
FOR EACH ROW EXECUTE FUNCTION experiment_selections_append_only()
"""

event.listen(
    ExperimentSelection.__table__, "after_create", DDL(APPEND_ONLY_FUNCTION).execute_if(dialect="postgresql")
)
event.listen(
    ExperimentSelection.__table__, "after_create", DDL(APPEND_ONLY_TRIGGER).execute_if(dialect="postgresql")
)
