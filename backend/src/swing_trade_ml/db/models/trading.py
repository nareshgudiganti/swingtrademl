"""Trading domain: strategies, signals, orders, positions, trades, equity curve.

Every table here carries a `mode` column ("paper" or "live"). Paper and live
records share the same schema and the same code paths, so the day the switch is
flipped nothing about the logic changes — only which broker fills the order.
Queries always filter on `mode` so six months of paper results never pollute
live P&L, and the paper track record stays queryable afterwards.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from swing_trade_ml.core.enums import (
    OrderStatus,
    OrderType,
    PositionStatus,
    ProductType,
    SignalType,
    TradingMode,
)
from swing_trade_ml.db.base import Base, TimestampMixin


class Strategy(Base, TimestampMixin):
    """A configured strategy instance.

    `strategy_type` selects the implementation from the strategy registry;
    `params` holds that implementation's tunables as JSON so adding a knob to a
    strategy needs no migration.
    """

    __tablename__ = "strategies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text)

    # Key into the STRATEGY_REGISTRY, e.g. "sma_crossover" | "ml_swing"
    strategy_type: Mapped[str] = mapped_column(String(64), index=True)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    mode: Mapped[str] = mapped_column(String(8), default=TradingMode.PAPER, index=True)

    # "auto" places real (paper/live) orders as today; "advisory" only ever
    # notifies with a recommendation — see services/execution.py. Never
    # auto-executed regardless of mode once set to advisory.
    execution_mode: Mapped[str] = mapped_column(String(16), default="auto", index=True)

    # Opt-in: add another tranche to an already-open, currently-profitable
    # position instead of rejecting the entry outright. See services/risk.py
    # open_exposure_value().
    allow_pyramiding: Mapped[bool] = mapped_column(Boolean, default=False)

    # Empty means "every watchlisted instrument"
    symbols: Mapped[list[str]] = mapped_column(JSON, default=list)

    # Per-strategy risk overrides; fall back to global settings when null
    max_positions: Mapped[int | None] = mapped_column(Integer)
    capital_allocation: Mapped[float | None] = mapped_column(Float)
    stop_loss_pct: Mapped[float | None] = mapped_column(Float)
    take_profit_pct: Mapped[float | None] = mapped_column(Float)

    signals: Mapped[list[Signal]] = relationship(back_populates="strategy")
    positions: Mapped[list[Position]] = relationship(back_populates="strategy")

    def __repr__(self) -> str:
        return f"<Strategy {self.name} type={self.strategy_type} active={self.is_active}>"


class Signal(Base, TimestampMixin):
    """A BUY/SELL/HOLD/EXIT recommendation produced by one strategy evaluation.

    Signals are recorded whether or not they are acted on. That is the point of
    the paper phase: a rejected signal (risk limit, low confidence) is as
    informative as an executed one when judging the strategy later.
    """

    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    strategy_id: Mapped[int] = mapped_column(ForeignKey("strategies.id", ondelete="CASCADE"), index=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id", ondelete="CASCADE"), index=True)

    signal_type: Mapped[str] = mapped_column(String(8), default=SignalType.HOLD, index=True)
    mode: Mapped[str] = mapped_column(String(8), default=TradingMode.PAPER, index=True)

    price: Mapped[float] = mapped_column(Float)
    # Model probability (ml strategies) or a rule-based score in [0, 1]
    confidence: Mapped[float | None] = mapped_column(Float)

    suggested_quantity: Mapped[int | None] = mapped_column(Integer)
    stop_loss: Mapped[float | None] = mapped_column(Float)
    take_profit: Mapped[float | None] = mapped_column(Float)

    # Human-readable rationale — what the dashboard and Telegram message show
    reason: Mapped[str | None] = mapped_column(Text)
    # Indicator values / feature vector at signal time, for later post-mortems
    features: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    was_executed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text)

    # True when this was a recommendation only (strategy.execution_mode ==
    # "advisory") — distinct from a rejection: nothing blocked it, it just
    # wasn't auto-acted on. was_executed stays False either way.
    advisory_only: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    strategy: Mapped[Strategy] = relationship(back_populates="signals")
    instrument: Mapped[Any] = relationship("Instrument")
    orders: Mapped[list[Order]] = relationship(back_populates="signal")

    __table_args__ = (Index("ix_signals_scan", "mode", "signal_type", "generated_at"),)

    def __repr__(self) -> str:
        return f"<Signal {self.signal_type} instrument={self.instrument_id} conf={self.confidence}>"


class Order(Base, TimestampMixin):
    """An order request and its lifecycle.

    In paper mode `broker_order_id` is a synthetic `PAPER-…` id; in live mode it
    is Zerodha's real order id. Everything else is identical.
    """

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signals.id", ondelete="SET NULL"), index=True)
    strategy_id: Mapped[int | None] = mapped_column(
        ForeignKey("strategies.id", ondelete="SET NULL"), index=True
    )
    position_id: Mapped[int | None] = mapped_column(
        ForeignKey("positions.id", ondelete="SET NULL"), index=True
    )
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id", ondelete="CASCADE"), index=True)

    broker_order_id: Mapped[str | None] = mapped_column(String(64), index=True)
    mode: Mapped[str] = mapped_column(String(8), default=TradingMode.PAPER, index=True)

    transaction_type: Mapped[str] = mapped_column(String(8))  # TransactionType
    order_type: Mapped[str] = mapped_column(String(8), default=OrderType.MARKET)
    product: Mapped[str] = mapped_column(String(8), default=ProductType.CNC)

    quantity: Mapped[int] = mapped_column(Integer)
    filled_quantity: Mapped[int] = mapped_column(Integer, default=0)
    price: Mapped[float | None] = mapped_column(Float)  # limit price, if any
    trigger_price: Mapped[float | None] = mapped_column(Float)  # for SL orders
    average_price: Mapped[float | None] = mapped_column(Float)  # realised fill price

    status: Mapped[str] = mapped_column(String(16), default=OrderStatus.PENDING, index=True)
    status_message: Mapped[str | None] = mapped_column(Text)

    # Simulated (paper) or actual (live) costs, so paper P&L stays honest
    brokerage: Mapped[float] = mapped_column(Float, default=0.0)
    taxes: Mapped[float] = mapped_column(Float, default=0.0)
    slippage: Mapped[float] = mapped_column(Float, default=0.0)

    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    signal: Mapped[Signal | None] = relationship(back_populates="orders")
    instrument: Mapped[Any] = relationship("Instrument")

    @property
    def total_cost(self) -> float:
        return self.brokerage + self.taxes

    def __repr__(self) -> str:
        return f"<Order {self.transaction_type} {self.quantity} inst={self.instrument_id} {self.status}>"


class Position(Base, TimestampMixin):
    """An open or closed holding.

    A swing position is opened by one entry order and closed by an exit order
    days later, so it holds both sides plus the live mark-to-market fields the
    dashboard reads.
    """

    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    strategy_id: Mapped[int | None] = mapped_column(
        ForeignKey("strategies.id", ondelete="SET NULL"), index=True
    )
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id", ondelete="CASCADE"), index=True)

    mode: Mapped[str] = mapped_column(String(8), default=TradingMode.PAPER, index=True)
    status: Mapped[str] = mapped_column(String(8), default=PositionStatus.OPEN, index=True)

    quantity: Mapped[int] = mapped_column(Integer)
    entry_price: Mapped[float] = mapped_column(Float)
    entry_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    exit_price: Mapped[float | None] = mapped_column(Float)
    exit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exit_reason: Mapped[str | None] = mapped_column(String(24))  # ExitReason

    stop_loss: Mapped[float | None] = mapped_column(Float)
    take_profit: Mapped[float | None] = mapped_column(Float)
    # Highest close seen since entry — the anchor for a trailing stop
    highest_price: Mapped[float | None] = mapped_column(Float)

    # Refreshed by the mark-to-market job while the position is open
    current_price: Mapped[float | None] = mapped_column(Float)
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    realized_pnl: Mapped[float | None] = mapped_column(Float)
    total_charges: Mapped[float] = mapped_column(Float, default=0.0)

    # Set the first time check_exits() alerts on a triggered stop/target for
    # an advisory-mode position, so the 60s job sends exactly one alert
    # instead of re-notifying every minute until the user confirms the exit.
    advisory_alert_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    notes: Mapped[str | None] = mapped_column(Text)

    strategy: Mapped[Strategy | None] = relationship(back_populates="positions")
    instrument: Mapped[Any] = relationship("Instrument")

    __table_args__ = (Index("ix_positions_open", "mode", "status", "instrument_id"),)

    @property
    def invested_value(self) -> float:
        return self.entry_price * self.quantity

    @property
    def holding_days(self) -> int:
        end = self.exit_at or datetime.now(self.entry_at.tzinfo)
        return (end - self.entry_at).days

    def __repr__(self) -> str:
        return f"<Position inst={self.instrument_id} qty={self.quantity} {self.status}>"


class Trade(Base, TimestampMixin):
    """A completed round trip — the immutable record used for performance stats.

    Written once when a position closes. Positions get mutated (marked to
    market, stops trailed); this table never does, so backtest-style analytics
    read from a stable source.
    """

    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    position_id: Mapped[int | None] = mapped_column(
        ForeignKey("positions.id", ondelete="SET NULL"), index=True
    )
    strategy_id: Mapped[int | None] = mapped_column(
        ForeignKey("strategies.id", ondelete="SET NULL"), index=True
    )
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id", ondelete="CASCADE"), index=True)

    mode: Mapped[str] = mapped_column(String(8), default=TradingMode.PAPER, index=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True)  # denormalised for fast reporting

    quantity: Mapped[int] = mapped_column(Integer)
    entry_price: Mapped[float] = mapped_column(Float)
    exit_price: Mapped[float] = mapped_column(Float)
    entry_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    exit_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    holding_days: Mapped[int] = mapped_column(Integer, default=0)

    gross_pnl: Mapped[float] = mapped_column(Float)
    charges: Mapped[float] = mapped_column(Float, default=0.0)
    net_pnl: Mapped[float] = mapped_column(Float)
    return_pct: Mapped[float] = mapped_column(Float)

    exit_reason: Mapped[str | None] = mapped_column(String(24))
    is_win: Mapped[bool] = mapped_column(Boolean, index=True)

    def __repr__(self) -> str:
        return f"<Trade {self.symbol} pnl={self.net_pnl:.2f} ({self.return_pct:.2%})>"


class PortfolioSnapshot(Base, TimestampMixin):
    """Daily equity-curve point.

    Drawdown and Sharpe cannot be reconstructed from trades alone — they need
    the value of the portfolio on days when nothing traded. One row per day per
    mode gives the dashboard its equity chart directly.
    """

    __tablename__ = "portfolio_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    mode: Mapped[str] = mapped_column(String(8), default=TradingMode.PAPER, index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    cash: Mapped[float] = mapped_column(Float)
    holdings_value: Mapped[float] = mapped_column(Float)
    total_value: Mapped[float] = mapped_column(Float)

    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    day_pnl: Mapped[float] = mapped_column(Float, default=0.0)

    open_positions: Mapped[int] = mapped_column(Integer, default=0)
    # Running peak of total_value, so drawdown is a subtraction not a window scan
    peak_value: Mapped[float] = mapped_column(Float, default=0.0)
    drawdown_pct: Mapped[float] = mapped_column(Float, default=0.0)

    __table_args__ = (Index("ix_snapshots_mode_ts", "mode", "ts"),)

    def __repr__(self) -> str:
        return f"<PortfolioSnapshot {self.mode} {self.ts:%Y-%m-%d} value={self.total_value:.2f}>"
