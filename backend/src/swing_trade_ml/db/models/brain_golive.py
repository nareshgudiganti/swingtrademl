"""M18 go-live records: the owner's stage changes and (Task 7) approvals.
Kept apart from db/models/brain.py: these rows sit next to version 1's
signals and orders, which the brain's own tables never do."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from swing_trade_ml.db.base import Base, utcnow


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
