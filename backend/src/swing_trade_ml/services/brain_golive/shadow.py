"""M18 stage 1: run the brain strategy right after the brain's nightly run.

Version 1's 15:45 scan leaves the brain strategy out (services/engine.py):
at 15:45 the brain has not run yet, so every stock would read "No brain run
today". This runs it once the nightly run is stored. Its signals go through
the normal strategy path; "brain" is always advisory in that path
(core/strategy_policy.py), so nothing is ever bought here.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.brokers import current_mode
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.trading import Strategy
from swing_trade_ml.services import engine
from swing_trade_ml.services.brain_golive import approvals
from swing_trade_ml.services.engine import ScanResult
from swing_trade_ml.strategies import brain as brain_strategy

log = get_logger(__name__)

BRAIN_STRATEGY_NAME = "TradeMind brain"
BRAIN_STRATEGY_DESCRIPTION = (
    "The TradeMind brain's ideas, recorded and scored next to version 1. It never buys on its own: "
    "in practice mode nothing is bought; later each idea waits for your OK on the Brain page."
)


def ensure_brain_strategy(db: Session) -> Strategy:
    existing = db.execute(
        select(Strategy).where(Strategy.strategy_type == "brain").order_by(Strategy.id).limit(1)
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    row = Strategy(
        name=BRAIN_STRATEGY_NAME,
        description=BRAIN_STRATEGY_DESCRIPTION,
        strategy_type="brain",
        params={},
        symbols=[],  # the whole watchlist, like the brain itself
        is_active=True,
        mode=current_mode(),
        execution_mode="advisory",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def active_brain_strategies(db: Session) -> list[Strategy]:
    return list(
        db.execute(
            select(Strategy)
            .where(Strategy.strategy_type == "brain", Strategy.is_active.is_(True))
            .order_by(Strategy.id)
        ).scalars()
    )


def _merge(into: ScanResult, r: ScanResult) -> None:
    into.strategies_run += r.strategies_run
    into.instruments_evaluated += r.instruments_evaluated
    into.signals_generated += r.signals_generated
    into.buys += r.buys
    into.exits += r.exits
    into.executed += r.executed
    into.errors.extend(r.errors)


def run_brain_strategy(db: Session, interval: str = "day") -> ScanResult:
    combined = ScanResult()
    today = brain_strategy.today_ist()
    for strategy in active_brain_strategies(db):
        if brain_strategy.todays_run(db, today, strategy.mode) is None:
            combined.errors.append(
                f"{strategy.name}: no brain run today for the {strategy.mode} book — skipped"
            )
            continue
        _merge(combined, engine.run_strategy(db, strategy, interval))
    if combined.strategies_run:
        # Practice (shadow) creates nothing; the approval stage asks the owner;
        # the automatic stage presses Approve through the same checks.
        outcome = approvals.after_scan(db, today)
        log.info("brain_golive.approvals.after_scan", **outcome)
    log.info("brain_golive.shadow.done", signals=combined.signals_generated, buys=combined.buys)
    return combined
