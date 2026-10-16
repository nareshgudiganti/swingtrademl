"""Read-only helpers that turn trade plans into beginner-friendly numbers.

`money_at_stake` is pure; the event helpers below only read the database.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.brain.modules.m13_news.calendar import trading_days_until
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import PositionStatus, TradingMode
from swing_trade_ml.db.models.feeds import UpcomingEvent
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Position
from swing_trade_ml.services.costs import compute_charges
from swing_trade_ml.services.portfolio import exclude_hand_books, exclude_real_trading


def _charges(turnover: float, side: str) -> float:
    brokerage, taxes = compute_charges(turnover, side)
    return brokerage + taxes


def _unavailable(why: str) -> dict:
    return {
        "available": False,
        "why": why,
        "invested": 0.0,
        "loss_if_stop": 0.0,
        "gain_if_target": 0.0,
        "gain_if_half_out": 0.0,
        "charges_round_trip": 0.0,
    }


def money_at_stake(
    entry: float | None,
    stop: float | None,
    target: float | None,
    qty: int,
) -> dict:
    """Rupees at stake for a plan, after real charges.

    `loss_if_stop` and `gain_if_target` are net of the buy leg plus the sell
    leg at their own exit price. `charges_round_trip` is the buy leg plus the
    sell leg at the TARGET price. `gain_if_half_out` sells qty // 2 at
    entry * (1 + ML_FIRST_TARGET_PCT) and the rest at target, each sell leg
    paying its own charges (including the flat depository fee).
    """
    if qty is None or qty <= 0:
        return _unavailable("No shares allowed")
    if entry is None or stop is None or target is None or stop >= entry or target <= entry:
        return _unavailable("Plan incomplete")

    invested = qty * entry
    buy = _charges(invested, "BUY")
    sell_stop = _charges(qty * stop, "SELL")
    sell_target = _charges(qty * target, "SELL")

    loss = (entry - stop) * qty + buy + sell_stop
    gain = (target - entry) * qty - buy - sell_target

    first_qty = qty // 2
    rest_qty = qty - first_qty
    first_price = entry * (1 + settings.ML_FIRST_TARGET_PCT)
    half = (first_price - entry) * first_qty + (target - entry) * rest_qty - buy
    if first_qty > 0:
        half -= _charges(first_qty * first_price, "SELL")
    half -= _charges(rest_qty * target, "SELL")

    return {
        "available": True,
        "why": None,
        "invested": round(invested, 2),
        "loss_if_stop": round(loss, 2),
        "gain_if_target": round(gain, 2),
        "gain_if_half_out": round(half, 2),
        "charges_round_trip": round(buy + sell_target, 2),
    }


# ---------------------------------------------------------------------------
# Upcoming events (bx8) — read-only
# ---------------------------------------------------------------------------


def _event_plain(kind: str, detail: str, day: date, days_away: int) -> str:
    """One plain-English line for an upcoming event."""
    if kind == "results":
        when = "today" if days_away == 0 else "tomorrow" if days_away == 1 else f"in {days_away} trading days"
        return f"Results {when} — prices can jump either way"
    return f"{detail or 'Corporate action'} on {day.day} {day:%b}"


def watchlist_symbols(db: Session) -> list[str]:
    rows = db.scalars(select(Instrument.tradingsymbol).where(Instrument.is_watchlisted.is_(True)).distinct())
    return sorted(rows)


def held_symbols(db: Session) -> list[str]:
    """Open PAPER positions of the bot's own book (no My Holdings, no tester)."""
    rows = db.scalars(
        select(Instrument.tradingsymbol)
        .join(Position, Position.instrument_id == Instrument.id)
        .where(
            Position.status == PositionStatus.OPEN,
            Position.mode == TradingMode.PAPER,
            exclude_real_trading(Position.strategy_id),
            exclude_hand_books(Position.strategy_id),
        )
        .distinct()
    )
    return sorted(rows)


def upcoming_events(
    db: Session, symbols: list[str] | None, today: date, trading_days: int = 15
) -> list[dict]:
    """Results and corporate actions within `trading_days` trading days.

    `symbols=None` means every stock; an empty list means none. Days are
    counted on the market calendar (weekends and holidays do not count).
    """
    if symbols is not None and not symbols:
        return []
    stmt = select(UpcomingEvent).where(UpcomingEvent.event_date >= today)
    if symbols is not None:
        stmt = stmt.where(UpcomingEvent.symbol.in_(symbols))
    out = []
    for ev in db.scalars(stmt):
        away = trading_days_until(today, ev.event_date)
        if not 0 <= away <= trading_days:
            continue
        out.append(
            {
                "symbol": ev.symbol,
                "kind": ev.kind,
                "date": ev.event_date.isoformat(),
                "trading_days_away": away,
                "detail": ev.detail or "",
                "plain": _event_plain(ev.kind, ev.detail or "", ev.event_date, away),
            }
        )
    out.sort(key=lambda r: (r["date"], r["symbol"]))
    return out
