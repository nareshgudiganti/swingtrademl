"""The scan loop: evaluate every active strategy against every eligible symbol."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.brokers import get_broker
from swing_trade_ml.core.enums import SignalType
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Strategy
from swing_trade_ml.ml.dataset import load_candles
from swing_trade_ml.services.execution import process_decision
from swing_trade_ml.strategies import get_strategy

log = get_logger(__name__)


@dataclass(slots=True)
class ScanResult:
    strategies_run: int = 0
    instruments_evaluated: int = 0
    signals_generated: int = 0
    buys: int = 0
    exits: int = 0
    executed: int = 0
    errors: list[str] = field(default_factory=list)


def _eligible_instruments(db: Session, strategy: Strategy) -> list[Instrument]:
    """The strategy's own symbol list, or the whole watchlist when it is empty."""
    stmt = select(Instrument).where(Instrument.is_active.is_(True))
    if strategy.symbols:
        stmt = stmt.where(Instrument.tradingsymbol.in_([s.upper() for s in strategy.symbols]))
    else:
        stmt = stmt.where(Instrument.is_watchlisted.is_(True))
    return list(db.execute(stmt).scalars().all())


def run_strategy(db: Session, strategy: Strategy, interval: str = "day") -> ScanResult:
    result = ScanResult(strategies_run=1)
    impl = get_strategy(strategy)
    instruments = _eligible_instruments(db, strategy)

    log.info(
        "engine.strategy.start",
        strategy=strategy.name,
        type=strategy.strategy_type,
        instruments=len(instruments),
    )

    for instrument in instruments:
        result.instruments_evaluated += 1
        try:
            # +50 bars of headroom above the strategy's stated minimum so the
            # longest indicator window is fully warmed, not just barely met.
            df = load_candles(db, instrument.id, interval, limit=impl.min_bars_required() + 50)
            if df.empty:
                continue

            decision = impl.evaluate(df, instrument, db)
            if decision is None:
                continue

            result.signals_generated += 1
            if decision.signal == SignalType.BUY:
                result.buys += 1
            elif decision.signal in (SignalType.EXIT, SignalType.SELL):
                result.exits += 1

            signal = process_decision(db, strategy, instrument, decision)
            if signal and signal.was_executed:
                result.executed += 1

        except Exception as exc:  # noqa: BLE001 — one symbol must not abort the scan
            message = f"{strategy.name}/{instrument.tradingsymbol}: {exc}"
            log.error("engine.instrument.failed", strategy=strategy.name,
                      symbol=instrument.tradingsymbol, error=str(exc))
            result.errors.append(message)
            db.rollback()

    log.info(
        "engine.strategy.done",
        strategy=strategy.name,
        signals=result.signals_generated,
        executed=result.executed,
        errors=len(result.errors),
    )
    return result


def run_all_active(db: Session, interval: str = "day") -> ScanResult:
    """Scan with every strategy whose mode matches the current broker.

    Filtering on mode means a strategy configured for live trading stays dormant
    during the paper phase instead of quietly producing paper signals under a
    live label.
    """
    mode = get_broker().mode
    strategies = list(
        db.execute(
            select(Strategy).where(Strategy.is_active.is_(True), Strategy.mode == mode)
        )
        .scalars()
        .all()
    )

    combined = ScanResult()
    if not strategies:
        log.info("engine.no_active_strategies", mode=mode)
        return combined

    for strategy in strategies:
        try:
            r = run_strategy(db, strategy, interval)
        except Exception as exc:  # noqa: BLE001
            log.error("engine.strategy.failed", strategy=strategy.name, error=str(exc))
            combined.errors.append(f"{strategy.name}: {exc}")
            db.rollback()
            continue

        combined.strategies_run += r.strategies_run
        combined.instruments_evaluated += r.instruments_evaluated
        combined.signals_generated += r.signals_generated
        combined.buys += r.buys
        combined.exits += r.exits
        combined.executed += r.executed
        combined.errors.extend(r.errors)

    return combined
