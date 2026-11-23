# ruff: noqa: E501 (long explanatory lines)
"""Persistence for the research paper simulation (#321, #379): synthetic portfolios, their daily ledger rows, fills,
exits, blocked decisions and the rules that were NOT applied.

Everything in these tables is SYNTHETIC. There is no `user_id` anywhere and no foreign key to a user or an account:
a simulated portfolio belongs to a fictional persona key (`syn-001`), never to a real person, so no customer screen
can reach it. `synthetic` is stamped true and the database refuses anything else. The only code that reads or writes
these tables is `simulation/store.py` (a test pins that).

Every row that came from a decision carries the permanent stock id (`security_id`, #389), the horizon record it was
decided from (`horizon_record_id`, #387; empty only for a policy with no record source), the policy and the rule
version, so a result traces stock -> horizon record -> policy and rule version -> simulated fill.

The schema is versioned (`sim_runs.schema_version`). Nothing here is read by trading, sizing, exits, orders or the
brain, and no job writes to it yet.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from swing_trade_ml.db.base import Base

SCHEMA_VERSION = 1
POLICIES = ("momentum", "model_only", "brain_filtered")


class SimRun(Base):
    """One simulation run: one rule version over one set of sessions. A run never mixes rule versions."""

    __tablename__ = "sim_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_key: Mapped[str] = mapped_column(String(64), unique=True)
    schema_version: Mapped[int] = mapped_column(SmallInteger, default=SCHEMA_VERSION, server_default="1")
    rule_version: Mapped[str] = mapped_column(String(32))  # for example hz-rules-v1:5D
    research_config_version: Mapped[str] = mapped_column(String(32))
    research_only: Mapped[bool] = mapped_column(Boolean)
    horizon_days: Mapped[int] = mapped_column(SmallInteger)
    synthetic: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    first_session: Mapped[date | None] = mapped_column(Date)
    last_session: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("horizon_days IN (5, 10, 15)", name="ck_sim_runs_horizon"),
        CheckConstraint("synthetic", name="ck_sim_runs_synthetic"),
    )


class SimPortfolio(Base):
    """One of the 100 fictional portfolios of a run (99 compared, 1 validation)."""

    __tablename__ = "sim_portfolios"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("sim_runs.id", ondelete="RESTRICT"), index=True)
    persona_key: Mapped[str] = mapped_column(String(16))
    setup_key: Mapped[str] = mapped_column(String(16))
    policy: Mapped[str] = mapped_column(String(16))
    balance_inr: Mapped[int] = mapped_column(BigInteger)
    start_offset: Mapped[int] = mapped_column(SmallInteger)
    counts_in_comparison: Mapped[bool] = mapped_column(Boolean)  # False for the validation portfolio only
    rule_version: Mapped[str] = mapped_column(String(32))
    research_only: Mapped[bool] = mapped_column(Boolean)
    synthetic: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("run_id", "persona_key", name="uq_sim_portfolios_persona"),
        # at most one validation portfolio per run, and it is the only one outside the comparison
        Index(
            "uq_sim_portfolios_one_validation",
            "run_id",
            unique=True,
            postgresql_where=text("NOT counts_in_comparison"),
        ),
        CheckConstraint(
            "policy IN ('momentum','model_only','brain_filtered')", name="ck_sim_portfolios_policy"
        ),
        CheckConstraint("balance_inr > 0", name="ck_sim_portfolios_balance"),
        CheckConstraint("start_offset >= 0", name="ck_sim_portfolios_offset"),
        CheckConstraint("synthetic", name="ck_sim_portfolios_synthetic"),
    )


class SimNotApplied(Base):
    """An app rule this portfolio's run did NOT apply, stated in words, so nothing claims it was applied."""

    __tablename__ = "sim_not_applied"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("sim_portfolios.id", ondelete="RESTRICT"), index=True
    )
    rule_text: Mapped[str] = mapped_column(String(255))

    __table_args__ = (UniqueConstraint("portfolio_id", "rule_text", name="uq_sim_not_applied"),)


class SimDay(Base):
    """One portfolio's closing state for one session: cash, equity and whether the drawdown halt was on."""

    __tablename__ = "sim_days"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("sim_portfolios.id", ondelete="RESTRICT"))
    session_date: Mapped[date] = mapped_column(Date)
    cash: Mapped[float] = mapped_column(Float)
    equity: Mapped[float] = mapped_column(Float)
    halted: Mapped[bool] = mapped_column(Boolean)
    market_mode: Mapped[str] = mapped_column(String(24), default="", server_default="")
    rule_version: Mapped[str] = mapped_column(String(32))
    research_only: Mapped[bool] = mapped_column(Boolean)

    __table_args__ = (
        UniqueConstraint("portfolio_id", "session_date", name="uq_sim_days_key"),
        CheckConstraint("cash >= 0", name="ck_sim_days_cash_not_negative"),
    )


class SimFill(Base):
    """A simulated buy. `horizon_record_id` is the recommendation it was decided from (empty for momentum)."""

    __tablename__ = "sim_fills"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("sim_portfolios.id", ondelete="RESTRICT"))
    session_date: Mapped[date] = mapped_column(Date)
    security_id: Mapped[int] = mapped_column(ForeignKey("securities.id", ondelete="RESTRICT"), index=True)
    symbol: Mapped[str] = mapped_column(String(64))  # display only
    horizon_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("horizon_records.id", ondelete="RESTRICT"), index=True
    )
    policy: Mapped[str] = mapped_column(String(16))
    rule_version: Mapped[str] = mapped_column(String(32))
    qty: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Float)
    charges: Mapped[float] = mapped_column(Float)
    cost: Mapped[float] = mapped_column(Float)

    __table_args__ = (
        UniqueConstraint("portfolio_id", "session_date", "security_id", name="uq_sim_fills_key"),
        CheckConstraint("qty > 0", name="ck_sim_fills_qty"),
        CheckConstraint("policy IN ('momentum','model_only','brain_filtered')", name="ck_sim_fills_policy"),
    )


class SimExit(Base):
    """A simulated sale (stop, half-out, target or horizon), tied to the record its buy came from."""

    __tablename__ = "sim_exits"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("sim_portfolios.id", ondelete="RESTRICT"))
    session_date: Mapped[date] = mapped_column(Date)
    security_id: Mapped[int] = mapped_column(ForeignKey("securities.id", ondelete="RESTRICT"), index=True)
    symbol: Mapped[str] = mapped_column(String(64))
    horizon_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("horizon_records.id", ondelete="RESTRICT")
    )
    policy: Mapped[str] = mapped_column(String(16))
    rule_version: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(String(12))
    qty: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Float)
    proceeds: Mapped[float] = mapped_column(Float)
    stale: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))

    __table_args__ = (
        UniqueConstraint("portfolio_id", "session_date", "security_id", "reason", name="uq_sim_exits_key"),
        CheckConstraint("qty > 0", name="ck_sim_exits_qty"),
        CheckConstraint("reason IN ('stop','half_out','target','horizon')", name="ck_sim_exits_reason"),
    )


class SimBlock(Base):
    """A pick that was NOT bought, with the plain reason. `seq` is its order within the day."""

    __tablename__ = "sim_blocks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("sim_portfolios.id", ondelete="RESTRICT"))
    session_date: Mapped[date] = mapped_column(Date)
    seq: Mapped[int] = mapped_column(SmallInteger)
    security_id: Mapped[int] = mapped_column(ForeignKey("securities.id", ondelete="RESTRICT"), index=True)
    symbol: Mapped[str] = mapped_column(String(64))
    horizon_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("horizon_records.id", ondelete="RESTRICT")
    )
    policy: Mapped[str] = mapped_column(String(16))
    rule_version: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(String(255))

    __table_args__ = (UniqueConstraint("portfolio_id", "session_date", "seq", name="uq_sim_blocks_key"),)


class SimMark(Base):
    """An open position at the close of a session, marked at the last close (stale when there was no bar)."""

    __tablename__ = "sim_marks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("sim_portfolios.id", ondelete="RESTRICT"))
    session_date: Mapped[date] = mapped_column(Date)
    security_id: Mapped[int] = mapped_column(ForeignKey("securities.id", ondelete="RESTRICT"), index=True)
    symbol: Mapped[str] = mapped_column(String(64))
    qty: Mapped[int] = mapped_column(Integer)
    mark: Mapped[float] = mapped_column(Float)
    value: Mapped[float] = mapped_column(Float)
    half_done: Mapped[bool] = mapped_column(Boolean)
    stale: Mapped[bool] = mapped_column(Boolean)

    __table_args__ = (
        UniqueConstraint("portfolio_id", "session_date", "security_id", name="uq_sim_marks_key"),
        CheckConstraint("qty > 0", name="ck_sim_marks_qty"),
    )


SIM_TABLES = (
    "sim_runs",
    "sim_portfolios",
    "sim_not_applied",
    "sim_days",
    "sim_fills",
    "sim_exits",
    "sim_blocks",
    "sim_marks",
)
