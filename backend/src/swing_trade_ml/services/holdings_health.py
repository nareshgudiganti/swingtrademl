"""Holdings health check: plain-English warnings about what one book holds right now.

Read-only, display only. Nothing here places, changes or cancels an order, a
stop, a size or a limit, and nothing is written anywhere: it only reads the
open positions of ONE book and says, in plain words, where they break the
settled rules. Books are never added together — paper and real money are
different accounts, and the real (My Holdings) book is private to the people
in REAL_ACCOUNT_USERS (the endpoint applies the same `book_for` guard as every
other portfolio read).

Every number comes from the code that already enforces it, never from here:

* one stock / one sector  -> services/limits.py `limits_for(account value)`:
  the capital ladder (₹10K one stock per sector; from ₹1L a 25% sector cap;
  the single-stock cap shrinks as the account grows, and a strategy's own
  `capital_allocation` override wins, exactly as on the entry path);
* stop-loss distance      -> settings.ML_STOP_RETURN_PCT (the agreed -4%);
* how long a trade runs   -> settings.ML_PREDICTION_HORIZON_DAYS (15 trading days).
  v1's own time stop is 30 *calendar* days, which is about the same length —
  that is correct and is not reported as a fault;
* results day             -> the `upcoming_events` table the morning feed fills
  (the same data services/avoid.py uses to skip a stock before its results).

`check()` is pure (tested at every boundary); `health_for_book()` only gathers
its inputs.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import PositionStatus, TradingMode
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.core.market_session import IST, is_trading_day, next_trading_day
from swing_trade_ml.services.limits import Limits, format_inr, limits_for

log = get_logger(__name__)

#: The settled plan: every trade is done within this many trading days.
PLAN_TRADING_DAYS = settings.ML_PREDICTION_HORIZON_DAYS

#: A stop this little further than the agreed one is not a problem: a buy can
#: fill a touch above the signal price the stop was worked out from, and prices
#: are rounded to the paisa. A quarter of a percentage point covers both.
STOP_SLACK = 0.0025

#: Small float tolerance so "exactly at the limit" never reads as over it.
_EPS = 1e-9


@dataclass(frozen=True, slots=True)
class Holding:
    """One open position, reduced to what the rules need."""

    symbol: str
    value: float  # what it is worth now
    entry_price: float
    stop_loss: float | None
    day: int  # which trading day of the trade today is
    max_position_pct: float  # the single-stock cap that applies to it
    sector: str | None  # sector bucket; None = not in the sector map
    sector_name: str | None
    results_on: date | None  # results date inside the holding window, if any


@dataclass(frozen=True, slots=True)
class Issue:
    kind: str
    symbols: tuple[str, ...]
    title: str  # one short plain sentence
    detail: str  # the numbers and the rule, shown on tap


def _pct(x: float) -> str:
    """0.25 -> "25%", 0.101 -> "10.1%" (no trailing ".0")."""
    s = f"{x * 100:.1f}"
    return (s[:-2] if s.endswith(".0") else s) + "%"


def check(
    holdings: list[Holding],
    account_value: float,
    limits: Limits,
    *,
    stop_pct: float | None = None,
    plan_days: int = PLAN_TRADING_DAYS,
) -> list[Issue]:
    """Every rule the holdings break, most urgent first. Pure."""
    stop_pct = settings.ML_STOP_RETURN_PCT if stop_pct is None else stop_pct
    if not holdings:
        return []
    held_total = sum(h.value for h in holdings)
    # An unreadable account value must not hide a problem: measure against what
    # is held instead, which can only make each share look bigger (more caution).
    base = account_value if account_value and account_value > 0 else held_total
    if base <= 0:
        base = 1.0

    stops: list[Issue] = []
    sizes: list[Issue] = []
    results: list[Issue] = []
    late: list[Issue] = []

    for h in holdings:
        # ---- stop-loss ----
        if h.stop_loss is None or h.stop_loss <= 0:
            stops.append(
                Issue(
                    "no_stop",
                    (h.symbol,),
                    f"{h.symbol} has no stop-loss.",
                    f"Nothing will sell {h.symbol} automatically if it keeps falling. The agreed plan is a "
                    f"stop-loss {_pct(stop_pct)} below the price paid.",
                )
            )
        elif h.entry_price > 0:
            distance = 1 - h.stop_loss / h.entry_price
            if distance > stop_pct + STOP_SLACK + _EPS:
                stops.append(
                    Issue(
                        "stop_too_far",
                        (h.symbol,),
                        f"{h.symbol}'s stop-loss is further away than agreed.",
                        f"The stop-loss is at ₹{h.stop_loss:,.2f}, {_pct(distance)} below the "
                        f"₹{h.entry_price:,.2f} paid. The agreed stop is {_pct(stop_pct)} below, "
                        "so this stock can lose more "
                        "than planned before it is sold.",
                    )
                )

        # ---- one stock too big ----
        share = h.value / base
        if share > h.max_position_pct + _EPS:
            sizes.append(
                Issue(
                    "stock_too_big",
                    (h.symbol,),
                    f"Too much money is in {h.symbol}.",
                    f"{h.symbol} is {_pct(share)} of this account ({format_inr(h.value)} of "
                    f"{format_inr(base)}). The rule for an account this size is at most "
                    f"{_pct(h.max_position_pct)} in one stock, so one bad day for it hurts more "
                    "than planned.",
                )
            )

        # ---- results day ----
        if h.results_on is not None:
            results.append(
                Issue(
                    "results_soon",
                    (h.symbol,),
                    f"{h.symbol} announces its results on {h.results_on:%d %b}.",
                    f"That is before this trade's {plan_days}-trading-day plan ends. A share price can jump "
                    "up or down on results day, and a big jump can go straight past the stop-loss.",
                )
            )

        # ---- held past the plan ----
        if h.day > plan_days:
            late.append(
                Issue(
                    "past_plan",
                    (h.symbol,),
                    f"{h.symbol} is on day {h.day} of a {plan_days}-day plan.",
                    f"Trades are meant to be finished within {plan_days} trading days. The bot's own safety "
                    "sell happens after 30 calendar days, which is about the same length, so this is a "
                    "reminder to review it, not a fault.",
                )
            )

    # ---- sectors (unmapped stocks are never grouped together) ----
    by_sector: dict[str, list[Holding]] = defaultdict(list)
    for h in holdings:
        if h.sector:
            by_sector[h.sector].append(h)
    for group in by_sector.values():
        name = group[0].sector_name or group[0].sector or ""
        symbols = tuple(h.symbol for h in group)
        if limits.sector_rule == "one_per_sector":
            if len(group) > 1:
                sizes.append(
                    Issue(
                        "two_in_one_sector",
                        symbols,
                        f"{len(group)} stocks in {name}: {', '.join(symbols)}.",
                        f"At this account size the rule is one stock per sector, so one bad day for "
                        f"{name} does not hit several holdings at once.",
                    )
                )
        elif limits.sector_cap_pct is not None:
            total = sum(h.value for h in group)
            share = total / base
            if share > limits.sector_cap_pct + _EPS:
                sizes.append(
                    Issue(
                        "sector_too_big",
                        symbols,
                        f"Too much money is in {name}.",
                        f"{name} ({', '.join(symbols)}) is {_pct(share)} of this account "
                        f"({format_inr(total)}). "
                        f"The rule is at most {_pct(limits.sector_cap_pct)} in one sector, so one bad day "
                        f"for {name} hurts more than planned.",
                    )
                )

    return stops + sizes + results + late


# --------------------------------------------------------------------------
# Gathering the inputs for one book (reads only).
# --------------------------------------------------------------------------

BOOK_LABELS = {
    "bot": "Bot (Paper)",
    "tester": "Testing (Paper)",
    "real": "My Zerodha (Real)",
}


def plan_last_day(entry_at: datetime) -> date:
    """The 15th trading day of a trade (day 1 = the entry day, or the next trading day)."""
    d = entry_at.astimezone(IST).date()
    if not is_trading_day(d):
        d = next_trading_day(d)
    for _ in range(PLAN_TRADING_DAYS - 1):
        d = next_trading_day(d)
    return d


def _book_positions(db: Session, book: str) -> list[Any]:
    from swing_trade_ml.brokers import get_broker
    from swing_trade_ml.db.models.market import Instrument
    from swing_trade_ml.db.models.trading import Position, Strategy
    from swing_trade_ml.services import portfolio as portfolio_service
    from swing_trade_ml.services.tester_paper import only_tester

    stmt = (
        select(Position, Instrument.tradingsymbol)
        .join(Instrument, Instrument.id == Position.instrument_id)
        .where(Position.status == PositionStatus.OPEN)
    )
    if book == "real":
        stmt = stmt.where(
            Position.mode == TradingMode.LIVE,
            Position.strategy_id.in_(
                select(Strategy.id).where(Strategy.name == portfolio_service.REAL_TRADING_STRATEGY_NAME)
            ),
        )
    elif book == "tester":
        stmt = stmt.where(Position.mode == TradingMode.PAPER, only_tester(Position.strategy_id))
    else:
        stmt = stmt.where(
            Position.mode == get_broker().mode, portfolio_service.exclude_hand_books(Position.strategy_id)
        )
    return list(db.execute(stmt).all())


def _account_value(db: Session, book: str, held_value: float) -> tuple[float, str]:
    """(account value, how it was measured — in plain words)."""
    if book == "tester":
        from swing_trade_ml.services import tester_paper

        return tester_paper.portfolio_value(db)[0], "Testing practice money: shares held plus cash left"
    if book == "bot":
        from swing_trade_ml.brokers import get_broker
        from swing_trade_ml.services.portfolio import portfolio_value_and_cash

        value, _cash = portfolio_value_and_cash(db, get_broker().mode, bot_book_only=True)
        return value, "The bot's account: shares held plus cash left"
    # Real: the tracked My Holdings shares plus Zerodha cash, if a Kite session is
    # already loaded. Never logs in; a missing session just leaves cash out.
    cash = 0.0
    try:
        from swing_trade_ml.brokers.kite import kite_broker

        kite_broker.load_session(db)
        if kite_broker.is_authenticated:
            cash = float(kite_broker.get_margins(db).available_cash)
    except Exception as exc:  # noqa: BLE001 - display only; fall back to shares alone
        log.info("holdings_health.real_cash_unavailable", error=str(exc))
        cash = 0.0
    if cash > 0:
        return held_value + cash, "My Holdings shares plus the cash in Zerodha"
    return held_value, (
        "My Holdings shares only — Zerodha's cash balance could not be read, so each share looks "
        "a little bigger than it is"
    )


def _results_dates(db: Session, windows: dict[str, tuple[date, date]]) -> tuple[dict[str, date], bool]:
    """symbol -> first results date in its window; and whether the calendar has data at all."""
    from swing_trade_ml.db.models.feeds import UpcomingEvent

    today = datetime.now(IST).date()
    loaded = (
        db.execute(
            select(UpcomingEvent.id)
            .where(UpcomingEvent.kind == "results", UpcomingEvent.event_date >= today)
            .limit(1)
        ).first()
        is not None
    )
    if not loaded or not windows:
        return {}, loaded
    found: dict[str, date] = {}
    for symbol, event_date in db.execute(
        select(UpcomingEvent.symbol, UpcomingEvent.event_date)
        .where(UpcomingEvent.kind == "results", UpcomingEvent.symbol.in_(list(windows)))
        .order_by(UpcomingEvent.event_date)
    ):
        start, end = windows[symbol]
        if start <= event_date <= end and symbol not in found:
            found[symbol] = event_date
    return found, loaded


def health_for_book(db: Session, book: str) -> dict[str, Any]:
    """The health card for one book. Reads only; never commits."""
    from swing_trade_ml.ml.sector_map import get_sector_bucket, sector_display_name
    from swing_trade_ml.services.avoid import RESULTS_BLACKOUT_DAYS
    from swing_trade_ml.services.held_read import day_number

    rows = _book_positions(db, book)
    today = datetime.now(IST).date()
    held_value = sum((p.current_price or p.entry_price) * p.quantity for p, _ in rows)
    account_value, basis = _account_value(db, book, held_value)
    base = account_value if account_value > 0 else held_value
    limits = limits_for(base)

    # Results that land before the trade's plan ends — or within the next few
    # days for a trade already past it (the same window avoid.py uses).
    windows = {
        symbol: (today, max(plan_last_day(p.entry_at), today + timedelta(days=RESULTS_BLACKOUT_DAYS)))
        for p, symbol in rows
    }
    results, results_checked = _results_dates(db, windows)

    holdings = []
    for p, symbol in rows:
        bucket = get_sector_bucket(symbol)
        holdings.append(
            Holding(
                symbol=symbol,
                value=(p.current_price or p.entry_price) * p.quantity,
                entry_price=p.entry_price,
                stop_loss=p.stop_loss,
                day=day_number(p.entry_at, today),
                max_position_pct=limits_for(base, p.strategy).max_position_pct,
                sector=bucket,
                sector_name=sector_display_name(bucket) if bucket else None,
                results_on=results.get(symbol),
            )
        )
    issues = check(holdings, base, limits)

    rules = [
        (
            f"Only one stock per sector (the rule for an account of {format_inr(base)})"
            if limits.sector_rule == "one_per_sector"
            else f"At most {_pct(limits.sector_cap_pct or 0)} of the account in one sector"
        ),
        f"At most {_pct(limits.max_position_pct)} of the account in one stock",
        f"Stop-loss {_pct(settings.ML_STOP_RETURN_PCT)} below the price paid",
        f"Every trade finished within {PLAN_TRADING_DAYS} trading days",
    ]
    if results_checked:
        rules.append("No company results day before the trade ends")

    notes = []
    if not results_checked:
        notes.append("The company results calendar has not loaded, so results days were not checked.")
    unmapped = sorted(h.symbol for h in holdings if not h.sector)
    if unmapped:
        notes.append(f"Not in the sector list, so left out of the sector check: {', '.join(unmapped)}.")

    return {
        "book": book,
        "book_label": BOOK_LABELS[book],
        "is_real_money": book == "real",
        "account_value": base,
        "account_value_basis": basis,
        "holdings_checked": len(holdings),
        "rules": rules,
        "results_checked": results_checked,
        "notes": notes,
        "issues": [{**asdict(i), "symbols": list(i.symbols)} for i in issues],
        "checked_at": datetime.now(IST).isoformat(),
    }
