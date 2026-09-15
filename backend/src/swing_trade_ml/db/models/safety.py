"""Runtime safety state: the kill switch, and the record of every entry the
risk layer refused.

Everything else that governs trading is either an environment setting (read
once at process start — `Settings` is lru_cached) or a per-strategy column.
Neither can stop the whole bot *now*, from the dashboard, without a redeploy.
These two tables are that missing piece.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from swing_trade_ml.db.base import Base, TimestampMixin, utcnow


class SystemState(Base, TimestampMixin):
    """Exactly one row, id=1, inserted by the migration.

    Read fresh on every decision (services/system_state.py) and never cached,
    for the same reason the live-trading latches are: a halt that only takes
    effect after a cache expiry or a restart is not a halt.

    Entries and exits are separate switches on purpose. Halting entries is
    the normal emergency act and is always safe — existing positions keep
    their stops. Disabling exits is a different, deliberate act that can trap
    capital in a falling position, so it is never implied by a halt.
    """

    __tablename__ = "system_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    new_entries_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    exits_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    halt_reason: Mapped[str | None] = mapped_column(Text)
    halted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    halted_by: Mapped[str | None] = mapped_column(String(128))


class RiskEvent(Base):
    """One entry the risk layer refused, and why.

    `check_entry` already produced a reason for every rejection; before this
    table it lived only on the Signal row, mixed in with non-risk outcomes.
    Keeping them here, keyed by a short `rule` code, is what lets the paper
    phase answer "how often did the sector cap bite, and did it help?".
    """

    __tablename__ = "risk_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    mode: Mapped[str] = mapped_column(String(8), index=True)
    strategy_id: Mapped[int | None] = mapped_column(
        ForeignKey("strategies.id", ondelete="SET NULL"), index=True
    )
    instrument_id: Mapped[int | None] = mapped_column(
        ForeignKey("instruments.id", ondelete="SET NULL"), index=True
    )
    symbol: Mapped[str | None] = mapped_column(String(64))
    # Short stable code, e.g. "SECTOR_CAP", "HALTED", "DRAWDOWN".
    rule: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str] = mapped_column(Text)
    amount_inr: Mapped[float | None] = mapped_column(Float)
