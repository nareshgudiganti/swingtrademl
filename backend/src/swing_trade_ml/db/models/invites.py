"""Invite requests: people ask for a place, the owner approves or rejects in Admin,
and only an approved request (with its one-time invite code) can create an account.
See endpoints/invites.py and endpoints/auth.py signup."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from swing_trade_ml.db.base import Base

#: pending -> approved | rejected. An approved invite can still be rejected (withdrawn) until it is used.
INVITE_STATUSES = ("pending", "approved", "rejected")
EXPERIENCE_LEVELS = ("just_starting", "now_and_then", "every_week")
LANGUAGES = ("english", "telugu")


class InviteRequest(Base):
    __tablename__ = "invite_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    # Always lower-cased by the API before it is stored or compared.
    email: Mapped[str] = mapped_column(String(254), index=True)
    phone: Mapped[str | None] = mapped_column(String(20))
    experience: Mapped[str] = mapped_column(String(16))
    language: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(12), default="pending", server_default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Username of the owner who approved/rejected, taken from their sign-in, never from the request body.
    decided_by: Mapped[str | None] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(String(500))
    # sha256 of the one-time invite code; the code itself is shown to the owner once, never stored.
    code_hash: Mapped[str | None] = mapped_column(String(64))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    __table_args__ = (
        # One open request per email: a second ask while the first waits is not stored.
        Index(
            "uq_invite_requests_pending_email",
            "email",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    def __repr__(self) -> str:
        return f"<InviteRequest {self.id} {self.status}>"
