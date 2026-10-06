"""Manual paper-testing book — separate from the bot's own portfolio.

Positions live under the `tester_paper` strategy. They are never scanned by
the daily engine and never mixed into `book=bot` reports.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from swing_trade_ml.brokers import get_broker, paper_broker
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import (
    OrderType,
    PositionStatus,
    ProductType,
    SignalType,
    TradingMode,
    TransactionType,
)
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Order, Position, Signal, Strategy, Trade
from swing_trade_ml.services.execution import open_position

log = get_logger(__name__)

TESTER_PAPER_STRATEGY_NAME = "tester_paper"
TESTER_PAPER_STRATEGY_TYPE = "tester_paper"
CapTier = Literal["large", "midcap", "smallcap"]
VALID_CAP_TIERS: frozenset[str] = frozenset({"large", "midcap", "smallcap"})


class PaperTesterDisabled(Exception):
    pass


class PaperTesterNotPaperMode(Exception):
    pass


def require_enabled() -> None:
    if not settings.PAPER_TESTER_ENABLED:
        raise PaperTesterDisabled("Paper testing is disabled on this server.")


def require_paper_mode() -> None:
    if get_broker().mode != TradingMode.PAPER:
        raise PaperTesterNotPaperMode("Paper testing only works when TRADING_MODE=paper.")


def get_or_create_strategy(db: Session) -> Strategy:
    row = db.execute(
        select(Strategy).where(Strategy.name == TESTER_PAPER_STRATEGY_NAME)
    ).scalar_one_or_none()
    if row is not None:
        return row
    row = Strategy(
        name=TESTER_PAPER_STRATEGY_NAME,
        strategy_type=TESTER_PAPER_STRATEGY_TYPE,
        description="Manual paper trades for validation — not the bot or brain book.",
        params={},
        is_active=False,
        mode=TradingMode.PAPER,
        execution_mode="auto",
    )
    db.add(row)
    db.flush()
    return row


def strategy_id_subquery():
    return select(Strategy.id).where(Strategy.name == TESTER_PAPER_STRATEGY_NAME)


def only_tester(strategy_id_col: Any) -> Any:
    return strategy_id_col.in_(strategy_id_subquery())


def _locked_capital(db: Session) -> float:
    return float(
        db.execute(
            select(
                func.coalesce(
                    func.sum(Position.entry_price * Position.quantity + Position.total_charges),
                    0.0,
                )
            ).where(
                Position.mode == TradingMode.PAPER,
                Position.status == PositionStatus.OPEN,
                Position.strategy_id.in_(strategy_id_subquery()),
            )
        ).scalar_one()
    )


def _realized_pnl(db: Session) -> float:
    return float(
        db.execute(
            select(func.coalesce(func.sum(Trade.net_pnl), 0.0)).where(
                Trade.mode == TradingMode.PAPER,
                Trade.strategy_id.in_(strategy_id_subquery()),
            )
        ).scalar_one()
    )


def available_cash(db: Session) -> float:
    """Virtual cash for the tester book only (independent starting capital)."""
    return settings.PAPER_TESTER_STARTING_CAPITAL + _realized_pnl(db) - _locked_capital(db)


def portfolio_value(db: Session) -> tuple[float, float, float]:
    """(total value, cash, holdings value) for the tester book."""
    positions = list(
        db.execute(
            select(Position).where(
                Position.mode == TradingMode.PAPER,
                Position.status == PositionStatus.OPEN,
                Position.strategy_id.in_(strategy_id_subquery()),
            )
        )
        .scalars()
        .all()
    )
    holdings = sum((p.current_price or p.entry_price) * p.quantity for p in positions)
    cash = available_cash(db)
    return holdings + cash, cash, holdings


def performance_stats(db: Session) -> dict[str, Any]:
    """Headline stats for book=tester (same shape as portfolio.performance_stats)."""
    require_paper_mode()
    positions = list(
        db.execute(
            select(Position).where(
                Position.mode == TradingMode.PAPER,
                Position.status == PositionStatus.OPEN,
                Position.strategy_id.in_(strategy_id_subquery()),
            )
        )
        .scalars()
        .all()
    )
    trades = list(
        db.execute(
            select(Trade)
            .where(
                Trade.mode == TradingMode.PAPER,
                Trade.strategy_id.in_(strategy_id_subquery()),
            )
            .order_by(Trade.exit_at)
        )
        .scalars()
        .all()
    )
    total_value, cash, holdings_value = portfolio_value(db)
    starting = settings.PAPER_TESTER_STARTING_CAPITAL
    unrealized = sum(p.unrealized_pnl for p in positions)
    realized = sum(t.net_pnl for t in trades)
    stats: dict[str, Any] = {
        "mode": TradingMode.PAPER,
        "measured_since": None,
        "starting_capital": starting,
        "total_value": total_value,
        "cash": cash,
        "holdings_value": holdings_value,
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
        "total_pnl": realized + unrealized,
        "total_return_pct": (total_value / starting - 1) if starting else 0.0,
        "open_positions": len(positions),
        "total_trades": len(trades),
        "book": "tester",
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
            "profit_factor": (gross_profit / gross_loss) if gross_loss else float("inf"),
        }
    else:
        stats |= {"winning_trades": 0, "losing_trades": 0, "win_rate": 0.0, "profit_factor": 0.0}
    stats.setdefault("max_drawdown_pct", 0.0)
    stats.setdefault("day_pnl", 0.0)
    stats.setdefault("day_pnl_pct", 0.0)
    return stats


def entry_signal_cap_tier(db: Session, position_id: int) -> str | None:
    row = db.execute(
        select(Signal)
        .join(Order, Order.signal_id == Signal.id)
        .where(
            Order.position_id == position_id,
            Order.transaction_type == TransactionType.BUY,
        )
        .order_by(Order.placed_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        return None
    tier = (row.features or {}).get("user_cap_tier")
    return tier if tier in VALID_CAP_TIERS else None


def paper_buy(
    db: Session,
    symbol: str,
    quantity: int,
    cap_tier: CapTier,
    exchange: str = "NSE",
) -> Position:
    require_enabled()
    require_paper_mode()
    if quantity <= 0:
        raise ValueError("Quantity must be positive.")
    if cap_tier not in VALID_CAP_TIERS:
        raise ValueError("cap_tier must be large, midcap, or smallcap.")

    instrument = db.execute(
        select(Instrument).where(
            Instrument.tradingsymbol == symbol.upper(),
            Instrument.exchange == exchange.upper(),
            Instrument.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if instrument is None:
        raise LookupError(f"Unknown symbol {exchange}:{symbol.upper()} — sync instruments first.")

    strategy = get_or_create_strategy(db)
    ref = paper_broker._reference_price(instrument.tradingsymbol, instrument.exchange, db)
    if ref is None or ref <= 0:
        raise ValueError(f"No price available for {instrument.tradingsymbol}.")

    from swing_trade_ml.api.v1.endpoints.portfolio import _derive_stop_target
    from swing_trade_ml.services.costs import compute_charges

    stop_loss, take_profit, _basis = _derive_stop_target(db, instrument, ref)
    est_turnover = ref * quantity
    brokerage, taxes = compute_charges(est_turnover, TransactionType.BUY)
    required = est_turnover + brokerage + taxes
    cash = available_cash(db)
    if required > cash:
        raise ValueError(
            f"Not enough paper testing cash: need about ₹{required:,.0f}, have ₹{cash:,.0f}."
        )
    if paper_broker.get_available_cash(db) < required:
        raise ValueError(
            "The shared practice cash pool is too low for this buy "
            "(bot paper trades and manual testing share the same pool)."
        )

    now = datetime.now(UTC)
    signal = Signal(
        strategy_id=strategy.id,
        instrument_id=instrument.id,
        signal_type=SignalType.BUY,
        mode=TradingMode.PAPER,
        price=ref,
        stop_loss=stop_loss,
        take_profit=take_profit,
        horizon_days=15,
        reason="Manual paper test buy",
        features={"user_cap_tier": cap_tier, "source": "paper_tester"},
        generated_at=now,
        advisory_only=False,
    )
    db.add(signal)
    db.flush()

    position = open_position(db, strategy, instrument, signal, quantity)
    if position is None:
        raise RuntimeError("Paper buy did not fill — check orders for a rejection message.")
    log.info(
        "paper_tester.buy",
        symbol=instrument.tradingsymbol,
        qty=quantity,
        cap_tier=cap_tier,
        position_id=position.id,
    )
    return position
