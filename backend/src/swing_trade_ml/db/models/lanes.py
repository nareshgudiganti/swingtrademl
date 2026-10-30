"""Horizon lanes: storage for the h05 evaluation. Separate tables, no foreign key to any money table
(orders, positions, signals, brain), so nothing here can reach the bot's cash, slots or the sealed trial.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from swing_trade_ml.db.base import Base, utcnow


class H05Run(Base):
    """One of the three evaluation runs. Model identities and the universe are frozen at run 1."""

    __tablename__ = "h05_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_no: Mapped[int] = mapped_column(SmallInteger, unique=True)
    protocol_code: Mapped[str] = mapped_column(String(64))
    protocol_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(12), default="active")  # active | closed
    start_day: Mapped[date] = mapped_column(Date)
    end_day: Mapped[date] = mapped_column(Date)
    models: Mapped[dict[str, Any]] = mapped_column(JSONB)
    universe: Mapped[dict[str, Any]] = mapped_column(JSONB)
    universe_hash: Mapped[str] = mapped_column(String(64))
    parity: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class H05GroupDay(Base):
    """Per run, signal day and group: how many stocks were eligible and whether the top 5 was full."""

    __tablename__ = "h05_group_days"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("h05_runs.id", ondelete="RESTRICT"), index=True)
    signal_day: Mapped[date] = mapped_column(Date)
    group: Mapped[str] = mapped_column(String(8))
    universe_n: Mapped[int] = mapped_column(Integer)
    scored_n: Mapped[int] = mapped_column(Integer)
    not_scored_n: Mapped[int] = mapped_column(Integer)
    selected_n: Mapped[int] = mapped_column(Integer)
    shortfall: Mapped[int] = mapped_column(Integer)
    # Where this day's market data came from: the NIFTY and signal-day bar counts and a fingerprint of the
    # group's signal-day bars. A fingerprint of ONE day, not of the whole changing dataset.
    provenance: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # When this selection was written. It is always before the simulated entry (the open of session 1).
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("run_id", "signal_day", "group", name="uq_h05_group_days_key"),)


class H05Signal(Base):
    """One row per stock per signal day: every eligible stock is scored and kept, selected or not.

    The endpoint label outcome (`label_*`) and the shadow trade outcome (`trade_*`) are separate columns
    on purpose: they answer different questions and are never merged."""

    __tablename__ = "h05_signals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("h05_runs.id", ondelete="RESTRICT"), index=True)
    signal_day: Mapped[date] = mapped_column(Date)
    symbol: Mapped[str] = mapped_column(String(64))
    group: Mapped[str] = mapped_column(String(8))
    instrument_id: Mapped[int | None] = mapped_column(Integer)

    # scoring
    status: Mapped[str] = mapped_column(String(10))  # scored | not_scored
    not_scored_reason: Mapped[str | None] = mapped_column(String(80))
    model_id: Mapped[int | None] = mapped_column(Integer)
    model_version: Mapped[str | None] = mapped_column(String(32))
    trained_on_symbol: Mapped[bool | None] = mapped_column(Boolean)
    score: Mapped[float | None] = mapped_column(Float)  # PRIMARY: the inputs the saved model was trained on
    score_production_path: Mapped[float | None] = mapped_column(Float)  # diagnostic only, never selects
    group_rank: Mapped[int | None] = mapped_column(Integer)
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    repeat_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    signal_close: Mapped[float | None] = mapped_column(Float)
    avg_volume_20: Mapped[float | None] = mapped_column(Float)
    flags: Mapped[list[str] | None] = mapped_column(JSONB)

    # endpoint label outcome: did the close five sessions later reach +2%?
    label_status: Mapped[str] = mapped_column(String(14), default="pending")
    label_day5: Mapped[date | None] = mapped_column(Date)
    label_close5: Mapped[float | None] = mapped_column(Float)
    label_hit: Mapped[int | None] = mapped_column(SmallInteger)
    label_note: Mapped[str | None] = mapped_column(Text)

    # fixed-rule shadow trade outcome
    trade_status: Mapped[str] = mapped_column(String(10), default="pending")
    trade_note: Mapped[str | None] = mapped_column(Text)
    entry_day: Mapped[date | None] = mapped_column(Date)
    entry_open: Mapped[float | None] = mapped_column(Float)
    entry_fill: Mapped[float | None] = mapped_column(Float)
    exit_day: Mapped[date | None] = mapped_column(Date)
    exit_price: Mapped[float | None] = mapped_column(Float)
    exit_fill: Mapped[float | None] = mapped_column(Float)
    exit_reason: Mapped[str | None] = mapped_column(String(10))
    sessions_held: Mapped[int | None] = mapped_column(SmallInteger)
    gap_fill: Mapped[bool | None] = mapped_column(Boolean)
    ambiguous: Mapped[bool | None] = mapped_column(Boolean)
    costs_inr: Mapped[float | None] = mapped_column(Float)
    net_return: Mapped[float | None] = mapped_column(Float)
    trade_flags: Mapped[list[str] | None] = mapped_column(JSONB)
    # higher-cost sensitivity of the same trade (never decides a verdict)
    trade_status_stress: Mapped[str | None] = mapped_column(String(10))
    net_return_stress: Mapped[float | None] = mapped_column(Float)
    outcome_provenance: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # written before entry

    __table_args__ = (UniqueConstraint("run_id", "signal_day", "symbol", name="uq_h05_signals_key"),)


class H05Event(Base):
    """A stop that must outlive a rolled-back transaction: a frozen-model check that failed for a signal day.
    The report lists these and the days they left unrecorded."""

    __tablename__ = "h05_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("h05_runs.id", ondelete="RESTRICT"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    signal_day: Mapped[date | None] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str] = mapped_column(Text)
