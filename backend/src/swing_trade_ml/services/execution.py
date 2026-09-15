"""Execution: turning signals into orders, positions and trades.

This is the only module that writes Order/Position/Trade rows. Strategies decide
*what*, risk decides *how much*, and this decides *whether and when* — keeping
those three concerns separate is what makes the paper phase's results
attributable to the strategy rather than to the plumbing.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from swing_trade_ml.brokers import OrderRequest, OrderResult, get_broker
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import (
    ExitReason,
    OrderStatus,
    OrderType,
    PositionStatus,
    ProductType,
    SignalType,
    TransactionType,
)
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Order, Position, Signal, Strategy, Trade
from swing_trade_ml.notifications import notifier
from swing_trade_ml.services import risk, system_state
from swing_trade_ml.services.costs import compute_charges
from swing_trade_ml.services.exit_policy import exit_policy_for, scale_out_quantity
from swing_trade_ml.services.portfolio import portfolio_value_and_cash

log = get_logger(__name__)


def record_signal(
    db: Session,
    strategy: Strategy,
    instrument: Instrument,
    decision,
    mode: str,
    quantity: int | None = None,
) -> Signal:
    signal = Signal(
        strategy_id=strategy.id,
        instrument_id=instrument.id,
        signal_type=decision.signal,
        mode=mode,
        price=decision.price,
        confidence=decision.confidence,
        suggested_quantity=quantity,
        stop_loss=decision.stop_loss,
        take_profit=decision.take_profit,
        horizon_days=decision.horizon_days,
        reason=decision.reason,
        features=decision.features,
        generated_at=datetime.now(UTC),
    )
    db.add(signal)
    db.commit()
    db.refresh(signal)
    return signal


def _finalize_open_position(
    db: Session,
    strategy: Strategy,
    instrument: Instrument,
    mode: str,
    quantity: int,
    fill_price: float,
    brokerage: float,
    taxes: float,
    stop_loss: float | None,
    take_profit: float | None,
    entry_at: datetime,
    entry_confidence: float | None = None,
) -> Position:
    """Shared by the broker-filled path and the manual (self-reported) path —
    both end up with the same fill_price/brokerage/taxes, just sourced
    differently."""
    position = Position(
        strategy_id=strategy.id,
        instrument_id=instrument.id,
        mode=mode,
        status=PositionStatus.OPEN,
        quantity=quantity,
        initial_quantity=quantity,
        entry_price=fill_price,
        entry_at=entry_at,
        stop_loss=stop_loss,
        initial_stop_loss=stop_loss,
        take_profit=take_profit,
        highest_price=fill_price,
        current_price=fill_price,
        total_charges=brokerage + taxes,
        entry_confidence=entry_confidence,
        last_confidence=entry_confidence,
    )
    db.add(position)
    db.commit()
    db.refresh(position)
    return position


def open_position(
    db: Session,
    strategy: Strategy,
    instrument: Instrument,
    signal: Signal,
    quantity: int,
) -> Position | None:
    """Place the entry order and, if it fills, create the position.

    The Order row is written before submission so a crash mid-flight leaves a
    record to reconcile against rather than an untracked broker order.
    """
    broker = get_broker()
    now = datetime.now(UTC)

    order = Order(
        signal_id=signal.id,
        strategy_id=strategy.id,
        instrument_id=instrument.id,
        mode=broker.mode,
        transaction_type=TransactionType.BUY,
        order_type=OrderType.MARKET,
        # CNC, not MIS: a swing position is held overnight, and MIS would be
        # auto-squared-off by the broker at 15:20 the same day.
        product=ProductType.CNC,
        quantity=quantity,
        status=OrderStatus.PENDING,
        placed_at=now,
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    request = OrderRequest(
        tradingsymbol=instrument.tradingsymbol,
        exchange=instrument.exchange,
        transaction_type=TransactionType.BUY,
        quantity=quantity,
        order_type=OrderType.MARKET,
        product=ProductType.CNC,
        tag=f"stml-{strategy.id}",
    )
    result = broker.place_order(request, db)

    order.broker_order_id = result.broker_order_id
    order.status = result.status
    order.filled_quantity = result.filled_quantity
    order.average_price = result.average_price
    order.brokerage = result.brokerage
    order.taxes = result.taxes
    order.slippage = result.slippage
    order.status_message = result.message
    if result.status == OrderStatus.COMPLETE:
        order.filled_at = now
    db.commit()

    if result.status != OrderStatus.COMPLETE:
        # Live orders legitimately return PENDING and are picked up later by
        # reconciliation; only the paper broker fills synchronously.
        log.info(
            "execution.entry.not_filled",
            symbol=instrument.tradingsymbol,
            status=result.status,
            message=result.message,
        )
        signal.rejection_reason = result.message
        db.commit()
        return None

    fill_price = result.average_price or signal.price
    position = _finalize_open_position(
        db,
        strategy,
        instrument,
        broker.mode,
        result.filled_quantity,
        fill_price,
        result.brokerage,
        result.taxes,
        signal.stop_loss,
        signal.take_profit,
        now,
        signal.confidence,
    )

    order.position_id = position.id
    signal.was_executed = True
    db.commit()

    log.info(
        "execution.entry.filled",
        symbol=instrument.tradingsymbol,
        qty=result.filled_quantity,
        price=fill_price,
        mode=broker.mode,
    )

    notifier.send_sync(
        _entry_message(instrument, position, signal, result, broker.mode),
        "fill",
    )
    return position


def manual_open_position(
    db: Session,
    strategy: Strategy,
    instrument: Instrument,
    quantity: int,
    entry_price: float,
    stop_loss: float | None = None,
    take_profit: float | None = None,
    brokerage: float | None = None,
    taxes: float | None = None,
    signal: Signal | None = None,
) -> Position:
    """Record a position the user filled themselves (e.g. an advisory-mode
    recommendation they acted on manually in Zerodha), rather than one this
    app placed through a broker.

    No Order row is created — there is no broker order to reconcile against.
    Charges default to the same paper cost-model estimate everything else
    uses (services/costs.py) when the caller doesn't supply their own.
    """
    now = datetime.now(UTC)

    if brokerage is None or taxes is None:
        default_brokerage, default_taxes = compute_charges(entry_price * quantity, TransactionType.BUY)
        brokerage = default_brokerage if brokerage is None else brokerage
        taxes = default_taxes if taxes is None else taxes

    # The strategy's own mode, not broker.mode — recording a real Zerodha
    # buy against a live-mode advisory strategy must tag it "live" even
    # while the broker itself is still in the paper phase, so it's tracked
    # (and shown) separately from paper-simulated positions rather than
    # silently collapsing into whichever mode the broker happens to be in.
    position = _finalize_open_position(
        db, strategy, instrument, strategy.mode, quantity, entry_price, brokerage, taxes,
        stop_loss, take_profit, now,
        signal.confidence if signal is not None else None,
    )

    if signal is not None:
        signal.was_executed = True
        db.commit()

    log.info(
        "execution.manual_entry.recorded",
        symbol=instrument.tradingsymbol,
        qty=quantity,
        price=entry_price,
        mode=strategy.mode,
    )

    notifier.send_sync(_manual_entry_message(instrument, position, strategy.mode), "fill")
    return position


def _finalize_close_position(
    db: Session,
    position: Position,
    instrument: Instrument,
    fill_price: float,
    exit_brokerage: float,
    exit_taxes: float,
    reason: ExitReason,
    closed_at: datetime,
    note: str | None = None,
) -> Trade:
    """Sell every share still held and close the position.

    Shared by the broker-filled path and the manual (self-reported) path —
    both end up computing the same P&L off a fill_price/brokerage/taxes,
    just sourced differently.

    For a position that never scaled out this is exactly the original
    arithmetic. For one that did, `position.total_charges` already holds only
    the entry charges belonging to the shares still held (the sold slice took
    its share — see _finalize_partial_close), so this Trade row is charged
    the right amount without any extra apportioning here.
    """
    sold_quantity = position.quantity
    exit_charges = exit_brokerage + exit_taxes
    # This exit's charges: the remaining entry-side charges plus the exit's own.
    total_charges = position.total_charges + exit_charges

    gross_pnl = (fill_price - position.entry_price) * sold_quantity
    net_pnl = gross_pnl - total_charges
    # Return is measured against capital deployed, so charges are correctly
    # reflected as a drag on the actual investment.
    invested = position.entry_price * sold_quantity
    return_pct = net_pnl / invested if invested else 0.0
    holding_days = max(0, (closed_at - position.entry_at).days)

    had_partial_exit = (
        position.initial_quantity is not None and position.quantity < position.initial_quantity
    )
    earlier_realized = 0.0
    earlier_charges = 0.0
    if had_partial_exit:
        # The closed row reports the whole position — both exits — so the
        # Positions page and anything else reading a closed row sees the same
        # totals the Trade rows add up to.
        earlier_realized = position.realized_pnl or 0.0
        earlier_charges = float(
            db.execute(
                select(func.coalesce(func.sum(Trade.charges), 0.0)).where(
                    Trade.position_id == position.id
                )
            ).scalar_one()
        )

    position.status = PositionStatus.CLOSED
    position.exit_price = fill_price
    position.exit_at = closed_at
    position.exit_reason = reason
    position.realized_pnl = earlier_realized + net_pnl
    position.unrealized_pnl = 0.0
    position.current_price = fill_price
    position.total_charges = earlier_charges + total_charges
    if had_partial_exit:
        # Nothing is held any more; a closed row's quantity means the size of
        # the position, as it always has.
        position.quantity = position.initial_quantity
    if note:
        position.notes = note

    trade = Trade(
        position_id=position.id,
        strategy_id=position.strategy_id,
        instrument_id=instrument.id,
        mode=position.mode,
        symbol=instrument.tradingsymbol,
        quantity=sold_quantity,
        entry_price=position.entry_price,
        exit_price=fill_price,
        entry_at=position.entry_at,
        exit_at=closed_at,
        holding_days=holding_days,
        gross_pnl=gross_pnl,
        charges=total_charges,
        net_pnl=net_pnl,
        return_pct=return_pct,
        exit_reason=reason,
        is_win=net_pnl > 0,
    )
    db.add(trade)
    db.commit()
    db.refresh(trade)
    return trade


def _finalize_partial_close(
    db: Session,
    position: Position,
    instrument: Instrument,
    quantity: int,
    fill_price: float,
    exit_brokerage: float,
    exit_taxes: float,
    reason: ExitReason,
    closed_at: datetime,
    note: str | None = None,
) -> Trade:
    """Sell `quantity` of the shares held, write that slice's Trade, and keep
    the position OPEN with the rest.

    Charge apportionment is the part that silently corrupts P&L if it is
    wrong. The entry order's charges were paid once, for every share. The
    sold slice takes its pro-rata share of them (quantity / held) plus all of
    this exit's own charges; the remainder of the entry charges stays on the
    position for the shares still held. Charging the slice the FULL entry
    charges — what reusing _finalize_close_position would do — counts them
    twice once the rest is sold, and drifts paper cash by the same amount,
    because get_available_cash() treats `total_charges` on an open position
    as capital still locked in it.

    A SCALE_OUT also raises the stop to at least the entry price: the profit
    on the sold half is banked, and the half still held should no longer be
    able to become a loss. The trailing stop keeps ratcheting from there.
    """
    held = position.quantity
    if not 0 < quantity < held:
        raise ValueError(f"Partial exit of {quantity} from a position holding {held}")

    entry_charge_share = position.total_charges * quantity / held
    charges = entry_charge_share + exit_brokerage + exit_taxes

    gross_pnl = (fill_price - position.entry_price) * quantity
    net_pnl = gross_pnl - charges
    invested = position.entry_price * quantity
    return_pct = net_pnl / invested if invested else 0.0
    holding_days = max(0, (closed_at - position.entry_at).days)

    if position.initial_quantity is None:
        # A row from before partial exits existed that the backfill missed —
        # freeze its size now, before the first reduction loses it.
        position.initial_quantity = held
    position.quantity = held - quantity
    position.total_charges = position.total_charges - entry_charge_share
    position.realized_pnl = (position.realized_pnl or 0.0) + net_pnl
    mark = position.current_price or fill_price
    position.unrealized_pnl = (mark - position.entry_price) * position.quantity

    if reason == ExitReason.SCALE_OUT:
        position.scaled_out_at = closed_at
        if position.stop_loss is None or position.stop_loss < position.entry_price:
            position.stop_loss = position.entry_price
    if note:
        position.notes = note

    trade = Trade(
        position_id=position.id,
        strategy_id=position.strategy_id,
        instrument_id=instrument.id,
        mode=position.mode,
        symbol=instrument.tradingsymbol,
        quantity=quantity,
        entry_price=position.entry_price,
        exit_price=fill_price,
        entry_at=position.entry_at,
        exit_at=closed_at,
        holding_days=holding_days,
        gross_pnl=gross_pnl,
        charges=charges,
        net_pnl=net_pnl,
        return_pct=return_pct,
        exit_reason=reason,
        is_win=net_pnl > 0,
    )
    db.add(trade)
    db.commit()
    db.refresh(trade)
    return trade


def close_position(
    db: Session,
    position: Position,
    exit_price: float | None,
    reason: ExitReason,
    note: str | None = None,
    quantity: int | None = None,
) -> Trade | None:
    """Exit a position (all of it, or `quantity` shares) and write the
    immutable Trade record for what was sold.

    `quantity` defaults to every share held, which is exactly the behaviour
    that existed before partial exits. A smaller quantity writes one Trade for
    that slice and leaves the position OPEN holding the rest; a quantity at or
    above what is held is simply a full close.
    """
    broker = get_broker()
    instrument = db.get(Instrument, position.instrument_id)
    if instrument is None:
        log.error("execution.exit.instrument_missing", position_id=position.id)
        return None

    held = position.quantity
    sell_quantity = held if quantity is None else min(int(quantity), held)
    if sell_quantity <= 0:
        raise ValueError(f"Cannot sell {quantity} shares of position {position.id}")

    now = datetime.now(UTC)

    order = Order(
        strategy_id=position.strategy_id,
        position_id=position.id,
        instrument_id=instrument.id,
        mode=broker.mode,
        transaction_type=TransactionType.SELL,
        order_type=OrderType.MARKET,
        product=ProductType.CNC,
        quantity=sell_quantity,
        status=OrderStatus.PENDING,
        placed_at=now,
    )
    db.add(order)
    db.commit()

    request = OrderRequest(
        tradingsymbol=instrument.tradingsymbol,
        exchange=instrument.exchange,
        transaction_type=TransactionType.SELL,
        quantity=sell_quantity,
        order_type=OrderType.MARKET,
        product=ProductType.CNC,
        tag=f"stml-exit-{position.id}",
    )
    result = broker.place_order(request, db)

    order.broker_order_id = result.broker_order_id
    order.status = result.status
    order.filled_quantity = result.filled_quantity
    order.average_price = result.average_price
    order.brokerage = result.brokerage
    order.taxes = result.taxes
    order.slippage = result.slippage
    order.status_message = result.message
    db.commit()

    if result.status != OrderStatus.COMPLETE:
        log.warning(
            "execution.exit.not_filled",
            symbol=instrument.tradingsymbol,
            status=result.status,
            message=result.message,
        )
        return None

    order.filled_at = now
    fill_price = result.average_price or exit_price or position.entry_price
    filled_quantity = result.filled_quantity or sell_quantity
    if filled_quantity < held:
        trade = _finalize_partial_close(
            db, position, instrument, filled_quantity, fill_price,
            result.brokerage, result.taxes, reason, now, note,
        )
        log.info(
            "execution.partial_exit.filled",
            symbol=instrument.tradingsymbol,
            qty=filled_quantity,
            remaining=position.quantity,
            pnl=round(trade.net_pnl, 2),
            reason=reason,
        )
        notifier.send_sync(
            _partial_exit_message(instrument, trade, position, reason, broker.mode), "fill"
        )
        return trade

    trade = _finalize_close_position(
        db, position, instrument, fill_price, result.brokerage, result.taxes, reason, now, note
    )

    log.info(
        "execution.exit.filled",
        symbol=instrument.tradingsymbol,
        pnl=round(trade.net_pnl, 2),
        return_pct=round(trade.return_pct, 4),
        reason=reason,
    )

    notifier.send_sync(
        _exit_message(instrument, trade, reason, broker.mode),
        "fill",
    )
    return trade


def manual_close_position(
    db: Session,
    position: Position,
    exit_price: float,
    reason: ExitReason = ExitReason.MANUAL,
    brokerage: float | None = None,
    taxes: float | None = None,
) -> Trade:
    """Record the exit fill for a position the user closed themselves.

    No Order row is created — there is no broker order to reconcile against.
    Charges default to the same paper cost-model estimate everything else
    uses (services/costs.py) when the caller doesn't supply their own.
    """
    instrument = db.get(Instrument, position.instrument_id)
    if instrument is None:
        raise ValueError(f"Instrument {position.instrument_id} not found for position {position.id}")

    if brokerage is None or taxes is None:
        default_brokerage, default_taxes = compute_charges(exit_price * position.quantity, TransactionType.SELL)
        brokerage = default_brokerage if brokerage is None else brokerage
        taxes = default_taxes if taxes is None else taxes

    now = datetime.now(UTC)
    trade = _finalize_close_position(db, position, instrument, exit_price, brokerage, taxes, reason, now)

    log.info(
        "execution.manual_exit.recorded",
        symbol=instrument.tradingsymbol,
        pnl=round(trade.net_pnl, 2),
        return_pct=round(trade.return_pct, 4),
        reason=reason,
    )

    notifier.send_sync(_exit_message(instrument, trade, reason, position.mode), "fill")
    return trade


def confidence_decay_status(
    entry_confidence: float | None,
    current_confidence: float,
    exit_confidence: float,
    already_alerted: bool,
    min_confidence: float | None = None,
    drop_threshold: float | None = None,
) -> str:
    """Pure decision: "alert" | "reset" | "none" — no DB, fully testable.

    Two conditions must BOTH hold before "alert": the drop from entry is at
    least drop_threshold, AND confidence has fallen into the "weakening"
    zone (the midpoint between min_confidence and exit_confidence). A single
    day's normal probability jitter right after a purchase (e.g. 66% -> 63%)
    must never trigger this on its own — only a real decline into genuinely
    weaker territory does.
    """
    min_confidence = settings.ML_MIN_CONFIDENCE if min_confidence is None else min_confidence
    drop_threshold = settings.CONFIDENCE_DECAY_ALERT_PCT if drop_threshold is None else drop_threshold

    if entry_confidence is None:
        return "none"

    warning_zone = (min_confidence + exit_confidence) / 2
    in_weak_zone = current_confidence < warning_zone
    drop = entry_confidence - current_confidence

    if in_weak_zone and drop >= drop_threshold:
        return "none" if already_alerted else "alert"
    if not in_weak_zone and already_alerted:
        return "reset"
    return "none"


def _check_confidence_decay(
    db: Session, position: Position, strategy: Strategy, instrument: Instrument,
    current_confidence: float | None, mode: str,
) -> None:
    """Warn once when a held position's confidence has genuinely declined.

    Neither the stop-loss nor the target reacts to the thesis itself
    weakening, only to price — this is the early warning for that gap.
    """
    if current_confidence is None:
        return
    position.last_confidence = current_confidence

    exit_confidence = float(strategy.params.get("exit_confidence", 0.35))
    status = confidence_decay_status(
        position.entry_confidence,
        current_confidence,
        exit_confidence,
        already_alerted=position.confidence_alert_sent_at is not None,
    )

    if status == "alert":
        position.confidence_alert_sent_at = datetime.now(UTC)
        db.commit()
        notifier.send_sync(
            _confidence_decay_message(instrument, position, current_confidence, mode), "signal"
        )
        return
    if status == "reset":
        position.confidence_alert_sent_at = None

    db.commit()


# Smaller than settings.CONFIDENCE_DECAY_ALERT_PCT (0.15) on purpose: this is
# a cosmetic "starting to ease" cue for the Positions page, not a trading
# decision or a notification trigger, so it's fine for it to catch smaller
# moves than the real alert does. 0.66 -> 0.63 (0.03) still reads as "hold" —
# consistent with confidence_decay_status() never firing on that jitter.
EARLY_DIP_DROP_PCT = 0.05


def position_action(
    entry_confidence: float | None,
    last_confidence: float | None,
    alert_sent: bool,
    holding_days: int,
    horizon_days: int | None,
    exit_confidence: float,
    exit_signal_pending: bool = False,
    min_confidence: float | None = None,
) -> tuple[str, str]:
    """Pure: the single "what should I do" read for one open position —
    what the Positions page shows instead of making the user cross-reference
    the Day column, the Confidence column, and a signal on a different page.

    Leads with the model's CURRENT, freshly re-evaluated confidence — not a
    fact about elapsed time. The model has no memory of its own earlier call;
    every day it re-asks "what's the probability of a move from here", so
    "day 5 of 5 and still red" is not itself informative — what matters is
    whether today's confidence still leans bullish, is fading toward the
    exit floor, or has already crossed it. Day count and any horizon-elapsed
    note are folded in as supporting detail, not the headline.

    Priority, strongest first: a real EXIT signal the strategy hasn't acted
    on (advisory mode only — an "auto" strategy closes automatically, so a
    still-open position can never actually have one) outranks an already-
    sent confidence-decay alert, which outranks the fresh directional read.
    """
    min_confidence = settings.ML_MIN_CONFIDENCE if min_confidence is None else min_confidence

    if exit_signal_pending:
        return "exit", "Exit signal — model wants out, not yet closed"

    horizon_note = ""
    if horizon_days is not None and holding_days >= horizon_days:
        horizon_note = f" (original {horizon_days}-day call has passed, day {holding_days})"

    if alert_sent:
        conf = f"{last_confidence:.0%}" if last_confidence is not None else "?"
        return "alert", f"Losing conviction ({conf} today) — alert already sent{horizon_note}"

    if last_confidence is None:
        detail = (
            f"day {holding_days} of {horizon_days}" if horizon_days is not None else f"day {holding_days}"
        )
        return "hold", f"Hold — {detail}, no fresh confidence reading yet"

    if last_confidence >= min_confidence:
        return (
            "bullish",
            f"Still bullish ({last_confidence:.0%} today) — model would buy this fresh right now"
            f"{horizon_note}",
        )

    warning_zone = (min_confidence + exit_confidence) / 2
    if last_confidence < warning_zone:
        return (
            "weak",
            f"Losing conviction ({last_confidence:.0%} today) — approaching exit level{horizon_note}",
        )

    if (
        entry_confidence is not None
        and entry_confidence - last_confidence >= EARLY_DIP_DROP_PCT
    ):
        return (
            "dip",
            f"Confidence easing ({entry_confidence:.0%} → {last_confidence:.0%}) today — "
            f"below the buy bar but not weak yet{horizon_note}",
        )

    return "hold", f"Neutral ({last_confidence:.0%} today) — below buy bar, holding steady{horizon_note}"


def process_decision(
    db: Session,
    strategy: Strategy,
    instrument: Instrument,
    decision,
    *,
    ranked_out_reason: str | None = None,
) -> Signal | None:
    """Route one strategy decision through risk checks to execution.

    Always records the signal — including rejected ones, with the reason —
    because a strategy's rejected entries are as much a part of its track record
    as its filled ones.

    `ranked_out_reason` is set by the scan loop (engine.run_strategy /
    backtest.run_backtest) when this BUY lost out to higher-confidence
    candidates from the same scan — see services/risk.rank_buy_candidates().
    Short-circuits straight to a rejected signal, skipping the risk/position
    queries below entirely since this candidate was never going to be acted
    on regardless of what they'd say.
    """
    broker = get_broker()
    # The strategy's own mode, not necessarily broker.mode: an advisory
    # strategy tracking real trades is scanned regardless of the broker's
    # current paper/live mode (see engine.run_all_active), and every bit of
    # its bookkeeping below — existing positions, exposure, signals — must
    # stay scoped to that strategy's own mode rather than whatever the
    # broker happens to be running right now.
    mode = strategy.mode

    if decision.signal == SignalType.BUY and ranked_out_reason:
        signal = record_signal(db, strategy, instrument, decision, mode)
        signal.rejection_reason = ranked_out_reason
        db.commit()
        return signal

    # Scoped by strategy, not just mode+instrument: each strategy manages its
    # own book independently (the SMA-crossover benchmark and ml_swing can
    # both hold the same symbol at once — that's the point of running them
    # side by side). Pyramiding also means this can legitimately be more than
    # one row, so it's a list, not a single scalar.
    existing_positions = list(
        db.execute(
            select(Position).where(
                Position.mode == mode,
                Position.strategy_id == strategy.id,
                Position.instrument_id == instrument.id,
                Position.status == PositionStatus.OPEN,
            )
        )
        .scalars()
        .all()
    )

    # Track the model's freshest read on anything already held, regardless of
    # what today's decision turns out to be — a currently-open position can
    # just as easily re-trigger BUY (rejected below as a duplicate) or EXIT
    # as it can HOLD, and the Positions page's "what does the model think
    # right now" read must not go stale just because today's verdict wasn't
    # literally HOLD. (Previously scoped to the HOLD branch only, which is
    # exactly why a position the model was newly bullish enough on to BUY
    # again showed a stale "no reading yet" instead of that fresh number.)
    # SignalDecision.confidence is conviction *in the decision*, and on an EXIT
    # ml_swing sets it to `1 - probability` — conviction in getting out. Stored
    # raw, that inverts the meaning of last_confidence exactly where it matters
    # most: a stock the model rates 25% shows as 0.75, the highest number on
    # the page, while the badge says Exit. It also silently disabled the decay
    # alert, since confidence_decay_status compares this value against the weak
    # zone and an inverted 0.75 never looks weak.
    #
    # Positions want the model's read on *the stock*, so undo the inversion.
    bullish_confidence = decision.confidence
    if (
        decision.signal in (SignalType.EXIT, SignalType.SELL)
        and bullish_confidence is not None
    ):
        bullish_confidence = round(1.0 - bullish_confidence, 3)

    for position in existing_positions:
        _check_confidence_decay(db, position, strategy, instrument, bullish_confidence, mode)

    if decision.signal == SignalType.HOLD:
        return record_signal(db, strategy, instrument, decision, mode)

    if decision.signal in (SignalType.EXIT, SignalType.SELL):
        signal = record_signal(db, strategy, instrument, decision, mode)
        if not existing_positions:
            signal.rejection_reason = "No open position to exit"
            db.commit()
            return signal
        if strategy.execution_mode == "advisory":
            signal.advisory_only = True
            db.commit()
            for position in existing_positions:
                notifier.send_sync(
                    _advisory_exit_message(instrument, position, decision.reason, mode), "signal"
                )
            return signal
        # An EXIT decision is strategy-level ("get out of this name"), so
        # every open tranche closes together, not just the first one found.
        executed = False
        for position in existing_positions:
            trade = close_position(db, position, decision.price, ExitReason.SIGNAL_EXIT, decision.reason)
            executed = executed or trade is not None
        signal.was_executed = executed
        db.commit()
        return signal

    # BUY
    existing_exposure = 0.0
    if existing_positions:
        # Pyramiding is opt-in per strategy, and only into a book that is
        # currently working — scaling into a loser is not pyramiding, it is
        # averaging down, which this deliberately does not do.
        total_unrealized = sum(p.unrealized_pnl or 0.0 for p in existing_positions)
        pyramiding_allowed = strategy.allow_pyramiding and total_unrealized > 0
        if not pyramiding_allowed:
            signal = record_signal(db, strategy, instrument, decision, mode)
            signal.rejection_reason = "Position already open"
            db.commit()
            return signal
        existing_exposure = risk.open_exposure_value(db, mode, strategy.id, instrument.id)

    total_value, cash = portfolio_value_and_cash(db, mode)
    verdict = risk.check_entry(
        db=db,
        mode=mode,
        instrument_id=instrument.id,
        price=decision.price,
        stop_loss=decision.stop_loss,
        portfolio_value=total_value,
        available_cash=cash,
        strategy=strategy,
        existing_exposure=existing_exposure,
    )

    signal = record_signal(db, strategy, instrument, decision, mode, verdict.quantity)

    if not verdict.allowed:
        signal.rejection_reason = verdict.reason
        # ---- risk events (portfolio risk layer) ----
        # Every check_entry rejection is also logged as a RiskEvent, committed
        # with the signal so the two cannot disagree. check_entry itself stays
        # write-free. (The two pre-filters above — ranked out, position already
        # open — are routine scan outcomes, not risk limits, and are not logged.)
        system_state.record_risk_event(
            db,
            mode=mode,
            rule=verdict.rule or "OTHER",
            reason=verdict.reason,
            strategy_id=strategy.id,
            instrument_id=instrument.id,
            symbol=instrument.tradingsymbol,
            amount_inr=verdict.amount_inr,
        )
        db.commit()
        log.info(
            "execution.entry.blocked",
            symbol=instrument.tradingsymbol,
            rule=verdict.rule,
            reason=verdict.reason,
        )
        return signal

    if strategy.execution_mode == "advisory":
        signal.advisory_only = True
        db.commit()
        notifier.send_sync(
            _advisory_entry_message(instrument, decision, strategy, verdict.quantity, mode),
            "signal",
        )
        return signal

    notifier.send_sync(
        _signal_message(instrument, decision, strategy, verdict.quantity, mode), "signal"
    )
    open_position(db, strategy, instrument, signal, verdict.quantity)
    return signal


def trail_stop(position: Position) -> None:
    """Ratchet the active stop up as the position moves favorably, keeping
    the same rupee distance below the highest price seen since entry that
    the strategy originally set at entry. Never moves the stop down.

    Added after the first six paper trades showed a real asymmetry: the one
    winner was cashed out on a 1-day confidence-exit, while three losers
    were held long enough to fall most of the way to their original,
    never-moving stop. `highest_price` was already being tracked on every
    tick for exactly this purpose — see its docstring on the Position model
    — but nothing ever read it. This closes that gap: once a trade is
    ahead, its downside tightens instead of staying fixed at the original
    entry-time risk.
    """
    if position.initial_stop_loss is None or position.stop_loss is None or position.highest_price is None:
        return
    distance = position.entry_price - position.initial_stop_loss
    if distance <= 0:
        return
    trailed = position.highest_price - distance
    if trailed > position.stop_loss:
        position.stop_loss = trailed


def _has_pending_exit_order(db: Session, position: Position) -> bool:
    """True while a sell for this position is still waiting at the broker.

    Only matters live: a Kite order comes back PENDING and is finished later
    by reconciliation, and `scaled_out_at` is set only once it fills. Without
    this check, the 60-second exit job would see the position still
    un-scaled-out and send a second half-sell every minute until the first
    one filled. Paper fills synchronously, so this is always False there.
    """
    return (
        db.execute(
            select(Order.id).where(
                Order.position_id == position.id,
                Order.transaction_type == TransactionType.SELL,
                Order.status.in_([OrderStatus.PENDING, OrderStatus.OPEN]),
            )
        ).first()
        is not None
    )


def check_exits(db: Session) -> list[Trade]:
    """Evaluate stop-loss, target and time-stop conditions on open positions.

    Runs on the intraday schedule so a stop is honoured during the session
    rather than at the next daily scan — for a 5% stop that difference is
    material.

    Scoped to positions in the broker's current mode, plus every open
    advisory-strategy position regardless of mode — an advisory position
    never reaches close_position() below (it always hits the early
    "advisory" continue and just alerts), so including a live-mode one here
    while the broker is still in paper mode is safe and is exactly what
    keeps a manually-recorded real trade's price/trailing-stop/exit alerts
    updating on the same intraday schedule as everything else.

    Exits run even while new entries are halted (the kill switch) — halting
    must never trap capital in positions heading for their stops. They stop
    only if `system_state.exits_enabled` has been switched off, which is a
    separate, deliberate act: with exits off, no stop-loss, target or time
    stop fires, and a falling position can lose far more than its stop was
    set to allow. A loud warning is logged on every run while it is off.

    Order of checks on each price, first match wins: stop-loss, final
    target, time stop (all full exits), then the partial scale-out. The
    scale-out comes last on purpose:
    * a tick that is at or past the final target sells everything in one
      order — one depository fee — rather than selling half and then the
      other half a moment later at the same price;
    * a position past its time stop is closing anyway, so selling half of it
      first would only pay an extra fee;
    * a tick that scales out never also fully exits: after the partial sale
      the loop moves on, and the next price update judges the remainder.
    The time stop and the scale-out are per strategy (services/exit_policy.py);
    a strategy that sets neither keeps the 60-day stop and never scales out.
    """
    if not system_state.get_state(db).exits_enabled:
        log.warning(
            "execution.check_exits.DISABLED",
            message="Exits are switched OFF — no stop-loss, target or time stop is being "
            "enforced. Open positions are unprotected until exits are re-enabled.",
        )
        return []

    broker = get_broker()
    mode = broker.mode
    positions = list(
        db.execute(
            select(Position)
            .join(Strategy, Strategy.id == Position.strategy_id, isouter=True)
            .where(
                Position.status == PositionStatus.OPEN,
                (Position.mode == mode) | (Strategy.execution_mode == "advisory"),
            )
        )
        .scalars()
        .all()
    )
    if not positions:
        return []

    instruments = {p.instrument_id: db.get(Instrument, p.instrument_id) for p in positions}
    keys = [i.symbol_key for i in instruments.values() if i is not None]
    prices = broker.get_ltp(keys, db) if keys else {}

    closed: list[Trade] = []
    for position in positions:
        instrument = instruments.get(position.instrument_id)
        if instrument is None:
            continue
        price = prices.get(instrument.symbol_key)
        if price is None:
            continue

        position.current_price = price
        position.unrealized_pnl = (price - position.entry_price) * position.quantity
        if position.highest_price is None or price > position.highest_price:
            position.highest_price = price

        trail_stop(position)

        policy = exit_policy_for(position.strategy.params if position.strategy is not None else None)
        is_advisory = position.strategy is not None and position.strategy.execution_mode == "advisory"

        reason: ExitReason | None = None
        if position.stop_loss and price <= position.stop_loss:
            reason = ExitReason.STOP_LOSS_HIT
        elif position.take_profit and price >= position.take_profit:
            reason = ExitReason.TARGET_HIT
        elif (datetime.now(UTC) - position.entry_at).days >= policy.time_stop_days:
            # Capital tied up this long in a swing trade is a failed thesis,
            # regardless of whether it is slightly up or down.
            reason = ExitReason.TIME_STOP

        if reason is None:
            if is_advisory:
                # Advisory positions are the user's own; only the full-exit
                # alerts above apply to them.
                continue
            sell = scale_out_quantity(
                policy,
                entry_price=position.entry_price,
                price=price,
                quantity=position.quantity,
                already_scaled_out=position.scaled_out_at is not None,
            )
            if sell and not _has_pending_exit_order(db, position):
                trade = close_position(db, position, price, ExitReason.SCALE_OUT, quantity=sell)
                if trade:
                    closed.append(trade)
            continue

        if is_advisory:
            # Alert once, not every 60s — the position stays open until the
            # user records the exit via manual_close_position().
            if position.advisory_alert_sent_at is None:
                notifier.send_sync(_advisory_exit_message(instrument, position, reason, mode), "signal")
                position.advisory_alert_sent_at = datetime.now(UTC)
            continue

        trade = close_position(db, position, price, reason)
        if trade:
            closed.append(trade)

    db.commit()
    return closed


def reconcile_pending_orders(db: Session) -> dict[str, int]:
    """Catch up every order still PENDING/OPEN against its real broker status.

    The gap this closes: KiteBroker.place_order() always returns PENDING —
    Kite's REST API confirms an order was *accepted*, never that it filled —
    so open_position()/close_position() defer creating the Position/Trade
    until "the reconciliation job" (their own comment) checks back. That job
    never existed; the only thing that did was the /orders/sync endpoint,
    and even that only patched the Order row's status without ever finishing
    the Position/Trade it was blocking on. Net effect: a live order could
    fill for real at Zerodha — real money, real shares — while the app
    stayed permanently unaware it existed. This is what actually finishes
    the job, called from both that endpoint and job_reconcile_orders.

    A no-op for paper mode, since PaperBroker fills synchronously and never
    leaves an order non-terminal in the first place.
    """
    broker = get_broker()
    pending = list(
        db.execute(
            select(Order).where(
                Order.mode == broker.mode,
                Order.status.in_([OrderStatus.PENDING, OrderStatus.OPEN]),
                Order.broker_order_id.isnot(None),
                Order.broker_order_id != "",
            )
        )
        .scalars()
        .all()
    )

    counts = {"checked": len(pending), "filled": 0, "failed": 0, "unchanged": 0}

    for order in pending:
        result = broker.get_order_status(order.broker_order_id, db)
        if result is None or result.status == order.status:
            counts["unchanged"] += 1
            continue

        order.status = result.status
        order.filled_quantity = result.filled_quantity
        order.average_price = result.average_price
        order.status_message = result.message

        if result.status == OrderStatus.COMPLETE:
            order.filled_at = order.filled_at or datetime.now(UTC)
            _finish_reconciled_order(db, order, result)
            counts["filled"] += 1
        elif result.status in (OrderStatus.REJECTED, OrderStatus.CANCELLED):
            _fail_reconciled_order(db, order, result)
            counts["failed"] += 1

    db.commit()
    log.info("execution.reconcile.done", **counts)
    return counts


def _finish_reconciled_order(db: Session, order: Order, result: OrderResult) -> None:
    """An order just reached COMPLETE that placement couldn't finish
    synchronously — do the part it deferred: create the Position for an
    entry, close it for a full exit, or record the slice sold for a partial
    (scale-out) exit while leaving it open. Idempotent — safe to call again
    if a later tick somehow sees the same transition twice."""
    instrument = db.get(Instrument, order.instrument_id)
    if instrument is None:
        log.error("execution.reconcile.instrument_missing", order_id=order.id)
        return

    fill_price = result.average_price or order.price
    if fill_price is None:
        log.error("execution.reconcile.no_fill_price", order_id=order.id)
        return

    filled_qty = result.filled_quantity or order.quantity

    # Only estimate what the broker did not tell us. Previously this
    # overwrote whatever the broker reported with the *paper* model's guess,
    # so a real fill's real charges were discarded in favour of an
    # approximation — and nothing said so.
    if result.brokerage or result.taxes:
        brokerage, taxes = result.brokerage, result.taxes
    else:
        brokerage, taxes = compute_charges(fill_price * filled_qty, order.transaction_type)
        if settings.is_live_trading:
            # Kite's order API does not return the charge breakdown, so a live
            # fill genuinely has to be estimated. Say so, rather than letting
            # an estimate masquerade as a settled figure in the P&L.
            log.info(
                "execution.reconcile.charges_estimated",
                order_id=order.id,
                brokerage=brokerage,
                taxes=taxes,
            )

    order.brokerage = brokerage
    order.taxes = taxes
    result.brokerage = brokerage
    result.taxes = taxes

    if order.transaction_type == TransactionType.BUY:
        if order.position_id is not None:
            return  # already finished
        signal = db.get(Signal, order.signal_id) if order.signal_id else None
        strategy = db.get(Strategy, order.strategy_id) if order.strategy_id else None
        if strategy is None:
            log.error("execution.reconcile.strategy_missing", order_id=order.id)
            return

        position = _finalize_open_position(
            db, strategy, instrument, order.mode, filled_qty, fill_price, brokerage, taxes,
            signal.stop_loss if signal else None,
            signal.take_profit if signal else None,
            order.filled_at or datetime.now(UTC),
            signal.confidence if signal else None,
        )
        order.position_id = position.id
        if signal is not None:
            signal.was_executed = True

        log.info(
            "execution.reconcile.entry_filled",
            symbol=instrument.tradingsymbol, order_id=order.id, price=fill_price, qty=filled_qty,
        )
        notifier.send_sync(_entry_message(instrument, position, signal, result, order.mode), "fill")
    else:
        if order.position_id is None:
            log.error("execution.reconcile.exit_without_position", order_id=order.id)
            return
        position = db.get(Position, order.position_id)
        if position is None or position.status != PositionStatus.OPEN:
            return  # already closed some other way

        closed_at = order.filled_at or datetime.now(UTC)

        # Idempotency for a SELL cannot be "did this shrink the position",
        # because the first call already does that shrinking — a retry then
        # sees filled_qty == the now-smaller position.quantity and falls
        # through to the full-close branch below, double-booking the trade.
        # A prior Trade for this exact (position, exit moment, quantity) is
        # the one signal that survives the position having already mutated.
        already_recorded = db.execute(
            select(Trade.id).where(
                Trade.position_id == position.id,
                Trade.exit_at == closed_at,
                Trade.quantity == filled_qty,
            )
        ).first()
        if already_recorded is not None:
            return

        if filled_qty < position.quantity:
            # A partial exit order. The only thing that places one is the
            # first-target scale-out in check_exits, so it is recorded as
            # that — and the position stays open holding the rest. Treating
            # it as a full close (as this branch used to for every sell)
            # would mark shares still held at the broker as sold.
            trade = _finalize_partial_close(
                db, position, instrument, filled_qty, fill_price, brokerage, taxes,
                ExitReason.SCALE_OUT, closed_at,
            )
            log.info(
                "execution.reconcile.partial_exit_filled",
                symbol=instrument.tradingsymbol, order_id=order.id, price=fill_price,
                qty=filled_qty, remaining=position.quantity,
            )
            notifier.send_sync(
                _partial_exit_message(instrument, trade, position, ExitReason.SCALE_OUT, order.mode),
                "fill",
            )
            return

        trade = _finalize_close_position(
            db, position, instrument, fill_price, brokerage, taxes,
            ExitReason.MANUAL, closed_at,
        )
        log.info(
            "execution.reconcile.exit_filled",
            symbol=instrument.tradingsymbol, order_id=order.id, price=fill_price,
        )
        notifier.send_sync(_exit_message(instrument, trade, ExitReason.MANUAL, order.mode), "fill")


def _fail_reconciled_order(db: Session, order: Order, result: OrderResult) -> None:
    """An order that was never going to fill — surfaced as a signal rejection
    (for an entry) so its history stays honest, and always as a Telegram
    alert, since a rejected live order is exactly the kind of thing that
    must not fail silently."""
    if order.signal_id:
        signal = db.get(Signal, order.signal_id)
        if signal is not None:
            signal.rejection_reason = result.message or f"Order {result.status}"

    log.warning(
        "execution.reconcile.order_failed",
        order_id=order.id, status=str(result.status), message=result.message,
    )
    notifier.send_sync(
        f"⚠️ <b>Order {result.status}</b> — instrument {order.instrument_id}, "
        f"order {order.id}\n{result.message or 'No reason given.'}",
        "error",
    )


# ------------------------------------------------------------- messages --


def _signal_message(instrument, decision, strategy, quantity, mode) -> str:
    icon = {"BUY": "🟢", "SELL": "🔴", "EXIT": "🟠"}.get(str(decision.signal), "⚪")
    badge = "📝 PAPER" if mode == "paper" else "💰 <b>LIVE</b>"
    lines = [
        f"{icon} <b>{decision.signal} · {instrument.tradingsymbol}</b>  ({badge})",
        "",
        f"Price: <b>₹{decision.price:,.2f}</b>",
        f"Quantity: <b>{quantity:,}</b>  (₹{decision.price * quantity:,.0f})",
    ]
    if decision.confidence is not None:
        lines.append(f"Confidence: <b>{decision.confidence:.1%}</b>")
    if decision.stop_loss:
        lines.append(
            f"Stop: ₹{decision.stop_loss:,.2f}  ({decision.stop_loss / decision.price - 1:+.1%})"
        )
    if decision.take_profit:
        lines.append(
            f"Target: ₹{decision.take_profit:,.2f}  "
            f"({decision.take_profit / decision.price - 1:+.1%})"
        )
    lines += ["", f"Strategy: <i>{strategy.name}</i>", f"Reason: {decision.reason}"]
    return "\n".join(lines)


def _entry_message(instrument, position, signal, result, mode) -> str:
    badge = "📝 PAPER" if mode == "paper" else "💰 <b>LIVE</b>"
    return (
        f"✅ <b>ENTERED · {instrument.tradingsymbol}</b>  ({badge})\n\n"
        f"BUY <b>{position.quantity:,}</b> @ <b>₹{position.entry_price:,.2f}</b>\n"
        f"Value: ₹{position.entry_price * position.quantity:,.2f}\n"
        f"Charges: ₹{result.brokerage + result.taxes:,.2f}\n"
        f"Stop: ₹{position.stop_loss or 0:,.2f}  ·  Target: ₹{position.take_profit or 0:,.2f}\n"
        f"Order: <code>{result.broker_order_id}</code>"
    )


def _exit_message(instrument, trade, reason, mode) -> str:
    icon = "🎯" if trade.net_pnl >= 0 else "🛑"
    badge = "📝 PAPER" if mode == "paper" else "💰 <b>LIVE</b>"
    return (
        f"{icon} <b>CLOSED · {instrument.tradingsymbol}</b>  ({badge})\n\n"
        f"Entry ₹{trade.entry_price:,.2f} → Exit ₹{trade.exit_price:,.2f}\n"
        f"Quantity: {trade.quantity:,}\n"
        f"P&amp;L: <b>₹{trade.net_pnl:,.2f}</b>  (<b>{trade.return_pct:+.2%}</b>)\n"
        f"Held: {trade.holding_days} days\n"
        f"Reason: {reason}"
    )


def _partial_exit_message(instrument, trade, position, reason, mode) -> str:
    """Plain English on purpose — the owner reads these on a phone without a
    trading background, so "stop-loss" becomes "sell-if-wrong price"."""
    badge = "📝 PAPER" if mode == "paper" else "💰 <b>LIVE</b>"
    symbol = instrument.tradingsymbol
    held_before = trade.quantity + position.quantity
    portion = "half" if trade.quantity * 2 == held_before else f"{trade.quantity:,} of {held_before:,} shares"
    gain = trade.exit_price / trade.entry_price - 1 if trade.entry_price else 0.0

    headline = f"Sold {portion} of {symbol} at {gain:+.1%}"
    stop = position.stop_loss
    if reason == ExitReason.SCALE_OUT and stop is not None:
        if abs(stop - position.entry_price) < 0.005:
            headline += " and moved its sell-if-wrong price up to what you paid"
        else:
            headline += f" — its sell-if-wrong price is ₹{stop:,.2f}, already above what you paid"
    lines = [
        f"💰 <b>BOOKED PART PROFIT · {symbol}</b>  ({badge})",
        "",
        f"{headline}.",
        "",
        f"Sold {trade.quantity:,} at ₹{trade.exit_price:,.2f} (bought at ₹{trade.entry_price:,.2f})",
        f"Profit on those, after charges: <b>₹{trade.net_pnl:,.2f}</b>",
        f"Still holding {position.quantity:,}"
        + (f", aiming for ₹{position.take_profit:,.2f}" if position.take_profit else ""),
    ]
    return "\n".join(lines)


def _manual_entry_message(instrument, position, mode) -> str:
    badge = "📝 PAPER" if mode == "paper" else "💰 <b>LIVE</b>"
    return (
        f"✅ <b>RECORDED · {instrument.tradingsymbol}</b>  ({badge})\n\n"
        f"BUY <b>{position.quantity:,}</b> @ <b>₹{position.entry_price:,.2f}</b>  "
        f"(self-reported fill)\n"
        f"Value: ₹{position.entry_price * position.quantity:,.2f}\n"
        f"Charges: ₹{position.total_charges:,.2f}\n"
        f"Stop: ₹{position.stop_loss or 0:,.2f}  ·  Target: ₹{position.take_profit or 0:,.2f}"
    )


def _advisory_entry_message(instrument, decision, strategy, quantity, mode) -> str:
    badge = "📝 PAPER" if mode == "paper" else "💰 <b>LIVE</b>"
    lines = [
        f"🔔 <b>RECOMMENDATION · {instrument.tradingsymbol}</b>  ({badge})",
        "",
        f"Suggested price: <b>₹{decision.price:,.2f}</b>",
        f"Suggested quantity: <b>{quantity:,}</b>  (₹{decision.price * quantity:,.0f})",
    ]
    if decision.confidence is not None:
        lines.append(f"Confidence: <b>{decision.confidence:.1%}</b>")
    if decision.stop_loss:
        lines.append(
            f"Stop: ₹{decision.stop_loss:,.2f}  ({decision.stop_loss / decision.price - 1:+.1%})"
        )
    if decision.take_profit:
        lines.append(
            f"Target: ₹{decision.take_profit:,.2f}  "
            f"({decision.take_profit / decision.price - 1:+.1%})"
        )
    lines += [
        "",
        "Enter at tomorrow's ~09:15 IST open, at/near this price, or as a "
        "limit order at it — the model only judges completed daily bars, it "
        "has no intraday timing signal beyond that.",
        "",
        f"Strategy: <i>{strategy.name}</i>",
        f"Reason: {decision.reason}",
        "",
        "Took this trade? Record it: POST /portfolio/positions/manual",
    ]
    return "\n".join(lines)


def _advisory_exit_message(instrument, position, reason, mode) -> str:
    badge = "📝 PAPER" if mode == "paper" else "💰 <b>LIVE</b>"
    return (
        f"🔔 <b>EXIT RECOMMENDED · {instrument.tradingsymbol}</b>  ({badge})\n\n"
        f"Reason: {reason}\n"
        f"Entry: ₹{position.entry_price:,.2f}  ·  Current: ₹{position.current_price or 0:,.2f}\n"
        f"Quantity: {position.quantity:,}\n\n"
        f"Sold this? Record it: POST /portfolio/positions/{position.id}/manual-close"
    )


def _confidence_decay_message(instrument, position, current_confidence, mode) -> str:
    badge = "📝 PAPER" if mode == "paper" else "💰 <b>LIVE</b>"
    drop = (position.entry_confidence or 0.0) - current_confidence
    return (
        f"⚠️ <b>CONFIDENCE FALLING · {instrument.tradingsymbol}</b>  ({badge})\n\n"
        f"Entry confidence: <b>{position.entry_confidence:.0%}</b> → now "
        f"<b>{current_confidence:.0%}</b>  (down {drop:.0%})\n\n"
        f"This is a warning, not an exit — price hasn't hit the stop or target, "
        f"but the model's conviction is fading before either of those trigger. "
        f"Your call whether to trim or wait.\n\n"
        f"Entry: ₹{position.entry_price:,.2f}  ·  "
        f"Current: ₹{position.current_price or position.entry_price:,.2f}\n"
        f"Stop: ₹{position.stop_loss or 0:,.2f}  ·  Target: ₹{position.take_profit or 0:,.2f}"
    )
