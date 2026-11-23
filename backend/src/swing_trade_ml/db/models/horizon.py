# ruff: noqa: E501 (long explanatory lines)
"""Horizon recommendation records (#387, keyed by the permanent stock identity of #389).

One immutable row per stock, market session, horizon, model and version; a re-run with a different result appends
the next revision that points at the one it replaces. A database trigger (see the migration) refuses UPDATE, DELETE
and TRUNCATE, the same rule as `score_ledger`. `research_only` is stamped from the versioned research config when the
row is written and never changes: a customer screen or a Brain decision reads only rows where it is false.

Nothing here is read by trading, sizing, exits, orders or the brain. All of it is additive.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from swing_trade_ml.db.base import Base

HORIZON_DECISIONS = ("TRADE", "WATCH", "WAIT", "NO_DECISION")


class HorizonRecordRow(Base):
    """One workflow result for one stock, session and horizon (a recommendation, or "No decision for this horizon")."""

    __tablename__ = "horizon_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    security_id: Mapped[int] = mapped_column(ForeignKey("securities.id", ondelete="RESTRICT"), index=True)
    session_date: Mapped[date] = mapped_column(Date)  # the market session whose data produced the score
    horizon_days: Mapped[int] = mapped_column(SmallInteger)  # 5, 10 or 15 exchange sessions
    model_id: Mapped[int | None] = mapped_column(Integer)  # plain id: a record must outlive the model row; None = no model
    model_name: Mapped[str] = mapped_column(String(64), default="", server_default="")
    model_version: Mapped[str] = mapped_column(String(64), default="", server_default="")
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    supersedes_id: Mapped[int | None] = mapped_column(ForeignKey("horizon_records.id", ondelete="RESTRICT"))

    decision: Mapped[str] = mapped_column(String(12))
    reason: Mapped[str] = mapped_column(Text)
    score: Mapped[float | None] = mapped_column(Float)
    input_close: Mapped[float | None] = mapped_column(Float)
    evaluation_due_session: Mapped[date | None] = mapped_column(Date)

    policy_code: Mapped[str | None] = mapped_column(String(32))
    target_pct: Mapped[float | None] = mapped_column(Float)
    stop_pct: Mapped[float | None] = mapped_column(Float)
    half_out_pct: Mapped[float | None] = mapped_column(Float)

    research_config_version: Mapped[str] = mapped_column(String(32))
    research_config_sha256: Mapped[str] = mapped_column(String(64))
    research_only: Mapped[bool] = mapped_column(Boolean)

    scan_key: Mapped[str | None] = mapped_column(String(64))
    run_ref: Mapped[str | None] = mapped_column(String(64))
    input_cutoff: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index(
            "uq_horizon_records_key",
            "security_id",
            "session_date",
            "horizon_days",
            text("coalesce(model_id, -1)"),
            "model_version",
            "revision",
            unique=True,
        ),
        Index("ix_horizon_records_security_session", "security_id", "session_date"),
        CheckConstraint("horizon_days IN (5, 10, 15)", name="horizon"),
        CheckConstraint("revision >= 1", name="revision"),
        CheckConstraint("decision IN ('TRADE','WATCH','WAIT','NO_DECISION')", name="decision"),
    )
