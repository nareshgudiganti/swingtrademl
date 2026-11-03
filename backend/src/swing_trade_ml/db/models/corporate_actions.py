"""Verified corporate actions and the record of what each one did to a paper position.

Additive, no foreign key into orders or trades, and nothing here is read by the exit path. An adjustment
row is the audit trail and the idempotency key: one per (action, position), with the full before and after.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from swing_trade_ml.db.base import Base, utcnow


class CorporateAction(Base):
    """One announced event, entered by hand after checking the company's own announcement.

    split: ratio_numerator / ratio_denominator = old face value / new face value (10 to 2 -> 10 / 2).
    bonus: ratio_numerator new shares for every ratio_denominator held (1:2 -> 1 / 2).
    Other kinds are stored so they can be flagged for review, never adjusted.
    """

    __tablename__ = "corporate_actions"
    __table_args__ = (UniqueConstraint("instrument_id", "kind", "ex_date", name="uq_corporate_action"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(
        String(16)
    )  # split | bonus | demerger | rights | dividend | merger | buyback
    ex_date: Mapped[date] = mapped_column(Date)
    ratio_numerator: Mapped[int | None] = mapped_column(Integer)
    ratio_denominator: Mapped[int | None] = mapped_column(Integer)
    source_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), default="UNVERIFIED")  # VERIFIED | UNVERIFIED
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PositionAdjustment(Base):
    """What one action did (or could not do) to one position. Never deleted, never rewritten once APPLIED."""

    __tablename__ = "position_adjustments"
    __table_args__ = (UniqueConstraint("action_id", "position_id", name="uq_position_adjustment"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    action_id: Mapped[int] = mapped_column(ForeignKey("corporate_actions.id", ondelete="CASCADE"), index=True)
    position_id: Mapped[int] = mapped_column(ForeignKey("positions.id", ondelete="CASCADE"), index=True)
    book: Mapped[str] = mapped_column(String(8))  # bot | tester | real
    status: Mapped[str] = mapped_column(String(14))  # APPLIED | NEEDS_REVIEW | SKIPPED
    before: Mapped[dict[str, Any]] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    expected_exit: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    explanation: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
