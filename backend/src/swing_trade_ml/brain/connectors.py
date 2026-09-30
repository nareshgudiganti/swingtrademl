"""The data sources the brain checks for freshness, besides prices.

This is the connector contract from the build book, kept as small as it can
be: a source has a plain name and a way to ask "what is the newest day you
have, up to this moment?". Adding a new source (a licensed news feed, say)
means adding one entry here; no brain step changes. Fetching and storing stay
with v1's ingestion jobs.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from swing_trade_ml.db.models.feeds import BlockDeal, DailyDelivery, InstitutionalFlow


@dataclass(frozen=True, slots=True)
class FeedSource:
    name: str
    latest: Callable[[Session, date], date | None]  # newest day on or before the given day


def _latest(column) -> Callable[[Session, date], date | None]:
    def query(db: Session, upto: date) -> date | None:
        return db.execute(select(func.max(column)).where(column <= upto)).scalar_one_or_none()

    return query


FEEDS: tuple[FeedSource, ...] = (
    FeedSource("delivery", _latest(DailyDelivery.trade_date)),
    FeedSource("bulk and block deals", _latest(BlockDeal.trade_date)),
    FeedSource("FII/DII flows", _latest(InstitutionalFlow.trade_date)),
)
