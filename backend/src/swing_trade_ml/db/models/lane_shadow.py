# ruff: noqa: E501 (long explanatory lines)
"""Shared daily shadow-testing lanes (10-day, 15-day): append-only picks and their one-time outcomes.

Both tables are protected in the database by triggers that refuse UPDATE, DELETE and TRUNCATE (see the
migration), so a recorded pick or outcome can never be edited or removed. They reference `ml_models` only to
name the model that scored; nothing here can reach orders, positions, cash, the brain or the sealed trial.
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
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from swing_trade_ml.db.base import Base


class LanePick(Base):
    """One recorded top-5 pick: a test record, never a trade."""

    __tablename__ = "lane_picks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("ml_models.id", ondelete="RESTRICT"), index=True)
    slot_key: Mapped[str] = mapped_column(String(16), index=True)  # "10d-large"
    horizon_days: Mapped[int] = mapped_column(Integer)
    cap_group: Mapped[str] = mapped_column(String(8))  # large | mid
    signal_day: Mapped[date] = mapped_column(Date)  # the IST market session the score was made on
    symbol: Mapped[str] = mapped_column(String(32))
    rank: Mapped[int] = mapped_column(Integer)  # 1..5 within the cap group
    score: Mapped[float] = mapped_column(Float)
    model_version: Mapped[str] = mapped_column(String(64))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    entry_assumption: Mapped[dict[str, Any]] = mapped_column(JSONB)
    target_pct: Mapped[float] = mapped_column(Float)
    stop_pct: Mapped[float] = mapped_column(Float)
    flags: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    __table_args__ = (
        UniqueConstraint("model_id", "signal_day", "symbol", name="uq_lane_picks_model_day_symbol"),
        UniqueConstraint(
            "model_id", "signal_day", "cap_group", "rank", name="uq_lane_picks_model_day_group_rank"
        ),
    )


class LaneOutcome(Base):
    """The result of one pick, written once when its horizon has matured."""

    __tablename__ = "lane_outcomes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    pick_id: Mapped[int] = mapped_column(ForeignKey("lane_picks.id", ondelete="RESTRICT"), unique=True)
    matured_day: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(12))  # target | stop | timeout | unresolved
    entry_fill: Mapped[float | None] = mapped_column(Float)
    exit_day: Mapped[date | None] = mapped_column(Date)
    exit_fill: Mapped[float | None] = mapped_column(Float)
    sessions_held: Mapped[int | None] = mapped_column(Integer)
    gross_return: Mapped[float | None] = mapped_column(Float)  # same rule with brokerage and taxes removed
    net_return: Mapped[float | None] = mapped_column(Float)
    # Mean net return of ALL eligible stocks of the same cap group, entered the same day under the same rule.
    baseline_net_return: Mapped[float | None] = mapped_column(Float)
    excess_return: Mapped[float | None] = mapped_column(Float)
    ambiguous: Mapped[bool] = mapped_column(
        Boolean, default=False
    )  # a bar touched both levels: counted as the stop
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
