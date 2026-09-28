"""The scan loop: evaluate every active strategy against every eligible symbol."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.brokers import get_broker
from swing_trade_ml.core.enums import SignalType
from swing_trade_ml.core.strategy_policy import is_advisory
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Strategy
from swing_trade_ml.ml.dataset import load_candles
from swing_trade_ml.services import risk
from swing_trade_ml.services.execution import process_decision
from swing_trade_ml.services.limits import limits_for
from swing_trade_ml.services.portfolio import portfolio_value_and_cash
from swing_trade_ml.strategies import get_strategy
from swing_trade_ml.strategies.base import SignalDecision

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


def eligible_instruments(db: Session, strategy: Strategy) -> list[Instrument]:
    """The strategy's own symbol list, or the whole watchlist when it is empty."""
    stmt = select(Instrument).where(Instrument.is_active.is_(True))
    if strategy.symbols:
        stmt = stmt.where(Instrument.tradingsymbol.in_([s.upper() for s in strategy.symbols]))
    else:
        stmt = stmt.where(Instrument.is_watchlisted.is_(True))
    return list(db.execute(stmt).scalars().all())


def _buy_slot_budget(db: Session, strategy: Strategy, mode: str) -> int:
    """How many BUYs this strategy may actually *fill* in one scan.

    Room is estimated once per scan from the same portfolio-wide open-position
    count `risk.check_entry` itself uses (not scoped to this strategy — that
    matches check_entry's own query, so this cap tracks what check_entry will
    actually allow rather than a stricter or looser estimate of it). The
    final per-instrument gate remains check_entry; this only decides how many
    of its approvals the scan is willing to take.
    """
    open_count = risk.open_position_count(db, mode)
    # Same resolver check_entry uses, fed the same portfolio value, so the
    # number of candidates acted on tracks the account-size ladder rather
    # than a fixed constant check_entry no longer reads.
    total_value, _cash = portfolio_value_and_cash(db, mode)
    slot_budget = limits_for(total_value, strategy).max_positions
    # check_entry also holds each strategy to a share of that budget, so the
    # tighter of the two is what a candidate actually has to fit through.
    share = max(1, slot_budget // max(risk.active_strategy_count(db, mode), 1))
    strategy_room = share - risk.open_position_count(db, mode, strategy.id)
    room = max(min(slot_budget - open_count, strategy_room), 0)
    return min(strategy.max_daily_buys, room) if strategy.max_daily_buys is not None else room


def _no_slot_left_reason(position: int, total: int, slots: int) -> str:
    """Why a BUY candidate was never tried, in words the app can show as-is."""
    if slots == 0:
        return (
            f"No room to buy anything today — this was candidate {position} of {total} "
            "by confidence, but the account is already at its position limit"
        )
    return (
        f"Ranked {position} of {total} today's BUY candidates by confidence — the day's "
        f"{slots} buy slot{'s' if slots != 1 else ''} were already filled by stronger ones"
    )


def run_strategy(db: Session, strategy: Strategy, interval: str = "day") -> ScanResult:
    if not is_advisory(strategy) and strategy.mode != get_broker().mode:
        raise ValueError("Automatic strategy mode does not match the current broker")
    result = ScanResult(strategies_run=1)
    impl = get_strategy(strategy)
    instruments = eligible_instruments(db, strategy)

    log.info(
        "engine.strategy.start",
        strategy=strategy.name,
        type=strategy.strategy_type,
        instruments=len(instruments),
    )

    pending: list[tuple[Instrument, SignalDecision]] = []
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

            pending.append((instrument, decision))

        except Exception as exc:  # noqa: BLE001 — one symbol must not abort the scan
            message = f"{strategy.name}/{instrument.tradingsymbol}: {exc}"
            log.error("engine.instrument.failed", strategy=strategy.name,
                      symbol=instrument.tradingsymbol, error=str(exc))
            result.errors.append(message)
            db.rollback()

    def attempt(instrument, decision, ranked_out_reason=None) -> bool:
        """Route one decision through risk to execution. True when it filled."""
        try:
            signal = process_decision(
                db, strategy, instrument, decision, ranked_out_reason=ranked_out_reason
            )
            if signal and signal.was_executed:
                result.executed += 1
                return True
        except Exception as exc:  # noqa: BLE001 - isolate each instrument
            message = f"{strategy.name}/{instrument.tradingsymbol}: {exc}"
            log.error("engine.instrument.failed", strategy=strategy.name,
                      symbol=instrument.tradingsymbol, error=str(exc))
            result.errors.append(message)
            db.rollback()
        return False

    def process(items):
        for instrument, decision in items:
            attempt(instrument, decision)

    # Only confirmed exits release capacity; pending orders still have open positions.
    process([(i, d) for i, d in pending if d.signal in (SignalType.EXIT, SignalType.SELL)])
    process([(i, d) for i, d in pending if d.signal == SignalType.HOLD])

    # Buy slots are spent by fills, never by rejections. Awarding them up front
    # on confidence alone is what broke buying in Sept 2026: the top-ranked
    # names were ones check_entry always refuses (cap tier, ASM list, stop-out
    # cooldown, too small to meet the minimum), they took every slot with them,
    # and each remaining candidate was discarded unexamined as "ranked out".
    # So walk the candidates strongest-first and only stop once the slots have
    # actually been filled.
    buys = sorted(
        [(i, d) for i, d in pending if d.signal == SignalType.BUY],
        key=lambda item: item[1].confidence or 0.0, reverse=True,
    )
    if buys:
        slots = _buy_slot_budget(db, strategy, strategy.mode)
        filled = 0
        for position, (instrument, decision) in enumerate(buys, start=1):
            if filled >= slots:
                attempt(instrument, decision,
                        ranked_out_reason=_no_slot_left_reason(position, len(buys), slots))
            elif attempt(instrument, decision):
                filled += 1

    log.info(
        "engine.strategy.done",
        strategy=strategy.name,
        signals=result.signals_generated,
        executed=result.executed,
        errors=len(result.errors),
    )
    return result


def run_all_active(db: Session, interval: str = "day") -> ScanResult:
    """Scan with every strategy whose mode matches the current broker, plus
    every advisory strategy regardless of mode.

    Filtering on mode means an "auto" strategy configured for live trading
    stays dormant during the paper phase instead of quietly producing paper
    signals under a live label. "advisory" strategies are exempt from that
    gate: process_decision() never lets them place a broker order — they only
    ever notify — so a live-mode advisory strategy (e.g. tracking real trades
    made manually in Zerodha) must still be scanned daily for fresh
    confidence/signals even while the broker itself is still in the paper
    phase.
    """
    mode = get_broker().mode
    strategies = list(
        db.execute(
            select(Strategy).where(
                Strategy.is_active.is_(True),
                (Strategy.mode == mode) | (Strategy.execution_mode == "advisory")
                | (Strategy.strategy_type == "long_term_value"),
            )
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
