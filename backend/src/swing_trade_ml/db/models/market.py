"""Market data: the instrument master, historical/live candles, and live quotes."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from swing_trade_ml.db.base import Base, TimestampMixin


class Instrument(Base, TimestampMixin):
    """One tradable symbol, synced from Kite's instrument dump.

    `instrument_token` is Kite's numeric id and the key every market-data API
    call needs — the human-readable `tradingsymbol` is not accepted there.
    """

    __tablename__ = "instruments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_token: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    exchange_token: Mapped[int | None] = mapped_column(BigInteger)
    tradingsymbol: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    exchange: Mapped[str] = mapped_column(String(16), default="NSE", index=True)
    segment: Mapped[str | None] = mapped_column(String(32))
    instrument_type: Mapped[str | None] = mapped_column(String(16))  # EQ, FUT, CE, PE
    lot_size: Mapped[int] = mapped_column(Integer, default=1)
    tick_size: Mapped[float] = mapped_column(Float, default=0.05)
    expiry: Mapped[date | None] = mapped_column(Date)

    # Only watchlisted instruments get candles ingested — the full NSE dump is
    # ~2000 equities and backfilling all of them would blow the Kite rate limit.
    is_watchlisted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    candles: Mapped[list[Candle]] = relationship(back_populates="instrument")

    __table_args__ = (
        UniqueConstraint("exchange", "tradingsymbol", name="uq_instruments_exchange_symbol"),
    )

    @property
    def symbol_key(self) -> str:
        """The `EXCHANGE:SYMBOL` form Kite's quote/LTP endpoints expect."""
        return f"{self.exchange}:{self.tradingsymbol}"

    def __repr__(self) -> str:
        return f"<Instrument {self.exchange}:{self.tradingsymbol}>"


class Candle(Base):
    """OHLCV bar. Holds both the historical backfill and live-appended bars.

    This is the largest table by far — a TimescaleDB hypertable partitioned on
    `ts` (see the initial migration).

    The primary key is the natural key `(instrument_id, interval, ts)` rather
    than a surrogate id. Three reasons, in order of importance:

    1. TimescaleDB requires the partitioning column to appear in every unique
       index. A PK on a bare `id` makes the table impossible to promote to a
       hypertable at all.
    2. It is genuinely unique — one bar per instrument per interval per
       timestamp — and nothing foreign-keys to candles, so a surrogate key
       would buy nothing.
    3. It doubles as the index for the dominant read ("last N bars of one
       interval for one instrument") and removes a bigserial sequence from the
       hottest insert path in the system.

    No TimestampMixin either: an immutable bar has no meaningful updated_at,
    and two extra timestamptz columns across tens of millions of rows is real
    storage.
    """

    __tablename__ = "candles"

    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instruments.id", ondelete="CASCADE"), primary_key=True
    )
    # Text rather than varchar: TimescaleDB recommends it for segment-by style
    # columns, and there is no length constraint worth enforcing here.
    interval: Mapped[str] = mapped_column(Text, primary_key=True, default="day")
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)

    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[int] = mapped_column(BigInteger, default=0)

    instrument: Mapped[Instrument] = relationship(back_populates="candles")

    # Chunk exclusion needs a plain `ts` index for time-range scans that are not
    # scoped to one instrument (for example the daily ingestion watermark).
    __table_args__ = (Index("ix_candles_ts", "ts"),)

    def __repr__(self) -> str:
        return f"<Candle {self.instrument_id} {self.interval} {self.ts} c={self.close}>"


class Quote(Base):
    """Latest polled snapshot per instrument — one row each, updated in place.

    Kept separate from `candles` so "what is it trading at right now" is a
    single-row primary-key read rather than an ordered scan of a huge table.
    """

    __tablename__ = "quotes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instruments.id", ondelete="CASCADE"), unique=True, index=True
    )

    last_price: Mapped[float] = mapped_column(Float)
    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float | None] = mapped_column(Float)  # previous day's close
    volume: Mapped[int | None] = mapped_column(BigInteger)
    change_pct: Mapped[float | None] = mapped_column(Float)

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    instrument: Mapped[Instrument] = relationship()

    def __repr__(self) -> str:
        return f"<Quote {self.instrument_id} ltp={self.last_price}>"
