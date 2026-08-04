"""Execution: turning signals into orders, positions and trades.

This is the only module that writes Order/Position/Trade rows. Strategies decide
*what*, risk decides *how much*, and this decides *whether and when* — keeping
those three concerns separate is what makes the paper phase's results
attributable to the strategy rather than to the plumbing.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.brokers import OrderRequest, get_broker
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
from swing_trade_ml.services import risk
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
        reason=decision.reason,
        features=decision.features,
        generated_at=datetime.now(UTC),
    )
    db.add(signal)
    db.commit()
    db.refresh(signal)
    return signal


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
    position = Position(
        strategy_id=strategy.id,
        instrument_id=instrument.id,
        mode=broker.mode,
        status=PositionStatus.OPEN,
        quantity=result.filled_quantity,
        entry_price=fill_price,
        entry_at=now,
        stop_loss=signal.stop_loss,
        take_profit=signal.take_profit,
        highest_price=fill_price,
        current_price=fill_price,
        total_charges=result.brokerage + result.taxes,
    )
    db.add(position)
    db.commit()
    db.refresh(position)

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


def close_position(
    db: Session,
    position: Position,
    exit_price: float | None,
    reason: ExitReason,
    note: str | None = None,
) -> Trade | None:
    """Exit a position and write the immutable Trade record."""
    broker = get_broker()
    instrument = db.get(Instrument, position.instrument_id)
    if instrument is None:
        log.error("execution.exit.instrument_missing", position_id=position.id)
        return None

    now = datetime.now(UTC)

    order = Order(
        strategy_id=position.strategy_id,
        position_id=position.id,
        instrument_id=instrument.id,
        mode=broker.mode,
        transaction_type=TransactionType.SELL,
        order_type=OrderType.MARKET,
        product=ProductType.CNC,
        quantity=position.quantity,
        status=OrderStatus.PENDING,
        placed_at=now,
    )
    db.add(order)
    db.commit()

    request = OrderRequest(
        tradingsymbol=instrument.tradingsymbol,
        exchange=instrument.exchange,
        transaction_type=TransactionType.SELL,
        quantity=position.quantity,
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
    exit_charges = result.brokerage + result.taxes
    total_charges = position.total_charges + exit_charges

    gross_pnl = (fill_price - position.entry_price) * position.quantity
    net_pnl = gross_pnl - total_charges
    # Return is measured against capital deployed, so charges are correctly
    # reflected as a drag on the actual investment.
    invested = position.entry_price * position.quantity
    return_pct = net_pnl / invested if invested else 0.0
    holding_days = max(0, (now - position.entry_at).days)

    position.status = PositionStatus.CLOSED
    position.exit_price = fill_price
    position.exit_at = now
    position.exit_reason = reason
    position.realized_pnl = net_pnl
    position.unrealized_pnl = 0.0
    position.current_price = fill_price
    position.total_charges = total_charges
    if note:
        position.notes = note

    trade = Trade(
        position_id=position.id,
        strategy_id=position.strategy_id,
        instrument_id=instrument.id,
        mode=broker.mode,
        symbol=instrument.tradingsymbol,
        quantity=position.quantity,
        entry_price=position.entry_price,
        exit_price=fill_price,
        entry_at=position.entry_at,
        exit_at=now,
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

    log.info(
        "execution.exit.filled",
        symbol=instrument.tradingsymbol,
        pnl=round(net_pnl, 2),
        return_pct=round(return_pct, 4),
        reason=reason,
    )

    notifier.send_sync(
        _exit_message(instrument, trade, reason, broker.mode),
        "fill",
    )
    return trade


def process_decision(
    db: Session, strategy: Strategy, instrument: Instrument, decision
) -> Signal | None:
    """Route one strategy decision through risk checks to execution.

    Always records the signal — including rejected ones, with the reason —
    because a strategy's rejected entries are as much a part of its track record
    as its filled ones.
    """
    broker = get_broker()
    mode = broker.mode

    if decision.signal == SignalType.HOLD:
        return record_signal(db, strategy, instrument, decision, mode)

    existing = db.execute(
        select(Position).where(
            Position.mode == mode,
            Position.instrument_id == instrument.id,
            Position.status == PositionStatus.OPEN,
        )
    ).scalar_one_or_none()

    if decision.signal in (SignalType.EXIT, SignalType.SELL):
        signal = record_signal(db, strategy, instrument, decision, mode)
        if existing is None:
            signal.rejection_reason = "No open position to exit"
            db.commit()
            return signal
        trade = close_position(db, existing, decision.price, ExitReason.SIGNAL_EXIT, decision.reason)
        signal.was_executed = trade is not None
        db.commit()
        return signal

    # BUY
    if existing is not None:
        signal = record_signal(db, strategy, instrument, decision, mode)
        signal.rejection_reason = "Position already open"
        db.commit()
        return signal

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
    )

    signal = record_signal(db, strategy, instrument, decision, mode, verdict.quantity)

    if not verdict.allowed:
        signal.rejection_reason = verdict.reason
        db.commit()
        log.info(
            "execution.entry.blocked",
            symbol=instrument.tradingsymbol,
            reason=verdict.reason,
        )
        return signal

    notifier.send_sync(
        _signal_message(instrument, decision, strategy, verdict.quantity, mode), "signal"
    )
    open_position(db, strategy, instrument, signal, verdict.quantity)
    return signal


def check_exits(db: Session) -> list[Trade]:
    """Evaluate stop-loss, target and time-stop conditions on open positions.

    Runs on the intraday schedule so a stop is honoured during the session
    rather than at the next daily scan — for a 5% stop that difference is
    material.
    """
    broker = get_broker()
    mode = broker.mode
    positions = list(
        db.execute(
            select(Position).where(Position.mode == mode, Position.status == PositionStatus.OPEN)
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

        reason: ExitReason | None = None
        if position.stop_loss and price <= position.stop_loss:
            reason = ExitReason.STOP_LOSS_HIT
        elif position.take_profit and price >= position.take_profit:
            reason = ExitReason.TARGET_HIT
        elif (datetime.now(UTC) - position.entry_at).days >= 60:
            # Capital tied up for 60 days in a swing trade is a failed thesis,
            # regardless of whether it is slightly up or down.
            reason = ExitReason.TIME_STOP

        if reason is not None:
            trade = close_position(db, position, price, reason)
            if trade:
                closed.append(trade)

    db.commit()
    return closed


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
