"""Mutual fund tracking: scheme master, NAV history, and the user's own
holdings. Unrelated to the trading engine, same as db/models/finance.py —
personal net-worth data sharing this app's infrastructure.

Data source is AMFI's own public NAVAll.txt disclosure (see
services/finance/mutual_funds.py) — the fund industry's own regulator-
mandated publication, not a scrape of a third party's page.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import (
    Boolean,
    Date,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from swing_trade_ml.db.base import Base, TimestampMixin


class MutualFund(Base, TimestampMixin):
    """One AMFI scheme. The full AMFI universe (~10,000 schemes) is stored
    here for search, but only is_tracked=True schemes get NAV history
    synced — see services/finance/mutual_funds.py::sync_nav_snapshot."""

    __tablename__ = "mutual_funds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scheme_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    amc_name: Mapped[str | None] = mapped_column(String(128))
    # AMFI's own category labels run longer than this app's internal finance
    # taxonomy (db/models/finance.py's category columns are String(64)) — e.g.
    # "Fund of Funds Scheme (Domestic) - Fund of Funds Scheme (Domestic)" is
    # 65 chars, confirmed against a live NAVAll.txt pull. 128 leaves headroom.
    category: Mapped[str | None] = mapped_column(String(128))
    is_tracked: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    navs: Mapped[list["MutualFundNav"]] = relationship(back_populates="scheme")
    holdings: Mapped[list["MutualFundHolding"]] = relationship(back_populates="scheme")


class MutualFundNav(Base):
    """One NAV observation. No surrogate id and no TimestampMixin, same
    reasoning as db/models/market.py::Candle — one row per scheme per date
    is the natural key, nothing foreign-keys to an individual NAV row, and
    this table is large enough that two extra timestamptz columns matter."""

    __tablename__ = "mutual_fund_navs"
    __table_args__ = (UniqueConstraint("scheme_id", "date", name="uq_mf_nav_scheme_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scheme_id: Mapped[int] = mapped_column(ForeignKey("mutual_funds.id", ondelete="CASCADE"), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    nav: Mapped[float] = mapped_column(Float)

    scheme: Mapped[MutualFund] = relationship(back_populates="navs")


class MutualFundHolding(Base, TimestampMixin):
    """One purchase lot. Multiple lots per scheme are allowed — average
    cost is computed at read time (services/finance/mutual_funds.py), never
    stored, matching FinanceLoan's "compute fresh, never persist" pattern."""

    __tablename__ = "mutual_fund_holdings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scheme_id: Mapped[int] = mapped_column(ForeignKey("mutual_funds.id", ondelete="CASCADE"), index=True)
    units: Mapped[float] = mapped_column(Float)
    purchase_nav: Mapped[float] = mapped_column(Float)
    purchase_date: Mapped[date] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)

    scheme: Mapped[MutualFund] = relationship(back_populates="holdings")
