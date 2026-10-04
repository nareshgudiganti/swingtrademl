"""M18 stages 2 and 3: the owner's OK before a brain idea is bought.

The scan path never orders for the brain ("brain" is always advisory there,
core/strategy_policy.py). This module is the ONLY place an order is placed for
it, and only through services.execution.open_position after fresh checks. The
automatic stage is this same path with the system pressing Approve; only the
owner can choose that stage (stage.py).

Timing (owner decision, 2026-10-04): an idea stays good until the close of the
NEXT trading session after the day it was made. An Approve while the market is
open buys at once. An Approve while it is closed buys nothing then: the idea is
stored as "waiting", and the market-open job (09:15-09:20 IST, trading days
only) runs every check again and only then buys. Nothing is ever ordered
outside market hours.

Safety:
- the stage is compared positively (== "approval" / == "auto"); anything else,
  including an unknown value, counts as practice and buys nothing;
- a row is claimed with a conditional UPDATE before any order, so two Approve
  presses (or a press and the open job) order at most once;
- an order that fails is recorded and never retried.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from swing_trade_ml.brokers import current_mode, get_broker
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import OrderStatus, SignalType
from swing_trade_ml.core.holidays import is_trading_holiday
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
from swing_trade_ml.db.models.brain_golive import BrainApproval
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Order, Signal, Strategy
from swing_trade_ml.notifications import notifier
from swing_trade_ml.services import ingestion, risk
from swing_trade_ml.services.brain_golive.stage import AUTO_BY, current_stage
from swing_trade_ml.services.execution import open_position
from swing_trade_ml.services.portfolio import portfolio_value_and_cash
from swing_trade_ml.strategies import brain as brain_strategy

log = get_logger(__name__)

__all__ = [
    "AUTO_BY",
    "ApprovalError",
    "ApprovalExpired",
    "ApprovalFailed",
    "ApprovalNotFound",
    "ApprovalRefused",
    "after_scan",
    "announce",
    "approval_out",
    "approve",
    "auto_approve",
    "create_pending",
    "execute_waiting",
    "expire_stale",
    "list_approvals",
    "reject",
    "valid_until",
]

IST = brain_strategy.IST
LIVE = ("pending", "waiting")  # the only statuses that can still lead to a buy
OPEN_WINDOW = timedelta(minutes=5)  # the market-open job buys only 09:15-09:20 IST
STATUS_PLAIN = {
    "pending": "Waiting for your OK",
    "waiting": "Approved — will be placed when the market opens",
    "approved": "Approved",
    "rejected": "Rejected",
    "expired": "Expired",
}
NOTHING_BOUGHT = "Nothing was bought."
STAGE_UNREADABLE = "Could not confirm the go-live switch just before buying, so nothing was bought."


class ApprovalError(Exception):
    """The message is shown to the owner as-is."""


class ApprovalNotFound(ApprovalError):  # noqa: N818 - names fixed by the API contract
    pass


class ApprovalRefused(ApprovalError):  # noqa: N818 - names fixed by the API contract
    """Nothing changed; the idea stays as it was."""


class ApprovalExpired(ApprovalError):  # noqa: N818 - names fixed by the API contract
    """The idea can no longer be bought; it is now marked expired."""


class ApprovalFailed(ApprovalError):  # noqa: N818 - names fixed by the API contract
    """The OK was recorded but the order could not be sent. Never retried."""


def _now() -> datetime:
    return datetime.now(UTC)


# ------------------------------------------------------------------ clock --


def _is_trading_day(d: date) -> bool:
    # The app's NSE calendar (core.holidays), the same rule as
    # services.ingestion.is_market_open and the brain's M01 is_trading_day.
    return d.weekday() < 5 and not is_trading_holiday(d)


def _next_trading_day(d: date) -> date:
    d += timedelta(days=1)
    while not _is_trading_day(d):
        d += timedelta(days=1)
    return d


def valid_until(decision_day: date) -> datetime:
    """The close of the next trading session after the idea's day (IST)."""
    return datetime.combine(_next_trading_day(decision_day), settings.market_close, tzinfo=IST)


def _market_open(now: datetime) -> bool:
    """In the session, strictly before the close: never an order at or after it."""
    return ingestion.is_market_open(now) and now.astimezone(IST).time() < settings.market_close


def _in_opening_window(now: datetime) -> bool:
    local = now.astimezone(IST)
    if not _is_trading_day(local.date()):
        return False
    opens = datetime.combine(local.date(), settings.market_open, tzinfo=IST)
    return opens <= local < opens + OPEN_WINDOW


def _next_open(now: datetime) -> datetime:
    local = now.astimezone(IST)
    d = local.date()
    if not (_is_trading_day(d) and local.time() < settings.market_open):
        d = _next_trading_day(d)
    return datetime.combine(d, settings.market_open, tzinfo=IST)


def _when(dt: datetime) -> str:
    return f"{dt.astimezone(IST):%a %d %b, %H:%M}"


# --------------------------------------------------------------- helpers --


def _get(db: Session, approval_id: int) -> BrainApproval:
    a = db.get(BrainApproval, approval_id)
    if a is None:
        raise ApprovalNotFound(f"No brain idea {approval_id} was found.")
    return a


def _expire(db: Session, a: BrainApproval, note: str, by: str = "system") -> bool:
    """Mark a still-live idea expired. Conditional, so it never overwrites a
    row another caller has just approved or rejected."""
    values: dict = {"status": "expired", "decided_note": note}
    if a.status == "pending":
        values |= {"decided_by": by, "decided_at": _now()}
    n = db.execute(
        update(BrainApproval)
        .where(BrainApproval.id == a.id, BrainApproval.status.in_(LIVE))
        .values(**values)
        .execution_options(synchronize_session="fetch")
    ).rowcount
    db.commit()
    db.refresh(a)
    return n == 1


def _claim(db: Session, a: BrainApproval, from_status: str, to_status: str, **values) -> bool:
    """Move the row from one status to another only if nobody else has: of
    two Approve presses (or a press and the open job) only one can win."""
    n = db.execute(
        update(BrainApproval)
        .where(BrainApproval.id == a.id, BrainApproval.status == from_status)
        .values(status=to_status, **values)
        .execution_options(synchronize_session="fetch")
    ).rowcount
    db.commit()
    db.refresh(a)
    return n == 1


def _stale_note(a: BrainApproval) -> str:
    deadline = _when(valid_until(a.decision_day))
    if a.status == "waiting":
        return (
            f"Approved, but it could not be bought by the close of the next trading day ({deadline}), "
            f"so it expired. {NOTHING_BOUGHT}"
        )
    return (
        f"Not approved by the close of the next trading day ({deadline}), so this idea expired. "
        f"{NOTHING_BOUGHT}"
    )


def _latest_decision(db: Session, a: BrainApproval, book: str) -> BrainDecision | None:
    """The stock's decision in the latest live nightly brain run made on or
    after the idea's day — a newer run that dropped the idea wins."""
    start, _ = brain_strategy.ist_day_bounds(a.decision_day)
    run = db.execute(
        select(BrainRun)
        .where(
            BrainRun.kind == "nightly",
            BrainRun.live.is_(True),
            BrainRun.status == "done",
            BrainRun.book == book,
            BrainRun.as_of >= start,
        )
        .order_by(BrainRun.started_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if run is None:
        return None
    found = list(
        db.execute(
            select(BrainDecision).where(BrainDecision.run_id == run.id, BrainDecision.symbol == a.symbol)
        ).scalars()
    )
    ideas = [d for d in found if d.kind == "idea"]
    return (ideas or found or [None])[0]


def _live_price(db: Session, instrument: Instrument) -> float | None:
    """The broker's last traded price — the same LTP call v1's exit loop uses.
    None when it cannot be had; then nothing is bought."""
    key = instrument.symbol_key
    try:
        price = get_broker().get_ltp([key], db).get(key)
    except Exception as exc:  # noqa: BLE001 - no price means no buy, never a crash
        log.warning("brain_golive.approval.no_live_price", symbol=instrument.tradingsymbol, error=str(exc))
        return None
    return float(price) if price is not None and price > 0 else None


class _Ready:
    def __init__(
        self,
        strategy: Strategy,
        instrument: Instrument,
        signal: Signal,
        quantity: int,
        automatic: bool,
    ) -> None:
        self.strategy, self.instrument, self.signal = strategy, instrument, signal
        self.quantity, self.automatic = quantity, automatic


def _check(db: Session, a: BrainApproval, now: datetime, automatic: bool, live: bool) -> _Ready:
    """Every check an Approve needs, run fresh. Raises ApprovalRefused (nothing
    changed) or ApprovalExpired (the caller marks the idea expired). Writes
    nothing itself.

    `live` is True whenever an order would follow (market open): the broker's
    live price must then sit inside the brain's own buy range and strictly
    above the stop, and v1's risk check sizes on that live price — a gap
    below the stop or away from the range never becomes a market order."""
    stage_now = current_stage(db)
    if not (stage_now == "approval" or stage_now == "auto"):
        raise ApprovalRefused(
            "The brain is in practice mode (shadow), so nothing can be bought. "
            "Switch to the approval stage first."
        )
    if automatic and stage_now != "auto":
        raise ApprovalRefused(
            "This was approved by the automatic stage, which is now switched off, so it needs your OK."
        )
    if now >= valid_until(a.decision_day):
        raise ApprovalExpired(_stale_note(a))
    strategy = db.get(Strategy, a.strategy_id)
    instrument = db.get(Instrument, a.instrument_id)
    signal = db.get(Signal, a.signal_id)
    if strategy is None or instrument is None or signal is None:
        raise ApprovalExpired("The idea's records are gone, so it cannot be bought.")
    if not strategy.is_active:
        raise ApprovalRefused("The brain strategy is switched off.")
    mode = current_mode()
    if strategy.mode != mode:
        raise ApprovalRefused(
            f"The brain strategy is set up for {strategy.mode} trading but the app is in {mode} mode."
        )
    d = _latest_decision(db, a, strategy.mode)
    if d is None:
        raise ApprovalExpired(
            f"The brain no longer says TRADE for {a.symbol}: its latest run did not look at this stock."
        )
    word = brain_strategy.effective_word(d)
    if d.kind != "idea" or word != "TRADE":
        raise ApprovalExpired(
            f"The brain no longer says TRADE for {a.symbol} ({word}): {brain_strategy.why(d)}"
        )
    if risk.has_open_position(db, mode, a.instrument_id, strategy_id=strategy.id):
        raise ApprovalExpired(f"You already hold {a.symbol} through the brain.")
    price = signal.price
    if live:
        label = "at the open" if _in_opening_window(now) else "right now"
        price = _live_price(db, instrument)
        if price is None:
            raise ApprovalExpired(f"Could not get a live price {label}, so nothing was bought.")
        low, high = d.entry_low, d.entry_high
        if low is None or high is None:
            raise ApprovalExpired(f"The brain gave no buy range for {a.symbol}, so nothing was bought.")
        if not (low <= price <= high):
            raise ApprovalExpired(
                f"The price {label} (₹{price:,.2f}) was outside the brain's buy range "
                f"(₹{low:,.2f} to ₹{high:,.2f}), so nothing was bought."
            )
        if signal.stop_loss is not None and price <= signal.stop_loss:
            raise ApprovalExpired(
                f"The price {label} (₹{price:,.2f}) was at or below the stop (₹{signal.stop_loss:,.2f}), "
                "so nothing was bought."
            )
    total, cash = portfolio_value_and_cash(db, mode)
    verdict = risk.check_entry(
        db=db,
        mode=mode,
        instrument_id=a.instrument_id,
        price=price,
        stop_loss=signal.stop_loss,
        portfolio_value=total,
        available_cash=cash,
        strategy=strategy,
    )
    if not verdict.allowed or verdict.quantity <= 0:
        raise ApprovalRefused(f"The safety check says no right now: {verdict.reason}")
    return _Ready(strategy, instrument, signal, verdict.quantity, automatic)


def _order_status(db: Session, signal: Signal) -> str | None:
    """Status of the newest order placed for this signal (open_position writes it)."""
    return db.execute(
        select(Order.status).where(Order.signal_id == signal.id).order_by(Order.id.desc()).limit(1)
    ).scalar_one_or_none()


def _order(db: Session, a: BrainApproval, ready: _Ready) -> BrainApproval:
    """Send the order through version 1. The row is already claimed, so this
    runs at most once per idea. Only ever called while the market is open."""
    if not _market_open(_now()):  # belt and braces: never an order outside market hours
        a.result_note = f"The market closed before the order could be sent. {NOTHING_BOUGHT}"
        db.commit()
        raise ApprovalFailed(a.result_note)
    # Re-read the stage right before the order: a switch back that landed
    # after the checks (rollback in flight) must still stop this buy.
    try:
        stage_now = current_stage(db)
    except Exception as exc:  # noqa: BLE001 - fail closed: no confirmed stage, no order
        if isinstance(exc, SQLAlchemyError):
            db.rollback()
        log.error("brain_golive.approval.stage_unreadable", symbol=a.symbol, error=str(exc))
        stage_now, unreadable = None, True
    else:
        unreadable = False
    if (
        unreadable
        or not (stage_now == "approval" or stage_now == "auto")
        or (ready.automatic and stage_now != "auto")
    ):
        if unreadable:
            note = STAGE_UNREADABLE
        elif stage_now == "approval":
            note = "The automatic stage was switched off before the order was sent. Nothing was bought."
        else:
            note = (
                "The brain was switched back to practice mode (shadow) before the order was sent. "
                "Nothing was bought."
            )
        db.execute(
            update(BrainApproval)
            .where(BrainApproval.id == a.id, BrainApproval.status == "approved")
            .values(status="expired", decided_note=note)
            .execution_options(synchronize_session="fetch")
        )
        db.commit()
        db.refresh(a)
        raise ApprovalExpired(note)
    try:
        position = open_position(db, ready.strategy, ready.instrument, ready.signal, ready.quantity)
    except Exception as exc:  # recorded and shown, never retried
        # open_position commits the Order row (and any broker_order_id) as it
        # goes, so a rollback here can only drop this failed step's unsaved
        # changes; it is needed only when the session itself is broken.
        if isinstance(exc, SQLAlchemyError):
            db.rollback()
        a = db.get(BrainApproval, a.id)
        a.result_note = (
            "The order may not have been sent — check the Orders page before doing anything else. "
            f"It will not be tried again. (Error: {exc})"
        )
        db.commit()
        log.error("brain_golive.approval.order_failed", symbol=a.symbol, error=str(exc))
        raise ApprovalFailed(a.result_note) from exc
    a.position_id = position.id if position is not None else None
    if position is not None:
        a.result_note = f"Bought {position.quantity} shares at ₹{position.entry_price:,.2f}."
    elif _order_status(db, ready.signal) in (OrderStatus.PENDING, OrderStatus.OPEN):
        a.result_note = "Order sent; it will show as a position once it fills."  # normal for live orders
    else:
        a.result_note = (
            f"The broker did not fill the order: {ready.signal.rejection_reason or 'no reason given'}. "
            f"{NOTHING_BOUGHT}"
        )
    db.commit()
    log.info("brain_golive.approval.ordered", symbol=a.symbol, filled=position is not None)
    return a


# ------------------------------------------------------------- lifecycle --


def expire_stale(db: Session, now: datetime | None = None) -> int:
    """Expire every live idea past the close of the next trading session.
    An OK the owner gave that was never bought (e.g. the open job did not
    run) is reported on Telegram once, naming the stock and why."""
    now = now or _now()
    n = 0
    unbought: list[str] = []
    for a in db.execute(select(BrainApproval).where(BrainApproval.status.in_(LIVE))).scalars().all():
        if now < valid_until(a.decision_day):
            continue
        was_waiting = a.status == "waiting"
        note = _stale_note(a)
        if _expire(db, a, note):
            n += 1
            if was_waiting:
                unbought.append(f"{a.symbol}: {note}")
    if unbought:
        notifier.send_sync("🧠 Approved brain ideas that expired unbought:\n" + "\n".join(unbought), "signal")
    return n


def create_pending(db: Session, today: date) -> list[BrainApproval]:
    """One pending idea per safe brain BUY of `today`, at most one per stock.
    A newer idea replaces an older one still waiting for an OK; an idea
    already approved and waiting for the open is left alone."""
    stage_now = current_stage(db)
    if not (stage_now == "approval" or stage_now == "auto"):
        return []
    expire_stale(db)
    start, end = brain_strategy.ist_day_bounds(today)
    known = (
        db.execute(
            select(BrainApproval).where(
                (BrainApproval.decision_day == today) | BrainApproval.status.in_(LIVE)
            )
        )
        .scalars()
        .all()
    )
    rows = db.execute(
        select(Signal, Instrument.tradingsymbol)
        .join(Strategy, Strategy.id == Signal.strategy_id)
        .join(Instrument, Instrument.id == Signal.instrument_id)
        .where(
            Strategy.strategy_type == "brain",
            Strategy.is_active.is_(True),
            Signal.signal_type == SignalType.BUY,
            Signal.advisory_only.is_(True),
            Signal.rejection_reason.is_(None),
            Signal.generated_at >= start,
            Signal.generated_at < end,
        )
        .order_by(Signal.generated_at.desc(), Signal.id.desc())
    ).all()
    seen: set[str] = set()
    created: list[BrainApproval] = []
    for sig, symbol in rows:
        if symbol in seen:  # the newest scan's signal wins
            continue
        seen.add(symbol)
        mine = [k for k in known if k.symbol == symbol]
        if any(k.decision_day == today or k.status == "waiting" for k in mine):
            continue
        for older in (k for k in mine if k.status == "pending"):
            _expire(
                db,
                older,
                f"A newer idea for {symbol} (from {today:%d %b %Y}) replaced this one. {NOTHING_BOUGHT}",
            )
        a = BrainApproval(
            signal_id=sig.id,
            strategy_id=sig.strategy_id,
            instrument_id=sig.instrument_id,
            symbol=symbol,
            decision_day=today,
            price=sig.price,
            stop_loss=sig.stop_loss,
            take_profit=sig.take_profit,
            suggested_qty=sig.suggested_quantity,
            reason=sig.reason or "",
            status="pending",
        )
        db.add(a)
        created.append(a)
    db.commit()
    return created


def announce(created: list[BrainApproval]) -> bool:
    if not created:
        return False
    n = len(created)
    names = ", ".join(a.symbol for a in created)
    text = (
        f"🧠 The brain has {n} idea{'s' if n != 1 else ''} waiting for your OK: {names}.\n"
        "Nothing is bought until you press Approve. An idea not approved and bought by the close of "
        "the next trading day expires. If you approve while the market is closed, it is bought when "
        "the market opens, after every check runs again.\n"
        f"Open: {settings.FRONTEND_URL.rstrip('/')}/brain#approvals"
    )
    return notifier.send_sync(text, "signal")


def approve(db: Session, approval_id: int, by: str, note: str = "") -> BrainApproval:
    """The owner's (or the automatic stage's) OK. Runs every check now; buys
    at once only while the market is open, otherwise waits for the open."""
    a = _get(db, approval_id)
    if a.status != "pending":
        raise ApprovalRefused(f"This idea is already {STATUS_PLAIN.get(a.status, a.status).lower()}.")
    now = _now()
    market_open = _market_open(now)
    try:
        ready = _check(db, a, now, automatic=by == AUTO_BY, live=market_open)
    except ApprovalExpired as exc:
        _expire(db, a, str(exc))
        raise
    decided = {"decided_by": by, "decided_at": now, "decided_note": note.strip() or None}
    if not market_open:
        if not _claim(db, a, "pending", "waiting", **decided):
            raise ApprovalRefused("This idea was already decided.")
        a.result_note = (
            f"Approved while the market is closed, so nothing is bought yet. It is bought when the market "
            f"opens ({_when(_next_open(now))}), only if every check still passes; otherwise it expires "
            f"unbought by {_when(valid_until(a.decision_day))}."
        )
        db.commit()
        log.info("brain_golive.approval.waiting", symbol=a.symbol, by=by)
        return a
    if not _claim(db, a, "pending", "approved", **decided):
        raise ApprovalRefused("This idea was already decided.")
    return _order(db, a, ready)


def _execute_one(db: Session, a: BrainApproval, now: datetime, dropped: list[str]) -> bool:
    """One waiting OK at the open: True when the order was sent."""
    try:
        ready = _check(db, a, now, automatic=a.decided_by == AUTO_BY, live=True)
    except ApprovalError as exc:
        note = str(exc) if "nothing was bought" in str(exc).lower() else f"{exc} {NOTHING_BOUGHT}"
        if _expire(db, a, note):
            dropped.append(f"{a.symbol}: {exc}")
        return False
    if not _claim(db, a, "waiting", "approved"):
        return False
    try:
        _order(db, a, ready)
    except ApprovalError as exc:
        dropped.append(f"{a.symbol}: {exc}")
        return False
    return True


def execute_waiting(db: Session) -> list[BrainApproval]:
    """The market-open job: buy each approved-and-waiting idea, but only in the
    first minutes of a trading session and only after every check runs again.
    Anything that fails a check expires with a plain reason."""
    now = _now()
    if not _in_opening_window(now):
        return []
    expire_stale(db, now)
    waiting = (
        db.execute(select(BrainApproval).where(BrainApproval.status == "waiting").order_by(BrainApproval.id))
        .scalars()
        .all()
    )
    ordered: list[BrainApproval] = []
    dropped: list[str] = []
    for a in waiting:
        symbol = a.symbol
        try:
            if _execute_one(db, a, now, dropped):
                ordered.append(a)
        except Exception as exc:  # noqa: BLE001 - one row never stops the others or the summary
            if isinstance(exc, SQLAlchemyError):
                db.rollback()
            log.error("brain_golive.approval.open_job_row_failed", symbol=symbol, error=str(exc))
            dropped.append(f"{symbol}: something went wrong while checking it ({exc}). {NOTHING_BOUGHT}")
    if dropped:
        notifier.send_sync(
            "🧠 Approved brain ideas not bought at the market open:\n" + "\n".join(dropped), "signal"
        )
    return ordered


def reject(db: Session, approval_id: int, by: str, reason: str) -> BrainApproval:
    a = _get(db, approval_id)
    if a.status not in LIVE:
        raise ApprovalRefused(f"This idea is already {STATUS_PLAIN.get(a.status, a.status).lower()}.")
    reason = reason.strip()
    if not reason:
        raise ApprovalRefused("Say why you are rejecting this idea.")
    n = db.execute(
        update(BrainApproval)
        .where(BrainApproval.id == a.id, BrainApproval.status.in_(LIVE))
        .values(status="rejected", decided_by=by, decided_at=_now(), decided_note=reason)
        .execution_options(synchronize_session="fetch")
    ).rowcount
    db.commit()
    db.refresh(a)
    if n != 1:
        raise ApprovalRefused("This idea was already decided.")
    return a


def list_approvals(db: Session, status: str | None = None, limit: int = 50) -> list[BrainApproval]:
    stmt = select(BrainApproval).order_by(BrainApproval.id.desc()).limit(limit)
    if status:
        stmt = stmt.where(BrainApproval.status == status)
    return list(db.execute(stmt).scalars())


def auto_approve(db: Session, today: date) -> list[BrainApproval]:
    """Only in the automatic stage: press Approve on today's pending ideas
    through the very same approve() checks."""
    if current_stage(db) != "auto":
        return []
    pending = (
        db.execute(
            select(BrainApproval.id)
            .where(BrainApproval.status == "pending", BrainApproval.decision_day == today)
            .order_by(BrainApproval.id)
        )
        .scalars()
        .all()
    )
    done: list[BrainApproval] = []
    for approval_id in pending:
        try:
            done.append(approve(db, approval_id, by=AUTO_BY))
        except ApprovalFailed as exc:
            log.error("brain_golive.approval.auto_failed", approval_id=approval_id, reason=str(exc))
        except ApprovalError as exc:
            log.info("brain_golive.approval.auto_skipped", approval_id=approval_id, reason=str(exc))
    return done


def after_scan(db: Session, today: date) -> dict:
    created = create_pending(db, today)
    stage_now = current_stage(db)
    if stage_now == "approval":
        announce(created)
    approved = auto_approve(db, today) if stage_now == "auto" else []
    return {"created": len(created), "approved": len(approved)}


def approval_out(a: BrainApproval) -> dict:
    return {
        "id": a.id,
        "symbol": a.symbol,
        "decision_day": a.decision_day.isoformat(),
        "valid_until": valid_until(a.decision_day).isoformat(),
        "price": a.price,
        "stop_loss": a.stop_loss,
        "take_profit": a.take_profit,
        "suggested_qty": a.suggested_qty,
        "reason": a.reason,
        "status": a.status,
        "status_plain": STATUS_PLAIN.get(a.status, a.status),
        "decided_by": a.decided_by,
        "decided_at": a.decided_at.isoformat() if a.decided_at else None,
        "decided_note": a.decided_note,
        "position_id": a.position_id,
        "result_note": a.result_note,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }
