"""Money added to the paper account, and keeping it out of the profit figures.

A top-up raises cash and account value by the same amount, so any number built from account
value (day P&L, return, drawdown) would read it as profit unless the deposit is taken out. The
first funding is the PAPER_STARTING_CAPITAL setting; every later top-up is a `CapitalDeposit` row.

Two ways to say "how much did it make":
* money-in return — profit divided by all the money put in (a top-up late in the run dilutes it);
* time-weighted return — each stretch between two snapshots is measured on its own and the
  stretches are chained, so the size and timing of a top-up cannot change the answer. This is the
  fair measure of how the bot itself is doing.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from itertools import pairwise

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from swing_trade_ml.core.enums import TradingMode
from swing_trade_ml.db.models.trading import CapitalDeposit

Deposits = Sequence[tuple[datetime, float]]


def list_deposits(db: Session, mode: str = TradingMode.PAPER) -> list[tuple[datetime, float]]:
    rows = db.execute(
        select(CapitalDeposit.ts, CapitalDeposit.amount)
        .where(CapitalDeposit.mode == mode)
        .order_by(CapitalDeposit.ts)
    ).all()
    return [(ts, float(amount)) for ts, amount in rows]


def deposited(
    db: Session,
    mode: str = TradingMode.PAPER,
    *,
    after: datetime | None = None,
    upto: datetime | None = None,
) -> float:
    """Money added with `after` < ts <= `upto` (either end open)."""
    stmt = select(func.coalesce(func.sum(CapitalDeposit.amount), 0.0)).where(
        CapitalDeposit.mode == mode
    )
    if after is not None:
        stmt = stmt.where(CapitalDeposit.ts > after)
    if upto is not None:
        stmt = stmt.where(CapitalDeposit.ts <= upto)
    return float(db.execute(stmt).scalar_one())


def add_deposit(
    db: Session,
    amount: float,
    *,
    mode: str = TradingMode.PAPER,
    note: str | None = None,
    ts: datetime | None = None,
) -> CapitalDeposit:
    if amount <= 0:
        raise ValueError("The amount added must be more than zero.")
    row = CapitalDeposit(mode=mode, ts=ts or datetime.now(UTC), amount=float(amount), note=note)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def added_since(deposits: Deposits, ts: datetime) -> float:
    """Money added strictly after `ts`."""
    return sum(a for t, a in deposits if t > ts)


def added_between(deposits: Deposits, start: datetime, end: datetime) -> float:
    """Money added with start < ts <= end."""
    return sum(a for t, a in deposits if start < t <= end)


def restate(value: float, ts: datetime, deposits: Deposits) -> float:
    """What `value` (taken at `ts`) would be had every later top-up already been in the account.

    Restating the whole curve to today's capital makes peaks and drawdowns comparable: a top-up
    adds the same amount to every earlier point, so it can neither create a drawdown nor hide one.
    """
    return value + added_since(deposits, ts)


def time_weighted_return(points: Sequence[tuple[datetime, float]], deposits: Deposits) -> float:
    """Chain-linked return over (ts, account value) points, oldest first.

    For each step the money added in that step is taken off the closing value, then the steps are
    multiplied together. Returns 0.0 with fewer than two points.
    """
    growth = 1.0
    for (t0, v0), (t1, v1) in pairwise(points):
        if v0 <= 0:
            continue
        growth *= (v1 - added_between(deposits, t0, t1)) / v0
    return growth - 1.0 if len(points) > 1 else 0.0
