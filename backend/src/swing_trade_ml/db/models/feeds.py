"""Daily market information from NSE that price candles do not contain.

Every row is stamped with the trading date it describes, and the loaders only
ever add rows for a date once that date's file exists — so a feature built
from these tables can never see something that was not public yet.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import BigInteger, Date, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from swing_trade_ml.db.base import Base, TimestampMixin


class DailyDelivery(Base, TimestampMixin):
    """One row per stock per day from NSE's full bhavcopy.

    `delivery_pct` is the share of the day's traded shares that were actually
    taken into a demat account rather than squared off the same day — the
    cleanest public trace of conviction buying. `series` is kept because a
    stock moved to series BE is in trade-for-trade, which is a restriction the
    entry filter needs to know about.
    """

    __tablename__ = "daily_delivery"
    __table_args__ = (UniqueConstraint("symbol", "series", "trade_date", name="uq_daily_delivery"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    series: Mapped[str] = mapped_column(String(8))
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    close_price: Mapped[float | None] = mapped_column(Float)
    traded_qty: Mapped[int | None] = mapped_column(BigInteger)
    turnover_lacs: Mapped[float | None] = mapped_column(Float)
    trades: Mapped[int | None] = mapped_column(Integer)
    delivery_qty: Mapped[int | None] = mapped_column(BigInteger)
    delivery_pct: Mapped[float | None] = mapped_column(Float)


class BlockDeal(Base, TimestampMixin):
    """A named bulk or block deal. `deal_key` makes reloading the same file
    a no-op — the source has no id of its own."""

    __tablename__ = "block_deals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    deal_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(8))  # bulk | block
    client_name: Mapped[str] = mapped_column(String(255))
    side: Mapped[str] = mapped_column(String(4))  # BUY | SELL
    quantity: Mapped[int] = mapped_column(BigInteger)
    price: Mapped[float] = mapped_column(Float)


class InstitutionalFlow(Base, TimestampMixin):
    """Net rupee crore bought or sold by foreign (FII/FPI) and domestic (DII)
    institutions on one day."""

    __tablename__ = "institutional_flows"
    __table_args__ = (UniqueConstraint("trade_date", "category", name="uq_institutional_flow"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    category: Mapped[str] = mapped_column(String(8))  # FII | DII
    buy_value: Mapped[float] = mapped_column(Float)
    sell_value: Mapped[float] = mapped_column(Float)
    net_value: Mapped[float] = mapped_column(Float)


class UpcomingEvent(Base, TimestampMixin):
    """A dated company event that can move a price on its own: a results
    announcement, or a split / bonus / rights issue. Forward-looking, so it is
    refreshed every morning rather than accumulated as history."""

    __tablename__ = "upcoming_events"
    __table_args__ = (UniqueConstraint("symbol", "kind", "event_date", name="uq_upcoming_event"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(24))  # results | corporate_action
    event_date: Mapped[date] = mapped_column(Date, index=True)
    detail: Mapped[str] = mapped_column(String(400), default="")


class TradingRestriction(Base, TimestampMixin):
    """A stock on one of NSE's surveillance lists (ASM or GSM) on a given day.
    Listed stocks can face higher margins or trading limits, so entering them
    risks a position that is hard to get out of."""

    __tablename__ = "trading_restrictions"
    __table_args__ = (UniqueConstraint("symbol", "kind", "as_of", name="uq_trading_restriction"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(8))  # ASM | GSM
    stage: Mapped[str] = mapped_column(String(64), default="")
    as_of: Mapped[date] = mapped_column(Date, index=True)
