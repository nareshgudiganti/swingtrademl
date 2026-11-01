# ruff: noqa: E501 (long explanatory lines)
"""Model registry, phase 1: the owner's research notes per model slot.

One new table. It holds labels and numbers the owner types (research status, priority, a note); nothing
reads it to decide anything. No foreign key to a model, strategy, order or brain table, so it cannot
reach the bot's models, cash or the sealed trial.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from swing_trade_ml.db.base import Base, utcnow


class ModelResearchSlot(Base):
    """One of nine slots: 5, 10 or 15 trading days across large, mid and small caps."""

    __tablename__ = "model_research_slots"

    slot_key: Mapped[str] = mapped_column(String(16), primary_key=True)  # "15d-large"
    horizon_days: Mapped[int] = mapped_column(Integer)
    cap_tier: Mapped[str] = mapped_column(String(12))  # large | midcap | smallcap
    # Descriptive labels only. They do not mean "validated" and start nothing.
    research_status: Mapped[str] = mapped_column(String(16), default="not_started")
    priority: Mapped[int | None] = mapped_column(Integer)  # 1 = first; duplicates allowed; null = unranked
    note: Mapped[str | None] = mapped_column(Text)
    # Bumped by every change. A change must name the version it saw, so two owners cannot overwrite each other.
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(128))
