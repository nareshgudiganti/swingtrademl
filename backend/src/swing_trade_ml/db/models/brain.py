"""The brain's own records: every run with its trace, every decision it made,
and the owner's ON / SHADOW / OFF switch per module.

The brain never writes to version 1's tables (signals, orders, positions).
These three are its audit trail: any decision can be traced back to which
modules ran, which fell back, and why.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from swing_trade_ml.db.base import Base, TimestampMixin, utcnow


class BrainRun(Base):
    __tablename__ = "brain_runs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)  # nightly | intraday | why
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    book: Mapped[str] = mapped_column(String(8))
    live: Mapped[bool] = mapped_column(default=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="done")  # done | failed
    error: Mapped[str | None] = mapped_column(Text)
    banner_mode: Mapped[str | None] = mapped_column(String(16))
    banner_headline: Mapped[str | None] = mapped_column(Text)
    modules: Mapped[dict] = mapped_column(JSONB, default=dict)  # module id -> mode used
    trace: Mapped[list] = mapped_column(JSONB, default=list)
    # {"overall": {score, fresh, issues}, "stale": [symbols]} from the data
    # gateway (M01), so the console can show data health without re-running.
    quality: Mapped[dict] = mapped_column(JSONB, default=dict)


class BrainDecision(Base):
    __tablename__ = "brain_decisions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("brain_runs.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(8))  # idea | holding
    word: Mapped[str] = mapped_column(String(8), index=True)
    entry_low: Mapped[float | None] = mapped_column(Float)
    entry_high: Mapped[float | None] = mapped_column(Float)
    target: Mapped[float | None] = mapped_column(Float)
    stop: Mapped[float | None] = mapped_column(Float)
    qty: Mapped[int] = mapped_column(Integer, default=0)
    horizon_days: Mapped[int] = mapped_column(Integer, default=15)
    confidence: Mapped[float | None] = mapped_column(Float)
    evidence_text: Mapped[str | None] = mapped_column(Text)
    reasons: Mapped[list] = mapped_column(JSONB, default=list)
    downgraded_from: Mapped[str | None] = mapped_column(String(8))
    downgrade_reason: Mapped[str | None] = mapped_column(Text)
    # The owner's overrule (constitution C8): only ever more cautious than
    # `word`, and always with who and why. The brain's own word is kept.
    overruled_word: Mapped[str | None] = mapped_column(String(8))
    overrule_reason: Mapped[str | None] = mapped_column(Text)
    overruled_by: Mapped[str | None] = mapped_column(String(128))
    overruled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BrainModuleSetting(Base, TimestampMixin):
    """The owner's switch for one module. No row means the module's default."""

    __tablename__ = "brain_modules"

    module_id: Mapped[str] = mapped_column(String(8), primary_key=True)
    mode: Mapped[str] = mapped_column(String(8))  # on | shadow | off
    changed_by: Mapped[str | None] = mapped_column(String(128))
    note: Mapped[str | None] = mapped_column(Text)
