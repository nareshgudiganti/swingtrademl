"""A person's request to delete their account: asked -> confirmed by email -> grace period -> done.

One row per request. At most one OPEN request (pending or scheduled) per person. The row holds no
personal data. See services/account_deletion.py and docs/RETENTION.md.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from swing_trade_ml.db.base import Base

#: pending = asked, waiting for the email link. scheduled = confirmed, in the grace period (sign-in blocked).
#: cancelled = the person (or a safety check) stopped it. completed = personal data removed.
DELETION_STATUSES = ("pending", "scheduled", "cancelled", "completed")


class AccountDeletion(Base):
    __tablename__ = "account_deletions"
    __table_args__ = (
        Index(
            "uq_account_deletions_one_open",
            "user_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'scheduled')"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(12), default="pending", server_default="pending")
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Why a request was stopped by a safety check, e.g. "protected_account". Never personal data.
    note: Mapped[str | None] = mapped_column(String(64))
