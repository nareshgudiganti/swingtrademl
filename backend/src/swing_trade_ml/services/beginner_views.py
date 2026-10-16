"""Read-only helpers that turn trade plans into beginner-friendly numbers.

`money_at_stake` is pure; the event helpers below only read the database.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.brain.modules.m13_news.calendar import trading_days_until
from swing_trade_ml.brain.trial_journal import TRIAL_START as BRAIN_TRIAL_START
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import PositionStatus, TradingMode
from swing_trade_ml.core.market_session import IST
from swing_trade_ml.db.models.feeds import UpcomingEvent
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.trading import Position
from swing_trade_ml.services.brain_golive.compare import NEEDED_FINISHED, finished_brain_ideas
from swing_trade_ml.services.costs import compute_charges
from swing_trade_ml.services.portfolio import (
    exclude_hand_books,
    exclude_real_trading,
    performance_stats,
    trial_start,
)


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


# ---- bx4: evidence summary -------------------------------------------------

PAPER_LABEL = "Practice money (paper)"
ENOUGH_TRADES = 30
FEW_TRADES_NOTE = "Too few finished trades to judge — this could be luck."
SEALED_NOTE = "Results stay hidden until the planned review so the test stays fair."


def period_change_pct(db: Session, instrument_ids: list[int], since: datetime) -> float | None:
    """Equal-weight mean % change of daily closes, from the first stored day on/after `since`
    to the latest stored day. Only instruments with a candle on BOTH of those days count.
    None when there is no data or the period is a single day, never 0 as a guess."""
    if not instrument_ids:
        return None
    rows = db.execute(
        select(Candle.instrument_id, Candle.ts, Candle.close).where(
            Candle.instrument_id.in_(instrument_ids), Candle.interval == "day", Candle.ts >= since
        )
    ).all()
    closes: dict[int, dict[date, float]] = {}
    for iid, ts, close in rows:
        closes.setdefault(iid, {})[ts.astimezone(IST).date()] = close
    days = {d for per in closes.values() for d in per}
    if len(days) < 2:
        return None
    first, last = min(days), max(days)
    changes = [
        (per[last] / per[first] - 1) * 100
        for per in closes.values()
        if first in per and last in per and per[first]
    ]
    return round(sum(changes) / len(changes), 2) if changes else None


def evidence_summary(db: Session) -> dict:
    """Plain-figure summary of the v1 paper bot since the trial began, plus a SEALED brain-trial
    count. No brain win rate, profit or comparison is ever returned here."""
    stats = performance_stats(db, mode=TradingMode.PAPER, bot_book_only=True)
    since = trial_start(TradingMode.PAPER)
    finished = int(stats["total_trades"])
    enough = finished >= ENOUGH_TRADES

    nifty = every = None
    if since is not None:
        nifty_ids = list(
            db.scalars(
                select(Instrument.id).where(Instrument.tradingsymbol == settings.BENCHMARK_INDEX_SYMBOL)
            )
        )
        watch_ids = list(db.scalars(select(Instrument.id).where(Instrument.is_watchlisted.is_(True))))
        nifty = period_change_pct(db, nifty_ids, since)
        every = period_change_pct(db, watch_ids, since)

    return {
        "paper_label": PAPER_LABEL,
        "bot": {
            "since": since.date().isoformat() if since else None,
            "profit_booked": stats["realized_pnl"],
            "profit_open": stats["unrealized_pnl"],
            "costs_paid": stats["total_charges"],
            "worst_fall_from_peak_pct": round(stats["max_drawdown_pct"] * 100, 2),
            "finished_trades": finished,
            "win_rate_pct": round(stats["win_rate"] * 100, 1) if finished else None,
            "nifty_same_period_pct": nifty,
            "every_stock_same_period_pct": every,
            "enough_trades": enough,
            "note": "" if enough else FEW_TRADES_NOTE,
        },
        "brain_trial": {
            "since": BRAIN_TRIAL_START.isoformat(),
            "finished": finished_brain_ideas(db),
            "needed": NEEDED_FINISHED,
            "sealed": True,
            "sealed_note": SEALED_NOTE,
        },
    }
