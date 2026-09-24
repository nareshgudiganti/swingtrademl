"""Portfolio valuation, mark-to-market, and performance statistics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from swing_trade_ml.brokers import get_broker, paper_broker
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import PositionStatus, TradingMode
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.market import Instrument, Quote
from swing_trade_ml.db.models.trading import PortfolioSnapshot, Position, Strategy, Trade

log = get_logger(__name__)

TRADING_DAYS_PER_YEAR = 252

# The advisory strategy that hand-bought Zerodha shares are tracked under —
# the "My Holdings" book. It is always stored as mode="live", so anything
# that reports on the bot's OWN book has to exclude it by strategy rather
# than trusting the mode filter, or the two merge the day the bot goes live.
REAL_TRADING_STRATEGY_NAME = "real_trading"


def exclude_real_trading(strategy_id_col: Any) -> Any:
    """A WHERE clause keeping only the bot's own rows. Rows with no strategy
    at all are the bot's: only `real_trading` marks a row as hand-bought."""
    real_ids = select(Strategy.id).where(Strategy.name == REAL_TRADING_STRATEGY_NAME)
    return or_(strategy_id_col.is_(None), strategy_id_col.not_in(real_ids))


def portfolio_value_and_cash(
    db: Session, mode: str, *, bot_book_only: bool = False
) -> tuple[float, float]:
    """(total portfolio value, available cash).

    In paper mode both come from the simulated ledger; in live mode cash comes
    from the broker's real margin and holdings are valued at last price.

    Live-mode cash always reads real Kite margins directly — not through
    get_broker(), which only returns the Kite broker once the app's own
    TRADING_MODE is switched to live. A live-mode *advisory* strategy (real
    trades made manually, tracked for confidence/exposure only — never
    auto-executed) still needs its real cash figure while the app itself is
    still in the paper phase, so this can't wait on that global toggle.
    """
    stmt = select(Position).where(Position.mode == mode, Position.status == PositionStatus.OPEN)
    if bot_book_only:
        stmt = stmt.where(exclude_real_trading(Position.strategy_id))
    open_positions = list(db.execute(stmt).scalars().all())
    holdings_value = sum(
        (p.current_price or p.entry_price) * p.quantity for p in open_positions
    )

    if mode == TradingMode.PAPER:
        cash = paper_broker.get_available_cash(db)
    else:
        from swing_trade_ml.brokers.kite import kite_broker

        try:
            kite_broker.load_session(db)
            cash = kite_broker.get_margins(db).available_cash
        except Exception as exc:  # noqa: BLE001
            log.error("portfolio.margins_failed", error=str(exc))
            cash = 0.0

        # Money committed to a buy the broker has accepted but not yet filled
        # is not spendable, and Kite's margin figure can still show it as
        # available for a moment. Counting it twice is what let the rest of a
        # scan keep buying past the cash floor.
        from swing_trade_ml.services.risk import in_flight_buy_holdings

        cash -= sum(h.value for h in in_flight_buy_holdings(db, mode))

    return holdings_value + cash, cash


def mark_to_market(db: Session, mode: str | None = None) -> int:
    """Refresh `current_price` and unrealised P&L on open positions.

    Reads the cached `quotes` table rather than calling the broker: this runs
    frequently, and one bulk read beats N network calls.

    Positions belonging to an advisory strategy are marked regardless of the
    mode filter, matching what execution.check_exits already does. Without it
    a live-mode advisory book — real Zerodha holdings tracked here — is
    invisible while the broker sits in paper, so current_price never moves off
    the entry price and every one of those positions reads as exactly flat no
    matter what the market does. An explicit `mode` argument still narrows to
    that mode alone, for callers that genuinely mean one book.
    """
    broker_mode = mode or get_broker().mode
    scope = Position.mode == broker_mode
    if mode is None:
        scope = or_(
            scope,
            Position.strategy_id.in_(
                select(Strategy.id).where(Strategy.execution_mode == "advisory")
            ),
        )
    positions = list(
        db.execute(select(Position).where(scope, Position.status == PositionStatus.OPEN))
        .scalars()
        .all()
    )
    if not positions:
        return 0

    quotes = {
        row.instrument_id: row.last_price
        for row in db.execute(
            select(Quote).where(Quote.instrument_id.in_([p.instrument_id for p in positions]))
        ).scalars()
    }

    updated = 0
    for position in positions:
        price = quotes.get(position.instrument_id)
        if price is None:
            continue
        position.current_price = price
        position.unrealized_pnl = (price - position.entry_price) * position.quantity
        if position.highest_price is None or price > position.highest_price:
            position.highest_price = price
        updated += 1

    if updated:
        db.commit()
    return updated


def take_snapshot(db: Session, mode: str | None = None) -> PortfolioSnapshot:
    """Write today's equity-curve point.

    Upserts on the calendar date so re-running the job replaces rather than
    duplicates the day's row.
    """
    mode = mode or get_broker().mode
    now = datetime.now(UTC)

    total_value, cash = portfolio_value_and_cash(db, mode)
    holdings_value = total_value - cash

    open_positions = list(
        db.execute(
            select(Position).where(Position.mode == mode, Position.status == PositionStatus.OPEN)
        )
        .scalars()
        .all()
    )
    unrealized = sum(p.unrealized_pnl for p in open_positions)
    realized = float(
        db.execute(
            select(func.coalesce(func.sum(Trade.net_pnl), 0.0)).where(Trade.mode == mode)
        ).scalar_one()
    )

    previous = db.execute(
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.mode == mode)
        .order_by(PortfolioSnapshot.ts.desc())
        .limit(1)
    ).scalar_one_or_none()

    starting = settings.PAPER_STARTING_CAPITAL if mode == TradingMode.PAPER else total_value
    day_pnl = total_value - previous.total_value if previous else total_value - starting
    peak = max(total_value, previous.peak_value if previous else starting)
    drawdown = (peak - total_value) / peak if peak else 0.0

    today = now.date()
    existing = None
    if previous and previous.ts.date() == today:
        existing = previous

    if existing:
        existing.cash = cash
        existing.holdings_value = holdings_value
        existing.total_value = total_value
        existing.realized_pnl = realized
        existing.unrealized_pnl = unrealized
        existing.day_pnl = day_pnl
        existing.open_positions = len(open_positions)
        existing.peak_value = peak
        existing.drawdown_pct = drawdown
        snapshot = existing
    else:
        snapshot = PortfolioSnapshot(
            mode=mode,
            ts=now,
            cash=cash,
            holdings_value=holdings_value,
            total_value=total_value,
            realized_pnl=realized,
            unrealized_pnl=unrealized,
            day_pnl=day_pnl,
            open_positions=len(open_positions),
            peak_value=peak,
            drawdown_pct=drawdown,
        )
        db.add(snapshot)

    db.commit()
    db.refresh(snapshot)
    log.info(
        "portfolio.snapshot",
        mode=mode,
        total_value=round(total_value, 2),
        drawdown=round(drawdown, 4),
    )
    return snapshot


def performance_stats(
    db: Session, mode: str | None = None, *, bot_book_only: bool = False
) -> dict[str, Any]:
    """Aggregate performance over all closed trades plus the equity curve.

    This is the report the six-month paper phase is run to produce — the basis
    for deciding whether to go live at all.

    `bot_book_only` drops the hand-bought "My Holdings" rows, so the figures
    describe what the bot itself did. In paper mode that changes nothing (the
    My Holdings book is live), but once the bot is live it is the difference
    between "how is the bot doing" and "how is the account doing".

    One exception: the snapshot-derived stats at the bottom (drawdown, day
    P&L, Sharpe/Sortino) stay account-wide either way, because a snapshot
    stores one total per mode and has no column to split the books by. They
    would need a per-book snapshot row to honour this flag.
    """
    mode = mode or get_broker().mode

    trades_stmt = select(Trade).where(Trade.mode == mode).order_by(Trade.exit_at)
    positions_stmt = select(Position).where(
        Position.mode == mode, Position.status == PositionStatus.OPEN
    )
    if bot_book_only:
        trades_stmt = trades_stmt.where(exclude_real_trading(Trade.strategy_id))
        positions_stmt = positions_stmt.where(exclude_real_trading(Position.strategy_id))

    trades = list(db.execute(trades_stmt).scalars().all())
    total_value, cash = portfolio_value_and_cash(db, mode, bot_book_only=bot_book_only)
    open_positions = list(db.execute(positions_stmt).scalars().all())

    starting = settings.PAPER_STARTING_CAPITAL if mode == TradingMode.PAPER else total_value
    unrealized = sum(p.unrealized_pnl for p in open_positions)
    realized = sum(t.net_pnl for t in trades)

    stats: dict[str, Any] = {
        "mode": mode,
        "starting_capital": starting,
        "total_value": total_value,
        "cash": cash,
        "holdings_value": total_value - cash,
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
        "total_pnl": realized + unrealized,
        "total_return_pct": (total_value / starting - 1) if starting else 0.0,
        "open_positions": len(open_positions),
        "total_trades": len(trades),
    }

    if trades:
        wins = [t for t in trades if t.is_win]
        losses = [t for t in trades if not t.is_win]
        gross_profit = sum(t.net_pnl for t in wins)
        gross_loss = abs(sum(t.net_pnl for t in losses))

        stats |= {
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": len(wins) / len(trades),
            "avg_win": gross_profit / len(wins) if wins else 0.0,
            "avg_loss": -gross_loss / len(losses) if losses else 0.0,
            "largest_win": max((t.net_pnl for t in wins), default=0.0),
            "largest_loss": min((t.net_pnl for t in losses), default=0.0),
            # Gross profit per rupee of gross loss. Above 1.5 is a genuinely
            # tradeable edge; below 1.0 the strategy loses money by definition.
            "profit_factor": (gross_profit / gross_loss) if gross_loss else float("inf"),
            "avg_holding_days": float(np.mean([t.holding_days for t in trades])),
            "avg_return_pct": float(np.mean([t.return_pct for t in trades])),
            "total_charges": sum(t.charges for t in trades),
            "expectancy": realized / len(trades),
        }
    else:
        stats |= {
            "winning_trades": 0, "losing_trades": 0, "win_rate": 0.0,
            "avg_win": 0.0, "avg_loss": 0.0, "profit_factor": 0.0,
            "avg_holding_days": 0.0, "avg_return_pct": 0.0,
            "total_charges": 0.0, "expectancy": 0.0,
        }

    snapshots = list(
        db.execute(
            select(PortfolioSnapshot)
            .where(PortfolioSnapshot.mode == mode)
            .order_by(PortfolioSnapshot.ts)
        )
        .scalars()
        .all()
    )
    if len(snapshots) > 1:
        values = np.array([s.total_value for s in snapshots], dtype=float)
        daily_returns = np.diff(values) / values[:-1]
        stats["max_drawdown_pct"] = float(max(s.drawdown_pct for s in snapshots))
        stats["current_drawdown_pct"] = float(snapshots[-1].drawdown_pct)
        stats["day_pnl"] = float(snapshots[-1].day_pnl)
        stats["day_pnl_pct"] = (
            float(snapshots[-1].day_pnl / snapshots[-2].total_value)
            if snapshots[-2].total_value
            else 0.0
        )

        std = daily_returns.std()
        # Annualised Sharpe, risk-free rate assumed zero. Over a six-month paper
        # run this is indicative only — the sample is too short to be a
        # statistically sound estimate.
        stats["sharpe_ratio"] = (
            float(daily_returns.mean() / std * np.sqrt(TRADING_DAYS_PER_YEAR)) if std else 0.0
        )
        downside = daily_returns[daily_returns < 0]
        stats["sortino_ratio"] = (
            float(daily_returns.mean() / downside.std() * np.sqrt(TRADING_DAYS_PER_YEAR))
            if len(downside) and downside.std()
            else 0.0
        )
    else:
        stats |= {
            "max_drawdown_pct": 0.0, "current_drawdown_pct": 0.0,
            "day_pnl": 0.0, "day_pnl_pct": 0.0,
            "sharpe_ratio": 0.0, "sortino_ratio": 0.0,
        }

    stats["top_movers"] = sorted(
        (
            {
                "symbol": (db.get(Instrument, p.instrument_id) or Instrument()).tradingsymbol,
                "pnl": p.unrealized_pnl,
                "pnl_pct": (
                    (p.current_price or p.entry_price) / p.entry_price - 1 if p.entry_price else 0.0
                ),
            }
            for p in open_positions
        ),
        key=lambda d: abs(d["pnl"]),
        reverse=True,
    )

    return stats


def strategy_performance_stats(
    db: Session, strategy_id: int, since: datetime | None = None
) -> dict[str, Any]:
    """Win rate / profit factor / net P&L for one strategy's closed trades —
    the per-strategy counterpart to performance_stats() above, which is
    scoped by broker mode instead. Powers the Strategies tab's win-rate cards
    and the by-strategy Reports breakdown. `since` restricts to trades closed
    on/after that timestamp; omit for all-time.
    """
    stmt = select(Trade).where(Trade.strategy_id == strategy_id)
    if since is not None:
        stmt = stmt.where(Trade.exit_at >= since)
    trades = list(db.execute(stmt).scalars().all())

    if not trades:
        return {"trades": 0, "win_rate": 0.0, "profit_factor": 0.0, "net_pnl": 0.0}

    wins = [t for t in trades if t.is_win]
    losses = [t for t in trades if not t.is_win]
    gross_profit = sum(t.net_pnl for t in wins)
    gross_loss = abs(sum(t.net_pnl for t in losses))

    return {
        "trades": len(trades),
        "win_rate": len(wins) / len(trades),
        "profit_factor": (gross_profit / gross_loss) if gross_loss else float("inf"),
        "net_pnl": sum(t.net_pnl for t in trades),
    }


def recent_post_exit_watch(db: Session, mode: str, lookback_days: int = 21) -> list[dict[str, Any]]:
    """Trades closed recently, with how far the stock has moved since we sold.

    Feeds the daily Telegram digest so "did we exit too early or was it the
    right call" can be watched every day without opening the app — pushed
    instead of only pulled from the Trades page's post-exit columns. A row
    stays in the digest either while it's fresh (first week after the sell,
    so a same-day exit like GVT&D shows up immediately) or once it's moved
    enough to be worth flagging (5%+ either way); quiet, unremarkable older
    exits age out rather than cluttering every day's message.
    """
    cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
    trades = list(
        db.execute(
            select(Trade)
            .where(Trade.mode == mode, Trade.exit_at >= cutoff)
            .order_by(Trade.exit_at.desc())
        )
        .scalars()
        .all()
    )
    if not trades:
        return []

    instrument_ids = {t.instrument_id for t in trades}
    live_prices = {
        q.instrument_id: q.last_price
        for q in db.execute(
            select(Quote).where(Quote.instrument_id.in_(instrument_ids))
        ).scalars()
    }

    from swing_trade_ml.db.models.market import Candle

    rows: list[dict[str, Any]] = []
    now = datetime.now(UTC)
    for t in trades:
        price = live_prices.get(t.instrument_id)
        if price is None:
            price = db.execute(
                select(Candle.close)
                .where(Candle.interval == "day", Candle.instrument_id == t.instrument_id)
                .order_by(Candle.ts.desc())
                .limit(1)
            ).scalar_one_or_none()
        if price is None or not t.exit_price:
            continue

        change_pct = (price - t.exit_price) / t.exit_price
        days_since_exit = (now - t.exit_at).days
        if days_since_exit > 7 and abs(change_pct) < 0.05:
            continue

        rows.append(
            {
                "symbol": t.symbol,
                "exit_price": t.exit_price,
                "exit_reason": t.exit_reason,
                "current_price": price,
                "change_pct": change_pct,
                "days_since_exit": days_since_exit,
            }
        )

    rows.sort(key=lambda r: abs(r["change_pct"]), reverse=True)
    return rows


def equity_curve(db: Session, mode: str | None = None, days: int = 180) -> list[dict[str, Any]]:
    mode = mode or get_broker().mode
    since = datetime.now(UTC) - timedelta(days=days)
    snapshots = list(
        db.execute(
            select(PortfolioSnapshot)
            .where(PortfolioSnapshot.mode == mode, PortfolioSnapshot.ts >= since)
            .order_by(PortfolioSnapshot.ts)
        )
        .scalars()
        .all()
    )
    return [
        {
            "date": s.ts.date().isoformat(),
            "total_value": s.total_value,
            "cash": s.cash,
            "holdings_value": s.holdings_value,
            "day_pnl": s.day_pnl,
            "drawdown_pct": s.drawdown_pct,
            "open_positions": s.open_positions,
        }
        for s in snapshots
    ]
