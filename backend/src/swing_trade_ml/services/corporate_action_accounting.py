# ruff: noqa: E501 (long explanatory lines)
"""Stock splits and bonus issues for open paper positions, plus a review flag for everything else.

Only two things are ever changed: a VERIFIED split or bonus is applied to a paper position that was open across the
ex-date (shares go up, every price level comes down by the same factor, so shares x entry price is unchanged).
Anything else, an unverified event, a demerger, a fractional share count, a real-money book, only produces a
NEEDS_REVIEW record that says what the original exit rules would do. Nothing here changes an exit rule, places an
order, writes an Order or a Trade, or runs on a schedule. The caller commits.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from fractions import Fraction
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.core.enums import PositionStatus, TradingMode
from swing_trade_ml.core.strategy_policy import exits_are_advisory
from swing_trade_ml.db.models.corporate_actions import CorporateAction, PositionAdjustment
from swing_trade_ml.db.models.trading import Position
from swing_trade_ml.services.exit_policy import exit_policy_for_strategy
from swing_trade_ml.services.portfolio import record_price

IST = ZoneInfo("Asia/Kolkata")

APPLIED, NEEDS_REVIEW, SKIPPED = "APPLIED", "NEEDS_REVIEW", "SKIPPED"
VERIFIED = "VERIFIED"
SUPPORTED_KINDS = ("split", "bonus")

# Every Position field a split or bonus can change. Prices are divided by the factor, share counts multiplied.
PRICE_FIELDS = (
    "entry_price",
    "stop_loss",
    "take_profit",
    "highest_price",
    "initial_stop_loss",
    "broker_stop_trigger",
)
QTY_FIELDS = ("quantity", "initial_quantity", "broker_stop_qty")

NOT_IMPLEMENTED = (
    "not implemented: needs confirmed entitlement, availability dates, valuation and cash treatment"
)


@dataclass(frozen=True)
class Plan:
    status: str  # APPLIED | NEEDS_REVIEW | SKIPPED
    book: str
    before: dict[str, Any]
    after: dict[str, Any] | None
    explanation: str


@dataclass
class PlannedChange:
    position_id: int
    symbol: str
    book: str
    status: str
    before: dict[str, Any]
    after: dict[str, Any] | None
    expected_exit: dict[str, Any] | None
    explanation: str
    written: bool = False


@dataclass
class ApplyResult:
    action_id: int
    applied: bool  # True only when the caller asked for a real apply
    changes: list[PlannedChange] = field(default_factory=list)


def factor(kind: str, numerator: int | None, denominator: int | None) -> Fraction | None:
    """Split 10 -> 2 gives 5. Bonus 1 new for 2 held gives 3/2. None when the ratio cannot be trusted."""
    if kind not in SUPPORTED_KINDS or not numerator or not denominator or numerator <= 0 or denominator <= 0:
        return None
    if kind == "split":
        return Fraction(numerator, denominator)
    return 1 + Fraction(numerator, denominator)


def snapshot(position: Any) -> dict[str, Any]:
    """Every field a split or bonus can change, as plain JSON numbers."""
    return {name: getattr(position, name) for name in (*QTY_FIELDS, *PRICE_FIELDS)}


def book_of(position: Position) -> str:
    """tester | bot | real. A live or advisory (own-holdings) position is never adjusted by this tool."""
    from swing_trade_ml.services.tester_paper import TESTER_PAPER_STRATEGY_NAME

    strategy = position.strategy
    if position.mode != TradingMode.PAPER or exits_are_advisory(strategy):
        return "real"
    return "tester" if strategy is not None and strategy.name == TESTER_PAPER_STRATEGY_NAME else "bot"


def _ist_date(moment: datetime) -> date:
    return moment.astimezone(IST).date()


def plan_adjustment(
    *,
    position_status: str,
    entry_date: date,
    book: str,
    state: dict[str, Any],
    kind: str,
    action_status: str,
    ex_date: date,
    numerator: int | None,
    denominator: int | None,
) -> Plan:
    """Pure decision for one position and one action. Never guesses."""

    def plan(status: str, why: str, after: dict[str, Any] | None = None) -> Plan:
        return Plan(status, book, dict(state), after, why)

    if position_status != PositionStatus.OPEN:
        return plan(SKIPPED, "The position is closed. Closed positions are never changed.")
    if entry_date >= ex_date:
        return plan(SKIPPED, "Bought on or after the ex-date, so its price is already on the new basis.")
    if book == "real":
        return plan(
            NEEDS_REVIEW,
            "Real or own-holdings position: the broker holds the true figures, so nothing is changed here.",
        )
    if action_status != VERIFIED:
        return plan(
            NEEDS_REVIEW, "The event is not verified against the company announcement, so nothing is changed."
        )
    if kind not in SUPPORTED_KINDS:
        return plan(NEEDS_REVIEW, f"A {kind} is {NOT_IMPLEMENTED}.")
    k = factor(kind, numerator, denominator)
    if k is None or k <= 1:
        return plan(
            NEEDS_REVIEW,
            "The ratio is missing, invalid or not an increase in shares (reverse splits are not implemented).",
        )
    after: dict[str, Any] = dict(state)
    for name in QTY_FIELDS:
        value = state[name]
        if value is None:
            continue
        scaled = value * k
        if scaled.denominator != 1:
            return plan(
                NEEDS_REVIEW,
                f"{name} {value} x {k} is not a whole number of shares. Not guessing; settle the fractional entitlement by hand.",
            )
        after[name] = int(scaled)
    for name in PRICE_FIELDS:
        if state[name] is not None:
            after[name] = state[name] / float(k)
    return plan(
        APPLIED,
        f"{kind.capitalize()} {numerator}:{denominator} (factor {k}): shares x {k}, every price level / {k}; "
        "money invested is unchanged.",
        after,
    )


def expected_exit(position: Position, price: float | None, now: datetime | None = None) -> dict[str, Any]:
    """What the unchanged exit rules would do with the raw price right now. Read-only: works on a copy."""
    from swing_trade_ml.services.execution import trail_stop

    now = now or datetime.now(UTC)
    if price is None:
        return {
            "would_exit": None,
            "reason": None,
            "price": None,
            "text": "No current price is stored, so the expected exit could not be worked out.",
        }
    copy = SimpleNamespace(
        **{
            c: getattr(position, c)
            for c in (
                "entry_price",
                "quantity",
                "stop_loss",
                "take_profit",
                "highest_price",
                "initial_stop_loss",
                "current_price",
                "unrealized_pnl",
            )
        }
    )
    record_price(copy, price)  # type: ignore[arg-type]
    trail_stop(copy)  # type: ignore[arg-type]
    policy = exit_policy_for_strategy(position.strategy)
    days = (now - position.entry_at).days
    reason: str | None = None
    text = f"Raw price {price:g} is between the stop {copy.stop_loss} and the target {copy.take_profit}: no exit would fire."
    if copy.stop_loss and price <= copy.stop_loss:
        reason, text = (
            "STOP_LOSS_HIT",
            f"Raw price {price:g} <= stop {copy.stop_loss:g} would trigger STOP_LOSS_HIT.",
        )
    elif copy.take_profit and price >= copy.take_profit:
        reason, text = (
            "TARGET_HIT",
            f"Raw price {price:g} >= target {copy.take_profit:g} would trigger TARGET_HIT.",
        )
    elif days >= policy.time_stop_days:
        reason, text = (
            "TIME_STOP",
            f"Held {days} days, over the {policy.time_stop_days}-day limit: TIME_STOP.",
        )
    return {
        "would_exit": reason is not None,
        "reason": reason,
        "price": price,
        "stop_loss": copy.stop_loss,
        "take_profit": copy.take_profit,
        "text": text,
    }


def _price_default(position: Position) -> float | None:
    return position.current_price


def _explain(plan: Plan, exp: dict[str, Any] | None, symbol: str, label: str) -> str:
    text = f"{symbol} ({plan.book} book), {label}: {plan.explanation}"
    if plan.status == NEEDS_REVIEW and exp is not None:
        text += f" The original exit rules, applied to the unadjusted position, would say: {exp['text']} Raw losses are not hidden."
    return text


def apply_action(
    db: Session,
    action_id: int,
    apply: bool = False,
    price_for: Callable[[Position], float | None] = _price_default,
    now: datetime | None = None,
) -> ApplyResult:
    """Plan (apply=False, the default: nothing is written) or carry out (apply=True) one action on the open
    positions of its stock. Re-running changes nothing: an APPLIED or SKIPPED row is final, a NEEDS_REVIEW row
    is only ever upgraded to APPLIED, and the unique key stops a second row."""
    action = db.get(CorporateAction, action_id)
    if action is None:
        raise ValueError(f"No corporate action with id {action_id}")
    result = ApplyResult(action_id=action_id, applied=apply)
    positions = (
        db.execute(
            select(Position)
            .where(Position.instrument_id == action.instrument_id, Position.status == PositionStatus.OPEN)
            .order_by(Position.id)
        )
        .scalars()
        .all()
    )
    label = f"{action.kind} ex {action.ex_date}"
    for position in positions:
        existing = db.execute(
            select(PositionAdjustment).where(
                PositionAdjustment.action_id == action.id, PositionAdjustment.position_id == position.id
            )
        ).scalar_one_or_none()
        if existing is not None and existing.status in (APPLIED, SKIPPED):
            continue
        plan = plan_adjustment(
            position_status=position.status,
            entry_date=_ist_date(position.entry_at),
            book=book_of(position),
            state=snapshot(position),
            kind=action.kind,
            action_status=action.status,
            ex_date=action.ex_date,
            numerator=action.ratio_numerator,
            denominator=action.ratio_denominator,
        )
        exp = expected_exit(position, price_for(position), now) if plan.status == NEEDS_REVIEW else None
        change = PlannedChange(
            position.id,
            action.symbol,
            plan.book,
            plan.status,
            plan.before,
            plan.after,
            exp,
            _explain(plan, exp, action.symbol, label),
        )
        result.changes.append(change)
        if not apply:
            continue
        if existing is not None and plan.status != APPLIED:
            continue  # already flagged; keep the first record
        when = now or datetime.now(UTC)
        if existing is None:
            existing = PositionAdjustment(action_id=action.id, position_id=position.id, created_at=when)
            db.add(existing)
        else:
            change.explanation += f" Earlier review flag: {existing.explanation}"
            exp = existing.expected_exit  # keep the flag-time expected exit as evidence
        existing.book, existing.status = plan.book, plan.status
        existing.before, existing.after, existing.expected_exit = plan.before, plan.after, exp
        existing.explanation = change.explanation
        if plan.status == APPLIED and plan.after is not None:
            for name, value in plan.after.items():
                setattr(position, name, value)
            existing.applied_at = when
        change.written = True
    if apply:
        db.flush()
    return result


def review_open_positions(
    db: Session,
    today: date,
    price_for: Callable[[Position], float | None] = _price_default,
    alert: Callable[[str], None] | None = None,
    record: bool = True,
    now: datetime | None = None,
) -> list[str]:
    """Flag open positions held across a VERIFIED action's ex-date that has no APPLIED row yet.

    Writes only NEEDS_REVIEW rows (once each), never touches a position or any exit rule. `alert`, if given, is
    called once per newly flagged position with the plain-English message; nothing is sent by this module.
    Returns the plain-English lines for every position that still needs review."""
    actions = (
        db.execute(
            select(CorporateAction).where(
                CorporateAction.status == VERIFIED, CorporateAction.ex_date <= today
            )
        )
        .scalars()
        .all()
    )
    lines: list[str] = []
    for action in actions:
        positions = (
            db.execute(
                select(Position)
                .where(Position.instrument_id == action.instrument_id, Position.status == PositionStatus.OPEN)
                .order_by(Position.id)
            )
            .scalars()
            .all()
        )
        for position in positions:
            if _ist_date(position.entry_at) >= action.ex_date:
                continue
            existing = db.execute(
                select(PositionAdjustment).where(
                    PositionAdjustment.action_id == action.id, PositionAdjustment.position_id == position.id
                )
            ).scalar_one_or_none()
            if existing is not None and existing.status != NEEDS_REVIEW:
                continue
            if existing is not None:
                lines.append(existing.explanation)
                continue
            exp = expected_exit(position, price_for(position), now)
            book = book_of(position)
            text = (
                f"{action.symbol} ({book} book): a verified {action.kind} went ex on {action.ex_date} while this position "
                "was open and it has not been adjusted, so its price and share count may be on different bases. "
                f"Review now. Exit rules are unchanged; they would say: {exp['text']} Raw losses are not hidden."
            )
            lines.append(text)
            if not record:
                continue
            db.add(
                PositionAdjustment(
                    action_id=action.id,
                    position_id=position.id,
                    book=book,
                    status=NEEDS_REVIEW,
                    before=snapshot(position),
                    after=None,
                    expected_exit=exp,
                    explanation=text,
                    created_at=now or datetime.now(UTC),
                )
            )
            if alert is not None:
                alert(text)
    if record:
        db.flush()
    return lines
