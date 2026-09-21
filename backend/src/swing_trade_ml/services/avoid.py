"""Reasons to stay out of a stock today, however good the setup looks.

An expert avoids landmines before looking at charts: a results announcement is
a coin-flip gap the stop cannot protect against, a stock on NSE's surveillance
lists can be hard to sell, and one in trade-for-trade cannot be squared off.
Each is a plain rule with a plain-English reason, so a refused trade explains
itself.

Fail-open on missing data: a feed that has not loaded must not silently veto
every trade. Feed health is monitored (a missing day raises a Telegram alert),
which is the right place to catch a stale source.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.db.models.feeds import DailyDelivery, TradingRestriction, UpcomingEvent

#: How far ahead a results announcement counts as too close to enter.
RESULTS_BLACKOUT_DAYS = 3
#: How far ahead a split / bonus / rights issue counts.
CORPORATE_ACTION_BLACKOUT_DAYS = 2
#: A restriction list older than this is treated as unknown, not as "clear".
RESTRICTION_MAX_AGE_DAYS = 4


def avoid_reason(db: Session, symbol: str, today: date) -> str | None:
    restricted = db.execute(
        select(TradingRestriction.kind, TradingRestriction.stage)
        .where(
            TradingRestriction.symbol == symbol,
            TradingRestriction.as_of >= today - timedelta(days=RESTRICTION_MAX_AGE_DAYS),
        )
        .order_by(TradingRestriction.as_of.desc())
        .limit(1)
    ).first()
    if restricted:
        return (
            f"The exchange has put {symbol} on its extra-watch list "
            f"({restricted.kind}, {restricted.stage}). Trading in it can be restricted, "
            "so it may be hard to sell."
        )

    latest_series = db.execute(
        select(DailyDelivery.series)
        .where(DailyDelivery.symbol == symbol, DailyDelivery.trade_date >= today - timedelta(days=5))
        .order_by(DailyDelivery.trade_date.desc())
        .limit(1)
    ).scalar_one_or_none()
    if latest_series in ("BE", "BZ"):
        return f"{symbol} is in delivery-only trading right now, which limits how it can be sold."

    results = db.execute(
        select(UpcomingEvent.event_date)
        .where(
            UpcomingEvent.symbol == symbol,
            UpcomingEvent.kind == "results",
            UpcomingEvent.event_date >= today,
            UpcomingEvent.event_date <= today + timedelta(days=RESULTS_BLACKOUT_DAYS),
        )
        .order_by(UpcomingEvent.event_date)
        .limit(1)
    ).scalar_one_or_none()
    if results:
        return (
            f"{symbol} announces its results on {results:%d %b}. The price can jump either "
            "way on the news, past any stop-loss."
        )

    action = db.execute(
        select(UpcomingEvent.event_date, UpcomingEvent.detail)
        .where(
            UpcomingEvent.symbol == symbol,
            UpcomingEvent.kind == "corporate_action",
            UpcomingEvent.event_date >= today,
            UpcomingEvent.event_date <= today + timedelta(days=CORPORATE_ACTION_BLACKOUT_DAYS),
        )
        .order_by(UpcomingEvent.event_date)
        .limit(1)
    ).first()
    if action:
        return (
            f"{symbol} has a corporate action on {action.event_date:%d %b} ({action.detail}) "
            "that resets its share price."
        )
    return None
