"""Shared enumerations.

These are stored as strings in Postgres rather than native PG enums — adding a
new value then needs no migration, which matters while the strategy set is
still evolving.
"""

from __future__ import annotations

from enum import StrEnum


class TradingMode(StrEnum):
    PAPER = "paper"
    LIVE = "live"


class SignalType(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    EXIT = "EXIT"


class TransactionType(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"
    SL_M = "SL-M"


class ProductType(StrEnum):
    """CNC = delivery (overnight). Swing trades hold for days, so CNC is the
    default; MIS is intraday-only and would be auto-squared-off at close."""

    CNC = "CNC"
    MIS = "MIS"
    NRML = "NRML"


class OrderStatus(StrEnum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class PositionStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ExitReason(StrEnum):
    TARGET_HIT = "TARGET_HIT"
    STOP_LOSS_HIT = "STOP_LOSS_HIT"
    SIGNAL_EXIT = "SIGNAL_EXIT"
    MANUAL = "MANUAL"
    RISK_LIMIT = "RISK_LIMIT"
    TIME_STOP = "TIME_STOP"


class CandleInterval(StrEnum):
    MINUTE = "minute"
    MIN_3 = "3minute"
    MIN_5 = "5minute"
    MIN_15 = "15minute"
    MIN_30 = "30minute"
    MIN_60 = "60minute"
    DAY = "day"


class ModelStatus(StrEnum):
    TRAINING = "TRAINING"
    TRAINED = "TRAINED"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    FAILED = "FAILED"


class NotificationEvent(StrEnum):
    SIGNAL = "signal"
    ORDER = "order"
    FILL = "fill"
    ERROR = "error"
    DAILY_SUMMARY = "daily_summary"
    SYSTEM = "system"
