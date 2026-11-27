# ruff: noqa: E501 (long explanatory lines)
"""Scan record tables (#260): one row per nightly pass, and where each stock ranked.

Both tables are add-only (a database trigger in the migration refuses UPDATE, DELETE and TRUNCATE), kept permanently
and are plain tables, not hypertables. Nothing writes to them yet: the writer is not built and no setting turns one
on. Nothing here is read by trading, sizing, exits, orders or the brain.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from swing_trade_ml.db.base import Base


class ScanRunRow(Base):
    """One nightly scoring pass: how many stocks were expected, scored, stale, missing or skipped."""

    __tablename__ = "scan_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    scan_key: Mapped[str] = mapped_column(
        String(64)
    )  # same format as horizon_records.scan_key, e.g. 'h5:2026-11-26'
    session_date: Mapped[date] = mapped_column(Date)
    horizon_days: Mapped[int] = mapped_column(SmallInteger)
    pass_no: Mapped[int] = mapped_column(SmallInteger, default=1, server_default="1")
    is_final: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    universe_count: Mapped[int] = mapped_column(Integer)
    scored_count: Mapped[int] = mapped_column(Integer)
    stale_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    missing_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    skipped_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    skipped_symbols: Mapped[str | None] = mapped_column(Text)  # JSON text, sorted list
    model_versions: Mapped[str | None] = mapped_column(
        Text
    )  # JSON text, sorted "<model_id>:<name>:<version>"
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_scan_runs_session", "session_date", "horizon_days"),
        Index("uq_scan_runs_key", "scan_key", "horizon_days", "pass_no", unique=True),
        CheckConstraint("horizon_days IN (5, 10, 15)", name="horizon"),
        CheckConstraint("pass_no >= 1", name="pass"),
        CheckConstraint(
            "universe_count >= 0 AND scored_count >= 0 AND stale_count >= 0 "
            "AND missing_count >= 0 AND skipped_count >= 0 "
            "AND scored_count + stale_count + missing_count + skipped_count <= universe_count",
            name="counts",
        ),
    )


class HorizonRankRow(Base):
    """Where one recorded score ranked in its day's cohort (1 = best; ties share a rank). Absent row = unranked."""

    __tablename__ = "horizon_ranks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    horizon_record_id: Mapped[int] = mapped_column(ForeignKey("horizon_records.id", ondelete="RESTRICT"))
    security_id: Mapped[int] = mapped_column(ForeignKey("securities.id", ondelete="RESTRICT"), index=True)
    session_date: Mapped[date] = mapped_column(Date)
    horizon_days: Mapped[int] = mapped_column(SmallInteger)
    model_id: Mapped[int | None] = mapped_column(Integer)  # plain id, same as horizon_records.model_id
    rank_no: Mapped[int] = mapped_column(Integer)
    cohort_size: Mapped[int] = mapped_column(Integer)
    rank_revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    scan_run_id: Mapped[int | None] = mapped_column(ForeignKey("scan_runs.id", ondelete="RESTRICT"))
    source: Mapped[str] = mapped_column(String(12), default="live", server_default="live")
    ranked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_horizon_ranks_session", "session_date", "horizon_days", "rank_no"),
        Index("uq_horizon_ranks_key", "horizon_record_id", "rank_revision", unique=True),
        CheckConstraint("horizon_days IN (5, 10, 15)", name="horizon"),
        CheckConstraint("rank_no >= 1 AND rank_no <= cohort_size", name="rank"),
        CheckConstraint("rank_revision >= 1", name="revision"),
        CheckConstraint("source IN ('live', 'backfill')", name="source"),
    )
