"""A person's saved Discover filters (#310, slice A).

Settings only: a name and the filters (time window, company size, pattern, word, sector, search text, layout,
watchlist-only). It stores no result, score, price or trade instruction, and nothing in trading reads it.
One row per screen, owned by one person (`user_id`, deleted with the account). Names are unique per person,
ignoring upper/lower case.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from swing_trade_ml.db.base import Base, TimestampMixin


class SavedScreen(Base, TimestampMixin):
    __tablename__ = "saved_screens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    # The filters, as validated by services/saved_screens.py::ScreenSpec.
    spec: Mapped[dict] = mapped_column(JSONB)
    # So old saved screens can still be read after the filters change.
    filters_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    __table_args__ = (Index("uq_saved_screens_user_name", "user_id", func.lower(name), unique=True),)
