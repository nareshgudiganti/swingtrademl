"""Which securities exist (#389): the one read that lists them all, for consumers that walk every stock.

Read-only. `all_security_ids` answers "every `security_id` there is, in order", so a reader that needs to look at each
stock (the research simulation reading horizon records) asks the identity package instead of reading its tables.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.db.models.identity import Security


def all_security_ids(db: Session) -> list[int]:
    """Every permanent security id, ascending. Never writes."""
    return list(db.scalars(select(Security.id).order_by(Security.id)))
