"""Personal finance domain: imported bank/UPI statements and their transactions.

Unrelated to the trading engine — this is a personal expense tracker bolted
onto the same app so it shares infrastructure (Postgres, auth, deployment)
instead of running as a second service. `FinanceTransaction.category` is
mutated in place on manual recategorization (see `is_manual_override`), the
same way the rest of this codebase updates rows rather than layering an
override table on top.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from swing_trade_ml.core.enums import FinanceIngestStatus
from swing_trade_ml.db.base import Base, TimestampMixin


class FinanceIngestedFile(Base, TimestampMixin):
    """One row per successfully imported statement — the whole-file dedup ledger.

    Only written after a successful parse+categorize+insert, so a failed
    upload (wrong password, unparseable PDF) never blocks retrying the same
    file under the same hash.
    """

    __tablename__ = "finance_ingested_files"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    file_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    file_name: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(16), index=True)
    status: Mapped[str] = mapped_column(String(16), default=FinanceIngestStatus.SUCCESS)
    transaction_count: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<FinanceIngestedFile {self.file_name} ({self.transaction_count} txns)>"


class FinanceTransaction(Base, TimestampMixin):
    """A single categorized transaction parsed from an uploaded statement.

    `dedup_key` is the practical identity of a transaction across re-uploads
    of the same or overlapping statements: `transaction_id` when the source
    provided one, else a composite of date/description/amount/source. Re-
    importing a statement is a no-op via the unique constraint on this
    column, which is what lets a manual recategorization survive a re-upload
    without a separate overlay table.
    """

    __tablename__ = "finance_transactions"
    __table_args__ = (Index("ix_finance_transactions_month_category", "month", "category"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ingested_file_id: Mapped[int | None] = mapped_column(
        ForeignKey("finance_ingested_files.id", ondelete="CASCADE"), index=True
    )

    dedup_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    txn_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    month: Mapped[str] = mapped_column(String(7), index=True)
    description: Mapped[str] = mapped_column(Text)
    amount: Mapped[float] = mapped_column(Float)
    direction: Mapped[str] = mapped_column(String(8), index=True)
    status: Mapped[str | None] = mapped_column(String(16))
    transaction_id: Mapped[str | None] = mapped_column(String(128), index=True)
    source: Mapped[str | None] = mapped_column(String(32))
    raw_text: Mapped[str | None] = mapped_column(Text)

    category: Mapped[str] = mapped_column(String(64), default="Uncategorised", index=True)
    is_manual_override: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<FinanceTransaction {self.txn_date:%Y-%m-%d} {self.description[:30]!r} {self.amount}>"
