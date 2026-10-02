"""The brain's own records: every run with its trace, every decision it made,
and the owner's ON / SHADOW / OFF switch per module.

The brain never writes to version 1's tables (signals, orders, positions).
These three are its audit trail: any decision can be traced back to which
modules ran, which fell back, and why.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
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
    # When the alert service compared this run with the one before (M16).
    # Only such runs are a baseline for the next alert; a manual "Run now"
    # never is, so it cannot swallow the scheduled run's alerts.
    alerts_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # What the run knew beyond its decisions, for the console: {"sectors": [...]}
    # (M11). None on runs stored before this column existed.
    context: Mapped[dict | None] = mapped_column(JSONB)


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
    # The learning loop's grade of this idea against the locked rule (M09):
    # target | stop | timeout, written once the outcome is fully known.
    outcome: Mapped[str | None] = mapped_column(String(8))
    outcome_return: Mapped[float | None] = mapped_column(Float)
    outcome_days: Mapped[int | None] = mapped_column(Integer)
    max_up: Mapped[float | None] = mapped_column(Float)
    max_down: Mapped[float | None] = mapped_column(Float)
    resolved_on: Mapped[date | None] = mapped_column(Date)
    # What kind of opinion `confidence` came from (M09): "model" for a raw
    # score, "combined" for M06's calibrated chance, etc. — None when
    # `confidence` is some other opinion's own confidence, not a probability
    # at all. Only "model" rows are a ranking the buy-level proposal can
    # reason about; the rest would silently mix incomparable numbers.
    score_source: Mapped[str | None] = mapped_column(String(16))


class BrainProposal(Base, TimestampMixin):
    """Something the learning loop noticed and wants to change (M09) — never
    takes effect on its own (constitution C9): the owner must accept it first."""

    __tablename__ = "brain_proposals"
    __table_args__ = (Index("ix_brain_proposals_status", "status"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String(24))  # e.g. buy_level | module_mode
    title: Mapped[str] = mapped_column(Text)
    evidence: Mapped[str] = mapped_column(Text)
    change: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(12), default="open")  # open | accepted | dismissed
    decided_by: Mapped[str | None] = mapped_column(String(128))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_note: Mapped[str | None] = mapped_column(Text)


class BrainLearningRun(Base):
    """One weekly learning-loop check's feature-drift result (M09), stored so
    the console can read it back instantly — walking every watch-listed
    stock's history to recompute drift is far too slow to do on every page
    load (spec finding F3)."""

    __tablename__ = "brain_learning_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    drift: Mapped[list] = mapped_column(JSONB, default=list)
    drift_lines: Mapped[list] = mapped_column(JSONB, default=list)
    drift_note: Mapped[str | None] = mapped_column(Text)


class BrainModuleSetting(Base, TimestampMixin):
    """The owner's switch for one module. No row means the module's default."""

    __tablename__ = "brain_modules"

    module_id: Mapped[str] = mapped_column(String(8), primary_key=True)
    mode: Mapped[str] = mapped_column(String(8))  # on | shadow | off
    changed_by: Mapped[str | None] = mapped_column(String(128))
    note: Mapped[str | None] = mapped_column(Text)


class FeatureSnapshot(Base):
    """What the brain saw for one stock on one day (M02): the model's own
    features and a few plain facts, from bars that end on that day. Stored by
    nightly runs so any past day can be replayed exactly. One row per stock,
    bar day and feature-set version; a re-run of the same night replaces it."""

    __tablename__ = "feature_snapshots"
    __table_args__ = (UniqueConstraint("symbol", "bar_date", "feature_set_version"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    bar_date: Mapped[date] = mapped_column(Date, index=True)
    feature_set_version: Mapped[str] = mapped_column(String(16))
    run_id: Mapped[str | None] = mapped_column(ForeignKey("brain_runs.id", ondelete="SET NULL"))
    close: Mapped[float] = mapped_column(Float)
    atr_14: Mapped[float | None] = mapped_column(Float)
    adv_inr_20: Mapped[float | None] = mapped_column(Float)
    features: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BrainAlert(Base):
    """One thing the owner was told (M16), so it is told only once a day."""

    __tablename__ = "brain_alerts"
    __table_args__ = (UniqueConstraint("alert_key", "alert_date"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    alert_key: Mapped[str] = mapped_column(String(96))
    alert_date: Mapped[date] = mapped_column(Date, index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("brain_runs.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(String(16), default="telegram")
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BrainEpisode(Base, TimestampMixin):
    """A stretch of days under one situation label — the start of the brain's
    market memory (M04). `end_day` is empty while the episode is still going."""

    __tablename__ = "brain_episodes"
    __table_args__ = (UniqueConstraint("scope", "start_day", name="uq_brain_episode_start"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    scope: Mapped[str] = mapped_column(String(16), index=True)  # market (later: sector, stock)
    label: Mapped[str] = mapped_column(String(32))
    start_day: Mapped[date] = mapped_column(Date, index=True)
    end_day: Mapped[date | None] = mapped_column(Date)
    state_key: Mapped[str] = mapped_column(String(64), default="")
    stats: Mapped[dict] = mapped_column(JSONB, default=dict)


class BrainExperience(Base):
    """One past stock-day the memory (M05) can recall: its situation key and
    what happened next under the locked rule. Rebuilt from candles, so it is
    a cache of history, not a record of anything the brain did."""

    __tablename__ = "brain_experience"
    __table_args__ = (UniqueConstraint("symbol", "day", name="uq_brain_experience"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    market: Mapped[str] = mapped_column(String(32))
    stock: Mapped[str] = mapped_column(String(16))
    trend: Mapped[str] = mapped_column(String(16))
    vol: Mapped[str] = mapped_column(String(16))
    outcome: Mapped[str] = mapped_column(String(8))  # target | stop | timeout
    exit_return: Mapped[float] = mapped_column(Float)
    days: Mapped[int] = mapped_column(Integer)
    outcome_day: Mapped[date] = mapped_column(Date, index=True)
    path_day: Mapped[date] = mapped_column(Date)
    path: Mapped[list] = mapped_column(JSONB, default=list)


class BrainTrack(Base, TimestampMixin):
    """One open trade on one day against the band of similar trades (M15).
    The stop stored here never goes below the one stored the day before."""

    __tablename__ = "brain_track"
    __table_args__ = (UniqueConstraint("book", "symbol", "opened_on", "day", name="uq_brain_track_day"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    book: Mapped[str] = mapped_column(String(8))
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    opened_on: Mapped[date] = mapped_column(Date)
    day: Mapped[date] = mapped_column(Date, index=True)
    day_n: Mapped[int] = mapped_column(Integer)
    ret: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(Text, default="")
    stop: Mapped[float | None] = mapped_column(Float)
    band: Mapped[list] = mapped_column(JSONB, default=list)
