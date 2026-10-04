"""M18 go-live records: the owner's stage changes and (Task 7) approvals.
Kept apart from db/models/brain.py: these rows sit next to version 1's
signals and orders, which the brain's own tables never do."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from swing_trade_ml.db.base import Base, TimestampMixin, utcnow


class BrainStageChange(Base):
    """One owner switch of the brain's trading stage. The newest row is the
    stage in force; no row means "shadow". Rows are never edited."""

    __tablename__ = "brain_stage_changes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    stage: Mapped[str] = mapped_column(String(12))  # shadow | approval | auto
    previous_stage: Mapped[str] = mapped_column(String(12))
    changed_by: Mapped[str] = mapped_column(String(128))
    reason: Mapped[str] = mapped_column(Text)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class BrainApproval(Base, TimestampMixin):
    """One brain idea waiting for (or decided by) the owner's OK (M18 stage 2).

    status: pending (waiting for the OK) | waiting (approved while the market
    was closed; bought at the next open after every check runs again) |
    approved (the order was sent) | rejected | expired."""

    __tablename__ = "brain_approvals"
    __table_args__ = (
        Index("ix_brain_approvals_status", "status"),
        Index("ix_brain_approvals_decision_day", "decision_day"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    signal_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("signals.id", ondelete="CASCADE"), unique=True
    )
    strategy_id: Mapped[int] = mapped_column(ForeignKey("strategies.id", ondelete="CASCADE"))
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id", ondelete="CASCADE"))
    symbol: Mapped[str] = mapped_column(String(64))
    decision_day: Mapped[date] = mapped_column(Date)
    price: Mapped[float] = mapped_column(Float)
    stop_loss: Mapped[float | None] = mapped_column(Float)
    take_profit: Mapped[float | None] = mapped_column(Float)
    suggested_qty: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[str] = mapped_column(String(12), default="pending", server_default="pending")
    decided_by: Mapped[str | None] = mapped_column(String(128))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_note: Mapped[str | None] = mapped_column(Text)
    position_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("positions.id", ondelete="SET NULL")
    )
    result_note: Mapped[str | None] = mapped_column(Text)
