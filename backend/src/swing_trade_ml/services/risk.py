"""Position sizing and pre-trade risk checks.

Every entry passes through `check_entry` before an order is created. Rejections
are recorded on the signal rather than dropped, so the paper phase produces
evidence about whether the limits helped or cost money.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import PositionStatus
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.trading import PortfolioSnapshot, Position, Strategy

log = get_logger(__name__)


@dataclass(slots=True)
class RiskDecision:
    allowed: bool
    quantity: int = 0
    reason: str = ""


def rank_buy_candidates(candidates: list[tuple[int, float]]) -> list[tuple[int, float]]:
    """BUY candidates from one scan — (instrument_id, confidence) pairs —
    ordered strongest-first.

    When more stocks clear the confidence bar than there are free position
    slots, this decides who gets them: the strategy's best ideas, not
    whichever instrument happened to be evaluated first. A stable sort keeps
    ties in their original (evaluation) order rather than reshuffling them
    arbitrarily on every scan.
    """
    return sorted(candidates, key=lambda c: c[1], reverse=True)


def open_position_count(db: Session, mode: str, strategy_id: int | None = None) -> int:
    stmt = select(func.count(Position.id)).where(
        Position.mode == mode, Position.status == PositionStatus.OPEN
    )
    if strategy_id is not None:
        stmt = stmt.where(Position.strategy_id == strategy_id)
    return int(db.execute(stmt).scalar_one() or 0)


def has_open_position(
    db: Session, mode: str, instrument_id: int, strategy_id: int | None = None
) -> bool:
    """Scoped per-strategy when strategy_id is given: each strategy manages
    its own book independently, so two different strategies holding the same
    symbol at once is not a duplicate entry — that is what running the
    ml_swing and sma_crossover strategies side by side as a comparison
    depends on."""
    stmt = select(Position.id).where(
        Position.mode == mode,
        Position.instrument_id == instrument_id,
        Position.status == PositionStatus.OPEN,
    )
    if strategy_id is not None:
        stmt = stmt.where(Position.strategy_id == strategy_id)
    return db.execute(stmt).first() is not None


def open_exposure_value(db: Session, mode: str, strategy_id: int | None, instrument_id: int) -> float:
    """Rupees already committed to this instrument across all open tranches
    for this strategy — the pyramiding case, where more than one Position row
    can be open for the same instrument at once."""
    total = db.execute(
        select(func.coalesce(func.sum(Position.entry_price * Position.quantity), 0.0)).where(
            Position.mode == mode,
            Position.instrument_id == instrument_id,
            Position.strategy_id == strategy_id,
            Position.status == PositionStatus.OPEN,
        )
    ).scalar_one()
    return float(total)


def current_drawdown(db: Session, mode: str) -> float:
    """Drawdown from the running peak, as a positive fraction."""
    snapshot = db.execute(
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.mode == mode)
        .order_by(PortfolioSnapshot.ts.desc())
        .limit(1)
    ).scalar_one_or_none()
    if snapshot is None or not snapshot.peak_value:
        return 0.0
    return max(0.0, (snapshot.peak_value - snapshot.total_value) / snapshot.peak_value)


def calculate_quantity(
    price: float,
    stop_loss: float | None,
    portfolio_value: float,
    available_cash: float,
    strategy: Strategy | None = None,
    existing_exposure: float = 0.0,
) -> tuple[int, str]:
    """Size the position off the distance to the stop, not off a fixed rupee amount.

    Risking a constant fraction of equity per trade means a wide stop
    automatically gets a smaller position and a tight stop a larger one, so
    every trade carries the same downside. That is the single highest-leverage
    risk control in the system.

    Two ceilings then apply: the max share of portfolio in one name, and the
    cash actually on hand. `existing_exposure` is rupees already committed to
    this instrument by an earlier tranche (pyramiding) — the concentration
    cap applies to *total* exposure across tranches, not each one separately.
    """
    if price <= 0:
        return 0, "Invalid price"

    risk_capital = portfolio_value * settings.RISK_PER_TRADE_PCT

    if stop_loss and stop_loss > 0 and stop_loss < price:
        risk_per_share = price - stop_loss
    else:
        # No stop supplied — assume the default stop distance so sizing stays
        # bounded rather than falling back to "as much as cash allows".
        risk_per_share = price * settings.DEFAULT_STOP_LOSS_PCT

    if risk_per_share <= 0:
        return 0, "Non-positive risk per share"

    qty_by_risk = risk_capital / risk_per_share

    max_position_pct = (
        strategy.capital_allocation
        if strategy and strategy.capital_allocation
        else settings.MAX_POSITION_PCT
    )
    remaining_concentration_room = max(0.0, (portfolio_value * max_position_pct) - existing_exposure)
    qty_by_concentration = remaining_concentration_room / price
    qty_by_cash = available_cash / price

    # floor, never round: rounding up would breach whichever limit was binding.
    quantity = math.floor(min(qty_by_risk, qty_by_concentration, qty_by_cash))

    if quantity < 1:
        return 0, (
            f"Computed size below 1 share (risk-based {qty_by_risk:.2f}, "
            f"concentration {qty_by_concentration:.2f}, cash {qty_by_cash:.2f})"
        )

    binding = min(
        ("risk-per-trade", qty_by_risk),
        ("concentration cap", qty_by_concentration),
        ("available cash", qty_by_cash),
        key=lambda kv: kv[1],
    )[0]
    return quantity, f"Sized by {binding}"


def check_entry(
    db: Session,
    mode: str,
    instrument_id: int,
    price: float,
    stop_loss: float | None,
    portfolio_value: float,
    available_cash: float,
    strategy: Strategy | None = None,
    existing_exposure: float = 0.0,
) -> RiskDecision:
    """Gate an entry. Checks run cheapest-first so an obvious rejection does not
    pay for a portfolio-wide query.

    `existing_exposure` > 0 signals that the caller has already vetted this as
    a pyramiding add (strategy.allow_pyramiding and the open position is
    currently profitable — see services/execution.py process_decision) and
    computed the rupees already committed via open_exposure_value(); the
    has_open_position block below only applies to the normal, non-pyramiding
    case.
    """
    strategy_id = strategy.id if strategy else None
    if existing_exposure <= 0 and has_open_position(db, mode, instrument_id, strategy_id):
        return RiskDecision(False, 0, "Position already open in this instrument")

    max_positions = (
        strategy.max_positions if strategy and strategy.max_positions else settings.MAX_OPEN_POSITIONS
    )
    open_count = open_position_count(db, mode)
    if open_count >= max_positions:
        return RiskDecision(False, 0, f"At position limit ({open_count}/{max_positions})")

    drawdown = current_drawdown(db, mode)
    if drawdown >= settings.MAX_PORTFOLIO_DRAWDOWN_PCT:
        # Halts new entries only; existing positions still exit normally, so
        # the circuit breaker cannot trap capital in losing trades.
        return RiskDecision(
            False,
            0,
            f"Drawdown circuit breaker: {drawdown:.1%} exceeds "
            f"{settings.MAX_PORTFOLIO_DRAWDOWN_PCT:.0%} — new entries halted",
        )

    quantity, note = calculate_quantity(
        price, stop_loss, portfolio_value, available_cash, strategy, existing_exposure
    )
    if quantity < 1:
        return RiskDecision(False, 0, note)

    if quantity * price > available_cash:
        return RiskDecision(False, 0, "Insufficient cash after sizing")

    return RiskDecision(True, quantity, note)
