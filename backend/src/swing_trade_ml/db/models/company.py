"""What a company itself has filed with the exchange (the Company and news tab).

Display only: nothing here feeds a pick, order, stop, size or limit. Every row keeps the
source and the date the company filed it, so a later restatement can never rewrite what
was public on an earlier day.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Float, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from swing_trade_ml.db.base import Base, TimestampMixin


class CompanyAnnouncement(Base, TimestampMixin):
    """One corporate announcement. `seq_id` is the exchange's own id, so reloading is a no-op;
    `created_at` is when we collected it."""

    __tablename__ = "company_filing_announcements"
    __table_args__ = (UniqueConstraint("source", "seq_id", name="uq_company_filing_announcement"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(16), default="nse")
    seq_id: Mapped[str] = mapped_column(String(40))
    announced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    category: Mapped[str] = mapped_column(String(160), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    attachment_url: Mapped[str | None] = mapped_column(String(400))


class CompanyShareholding(Base, TimestampMixin):
    """Who owns the company at a quarter end (promoters against everyone else), as filed on
    `filed_on`. Only a filing that adds up to 100% is stored."""

    __tablename__ = "company_filing_shareholdings"
    __table_args__ = (UniqueConstraint("symbol", "source", "as_of", name="uq_company_filing_shareholding"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(16), default="nse")
    as_of: Mapped[date] = mapped_column(Date, index=True)
    filed_on: Mapped[date] = mapped_column(Date)
    promoter_pct: Mapped[float] = mapped_column(Float)
    public_pct: Mapped[float] = mapped_column(Float)
