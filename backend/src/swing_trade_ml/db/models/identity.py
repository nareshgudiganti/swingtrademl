# ruff: noqa: E501 (long explanatory lines)
"""Stock identity and the score ledger (#389, docs/architecture/IDENTITY-CONTRACTS.md sections 1 and 4).

`securities` is the permanent stock identity; `security_symbols` is its dated symbol history; `security_aliases`
holds the outside ids (the Kite token, the ISIN, later the Groww id) that point at it. `score_ledger` is the
append-only history of every score: a database trigger (see the migration) refuses UPDATE, DELETE and TRUNCATE.

Nothing here is read by trading, sizing, exits, orders or the brain. All of it is additive.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
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
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from swing_trade_ml.db.base import Base, TimestampMixin

SECURITY_ACTIVE = "active"
SECURITY_DELISTED = "delisted"

LEDGER_SCORED = "scored"
LEDGER_MISSING = "missing"
LEDGER_STALE = "stale"
LEDGER_LATE = "late"
LEDGER_NO_SCORE = "no_score"
LEDGER_STATUSES = (LEDGER_SCORED, LEDGER_MISSING, LEDGER_STALE, LEDGER_LATE, LEDGER_NO_SCORE)

SOURCES = ("v1_scan", "prediction", "brain", "catch_up", "backfill")


class Security(Base, TimestampMixin):
    """One real security. The id never changes and is never reused; a symbol can change, the id cannot."""

    __tablename__ = "securities"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # The natural key. Nullable on purpose for now: no ISIN source is loaded on main yet, so a security made from
    # an instrument starts without one and gets it attached later. Postgres allows many NULLs under UNIQUE.
    isin: Mapped[str | None] = mapped_column(String(12), unique=True)
    name: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), default=SECURITY_ACTIVE, server_default=SECURITY_ACTIVE)
    # An ISIN change (merger, face-value change) is a NEW security linked to the old one, never a silent merge.
    successor_of_id: Mapped[int | None] = mapped_column(ForeignKey("securities.id", ondelete="RESTRICT"))


class SecuritySymbol(Base):
    """A symbol a security carried on one exchange between two dates (valid_to empty = still current)."""

    __tablename__ = "security_symbols"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    security_id: Mapped[int] = mapped_column(ForeignKey("securities.id", ondelete="RESTRICT"), index=True)
    exchange: Mapped[str] = mapped_column(String(16))
    symbol: Mapped[str] = mapped_column(String(64))
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)

    __table_args__ = (
        UniqueConstraint("exchange", "symbol", "valid_from", name="uq_security_symbols_exchange_symbol_from"),
        CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="valid_range"),
        Index("ix_security_symbols_lookup", "exchange", "symbol"),
    )


class SecurityAlias(Base):
    """An outside id for a security: provider 'kite_token', 'isin' or 'groww'. One alias belongs to one security."""

    __tablename__ = "security_aliases"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    security_id: Mapped[int] = mapped_column(ForeignKey("securities.id", ondelete="RESTRICT"), index=True)
    provider: Mapped[str] = mapped_column(String(16))
    external_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("provider", "external_id", name="uq_security_aliases_provider_external"),)


class ScoreLedger(Base):
    """Every score ever recorded, once. A re-run with a different value is a new revision, never an update.

    Key (see the unique index in the migration): security, session date, horizon (NULL counts as one value),
    source, model name, model version, revision. `session_date` is the market session of the candle that was
    scored, never the clock day of the call. A gap is a row with status 'missing', never an absence and never 0.
    """

    __tablename__ = "score_ledger"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    security_id: Mapped[int] = mapped_column(ForeignKey("securities.id", ondelete="RESTRICT"), index=True)
    session_date: Mapped[date] = mapped_column(Date)
    horizon_days: Mapped[int | None] = mapped_column(SmallInteger)
    source: Mapped[str] = mapped_column(String(16))
    model_id: Mapped[int | None] = mapped_column(Integer)  # plain id: a ledger row must outlive the model row
    model_name: Mapped[str] = mapped_column(String(64), default="", server_default="")
    model_version: Mapped[str] = mapped_column(String(64), default="", server_default="")
    score: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(12), default=LEDGER_SCORED, server_default=LEDGER_SCORED)
    scan_key: Mapped[str | None] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    supersedes_id: Mapped[int | None] = mapped_column(ForeignKey("score_ledger.id", ondelete="RESTRICT"))
    input_cutoff: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    run_ref: Mapped[str | None] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index(
            "uq_score_ledger_key",
            "security_id",
            "session_date",
            text("coalesce(horizon_days, -1)"),
            "source",
            "model_name",
            "model_version",
            "revision",
            unique=True,
        ),
        Index("ix_score_ledger_security_session", "security_id", "session_date"),
        CheckConstraint("status IN ('scored','missing','stale','late','no_score')", name="status"),
        CheckConstraint("revision >= 1", name="revision"),
    )
