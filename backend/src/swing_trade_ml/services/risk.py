"""Position sizing and pre-trade risk checks.

Every entry passes through `check_entry` before an order is created. Rejections
are recorded on the signal rather than dropped, so the paper phase produces
evidence about whether the limits helped or cost money.

Every limit is resolved per account size by `services/limits.py` — nothing in
this module reads a portfolio limit from settings directly, so the scan, this
gate and the backtest cannot disagree about what the limits are.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import ExitReason, OrderStatus, PositionStatus, TransactionType
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.trading import (
    Order,
    PortfolioSnapshot,
    Position,
    Signal,
    Strategy,
)
from swing_trade_ml.ml.sector_map import get_sector_bucket, sector_display_name
from swing_trade_ml.services import avoid, deployable, system_state
from swing_trade_ml.services.costs import apply_slippage, compute_charges
from swing_trade_ml.services.limits import LARGE, SMALL, Limits, format_inr, limits_for
from swing_trade_ml.services.portfolio import portfolio_value_and_cash
from swing_trade_ml.strategies.tier import cap_tier

log = get_logger(__name__)

ADV_LOOKBACK_DAYS = 20

# Plain-English names for the size ceilings, used in "Sized by ..." notes.
_CEILING_RULES: dict[str, str] = {
    "sector limit": "SECTOR_CAP",
    "small-company budget": "CAP_TIER",
    "trading-volume limit": "LIQUIDITY",
    "market-conditions limit": "DEPLOYABLE",
    "cash reserve": "CASH_FLOOR",
    "available cash": "CASH",
}


@dataclass(slots=True)
class RiskDecision:
    """The verdict on one entry.

    `rule` is a short, stable code naming which limit decided a rejection
    (e.g. "SECTOR_CAP") — what the risk_events table groups and counts by.
    `reason` is the plain-English sentence the owner reads. `amount_inr` is
    the rupee figure the rule was judged on, where one exists. Both extra
    fields default to None so the existing positional construction
    `RiskDecision(False, 0, "...")` keeps working.
    """

    allowed: bool
    quantity: int = 0
    reason: str = ""
    rule: str | None = None
    amount_inr: float | None = None


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
    """Slots already spoken for — filled positions plus buys still in flight,
    so a scan cannot hand out the same slot twice while Kite is still
    reconciling the first one."""
    stmt = select(func.count(Position.id)).where(
        Position.mode == mode, Position.status == PositionStatus.OPEN
    )
    if strategy_id is not None:
        stmt = stmt.where(Position.strategy_id == strategy_id)
    filled = int(db.execute(stmt).scalar_one() or 0)
    return filled + len(in_flight_buy_holdings(db, mode, strategy_id))


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


def stopped_out_recently(
    db: Session, mode: str, instrument_id: int, strategy_id: int | None, cooldown_days: int
) -> bool:
    """True if this instrument stopped this same strategy out within the
    cooldown window — the guard against re-buying a name the moment
    confidence clears the bar again, right after it just cost money."""
    if cooldown_days <= 0:
        return False
    cutoff = datetime.now(UTC) - timedelta(days=cooldown_days)
    stmt = select(Position.id).where(
        Position.mode == mode,
        Position.instrument_id == instrument_id,
        Position.status == PositionStatus.CLOSED,
        Position.exit_reason == ExitReason.STOP_LOSS_HIT,
        Position.exit_at >= cutoff,
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


def current_drawdown(db: Session, mode: str, current_value: float | None = None) -> float:
    """Drawdown from the running peak, as a positive fraction.

    The peak legitimately comes from the snapshot history — a high-water mark
    cannot be known from today alone. The *current* value must not: snapshots
    are written once a day by the take_snapshot job, so measuring the fall
    against the snapshot's own total_value reads yesterday's healthy account
    on exactly the day a drawdown opens up — the one day this brake exists
    for. Callers holding the live value (check_entry, handed it by
    portfolio_value_and_cash) pass it in; the rest pay for one valuation.

    `max(0.0, ...)` is what makes a new high read as zero rather than a
    negative drawdown: above the recorded peak, today IS the peak.
    """
    if current_value is None:
        current_value, _cash = portfolio_value_and_cash(db, mode)
    # No snapshot yet means a fresh account with no known peak, so there is
    # nothing to have fallen from — and nothing to divide by.
    peak = db.execute(
        select(func.max(PortfolioSnapshot.peak_value)).where(PortfolioSnapshot.mode == mode)
    ).scalar()
    if not peak:
        return 0.0
    return max(0.0, (peak - current_value) / peak)


# ---------------------------------------------------------------- holdings --


@dataclass(slots=True)
class Holding:
    """One open position, reduced to what portfolio-level limits need."""

    instrument_id: int
    tradingsymbol: str
    value: float
    tier: str


def in_flight_buy_holdings(
    db: Session, mode: str, strategy_id: int | None = None
) -> list[Holding]:
    """Buys the broker has accepted but not yet filled, valued as if they had.

    Kite answers `place_order` with PENDING and the Position row only appears
    when the 60-second reconciliation job sees the fill. Since every
    portfolio-level limit reads the book through `open_holdings`, without
    these rows a scan checks its second and third candidates against the
    account as it stood before the first — which is how three banks can each
    pass the same 25% sector cap in one run.

    Paper never has rows here: the simulated broker fills synchronously, so
    its Position exists before the next candidate is looked at. That is also
    why the bug never showed up in the paper track record.

    Orders are valued at the price their signal was raised at, which is the
    number the entry was sized against; a limit price is the fallback for the
    rare order with no signal behind it.
    """
    rows = db.execute(
        select(Order, Instrument.tradingsymbol, Strategy.params, Signal.price)
        .join(Instrument, Instrument.id == Order.instrument_id)
        .join(Strategy, Strategy.id == Order.strategy_id, isouter=True)
        .join(Signal, Signal.id == Order.signal_id, isouter=True)
        .where(
            Order.mode == mode,
            Order.transaction_type == TransactionType.BUY,
            Order.status.in_((OrderStatus.PENDING, OrderStatus.OPEN)),
            # Reconciliation sets position_id when it creates the Position, so
            # this is what stops the same money being counted twice.
            Order.position_id.is_(None),
            *([Order.strategy_id == strategy_id] if strategy_id is not None else []),
        )
    ).all()
    holdings: list[Holding] = []
    for order, symbol, params, signal_price in rows:
        price = signal_price if signal_price is not None else (order.price or 0.0)
        tier = cap_tier((params or {}).get("model_name")) if params is not None else LARGE
        holdings.append(Holding(order.instrument_id, symbol, price * order.quantity, tier))
    return holdings


def open_holdings(db: Session, mode: str) -> list[Holding]:
    """Every open position in this mode, across all strategies, valued at the
    latest marked price where one exists and at entry otherwise.

    Across strategies on purpose: a sector shock hits the account, not one
    strategy's slice of it, so two strategies each holding a bank are two
    banks in the same book.
    """
    rows = db.execute(
        select(Position, Instrument.tradingsymbol, Strategy.params)
        .join(Instrument, Instrument.id == Position.instrument_id)
        .join(Strategy, Strategy.id == Position.strategy_id, isouter=True)
        .where(Position.mode == mode, Position.status == PositionStatus.OPEN)
    ).all()
    holdings: list[Holding] = []
    for position, symbol, params in rows:
        price = position.current_price or position.entry_price
        tier = cap_tier((params or {}).get("model_name")) if params is not None else LARGE
        holdings.append(Holding(position.instrument_id, symbol, price * position.quantity, tier))
    return holdings + in_flight_buy_holdings(db, mode)


def average_daily_traded_value(
    db: Session, instrument_id: int, days: int = ADV_LOOKBACK_DAYS
) -> float | None:
    """Mean of close × volume over the last `days` daily candles, or None when
    there are fewer than that many — a two-day average of a newly listed or
    newly ingested stock is not a liquidity measurement."""
    rows = db.execute(
        select(Candle.close, Candle.volume)
        .where(Candle.instrument_id == instrument_id, Candle.interval == "day")
        .order_by(Candle.ts.desc())
        .limit(days)
    ).all()
    if len(rows) < days:
        return None
    return float(sum(float(c) * float(v) for c, v in rows) / len(rows))


# ------------------------------------------------------------------ sizing --


def buy_cost(price: float, quantity: int) -> float:
    """Everything a buy takes out of cash: the slipped fill, plus charges.

    Mirrors what the paper broker deducts when it fills (brokers/paper.py
    place_order), so an order that passes the risk check cannot then be
    refused by the broker for want of a few rupees of charges.
    """
    fill = apply_slippage(price, TransactionType.BUY)
    turnover = fill * quantity
    brokerage, taxes = compute_charges(turnover, TransactionType.BUY)
    return turnover + brokerage + taxes


def _affordable_quantity(price: float, cash: float) -> float:
    """The (fractional) share count whose full buy cost fits in `cash`.

    Buy-side charges are a fixed part plus a part proportional to turnover
    (costs.py), so this solves the linear equation directly instead of
    decrementing a share at a time.
    """
    if cash <= 0:
        return 0.0
    fill = apply_slippage(price, TransactionType.BUY)
    fixed = sum(compute_charges(0.0, TransactionType.BUY))
    per_share = fill + (sum(compute_charges(fill, TransactionType.BUY)) - fixed)
    if per_share <= 0:
        return 0.0
    return max(0.0, (cash - fixed) / per_share)


def _size(
    price: float,
    stop_loss: float | None,
    portfolio_value: float,
    available_cash: float,
    strategy: Strategy | None,
    existing_exposure: float,
    limits: Limits,
    ceilings: dict[str, float] | None,
) -> tuple[int, str, str]:
    """(quantity, binding constraint label, note). See calculate_quantity."""
    if price <= 0:
        return 0, "invalid", "Invalid price"

    sizing_mode = (
        (strategy.params.get("position_sizing_mode") if strategy and strategy.params else None)
        or settings.POSITION_SIZING_MODE
    )

    if sizing_mode == "fixed_amount":
        qty_by_target = settings.FIXED_POSITION_AMOUNT_INR / price
        target_label = "fixed amount"
    else:
        risk_capital = portfolio_value * limits.risk_per_trade_pct

        if stop_loss and stop_loss > 0 and stop_loss < price:
            risk_per_share = price - stop_loss
        else:
            # No stop supplied — assume the default stop distance so sizing
            # stays bounded rather than falling back to "as much as cash allows".
            risk_per_share = price * settings.DEFAULT_STOP_LOSS_PCT

        if risk_per_share <= 0:
            return 0, "invalid", "Non-positive risk per share"

        qty_by_target = risk_capital / risk_per_share
        target_label = "risk-per-trade"

    remaining_concentration_room = max(
        0.0, (portfolio_value * limits.max_position_pct) - existing_exposure
    )
    candidates: list[tuple[str, float]] = [
        (target_label, qty_by_target),
        ("concentration cap", remaining_concentration_room / price),
        ("available cash", _affordable_quantity(price, available_cash)),
    ]
    for label, rupees in (ceilings or {}).items():
        if label == "cash reserve":
            candidates.append((label, _affordable_quantity(price, rupees)))
        else:
            candidates.append((label, max(0.0, rupees) / price))

    # floor, never round: rounding up would breach whichever limit was binding.
    binding, binding_qty = min(candidates, key=lambda kv: kv[1])
    quantity = math.floor(binding_qty)

    if quantity < 1:
        detail = ", ".join(f"{label} {qty:.2f}" for label, qty in candidates)
        return 0, binding, f"Computed size below 1 share ({detail})"
    return quantity, binding, f"Sized by {binding}"


def calculate_quantity(
    price: float,
    stop_loss: float | None,
    portfolio_value: float,
    available_cash: float,
    strategy: Strategy | None = None,
    existing_exposure: float = 0.0,
    *,
    limits: Limits | None = None,
    ceilings: dict[str, float] | None = None,
) -> tuple[int, str]:
    """Size the position — by default off the distance to the stop, not off a
    fixed rupee amount.

    Risking a constant fraction of equity per trade means a wide stop
    automatically gets a smaller position and a tight stop a larger one, so
    every trade carries the same downside. That is the single highest-leverage
    risk control in the system.

    settings.POSITION_SIZING_MODE == "fixed_amount" overrides this with a flat
    rupee target instead (settings.FIXED_POSITION_AMOUNT_INR) — for a
    deliberately small, capital-light live rollout where per-trade fixed costs
    would otherwise dominate a tiny, precisely-risk-sized position. Both modes
    still pass through the same ceilings below.

    A strategy can override the global mode via `params["position_sizing_mode"]`
    — added after the small-cap backtest showed every position running near
    the maximum allowed stop distance while still being sized at the same flat
    amount as a tight-stop large-cap trade.

    `existing_exposure` is rupees already committed to this instrument by an
    earlier tranche (pyramiding) — the concentration cap applies to *total*
    exposure across tranches, not each one separately.

    The risk-per-trade fraction and the single-stock cap come from
    `limits_for(portfolio_value, strategy)` unless `limits` is passed in.
    `ceilings` are extra rupee caps on this position from portfolio-level
    rules (sector room, liquidity, market-conditions room, cash reserve),
    keyed by the plain label that names them when they bind. The cash ceiling
    includes buy charges, the same way the broker counts them.
    """
    limits = limits or limits_for(portfolio_value, strategy)
    quantity, _binding, note = _size(
        price, stop_loss, portfolio_value, available_cash, strategy, existing_exposure,
        limits, ceilings,
    )
    return quantity, note


# -------------------------------------------------------------- entry gate --


def _reject(rule: str, reason: str, amount_inr: float | None = None) -> RiskDecision:
    return RiskDecision(False, 0, reason, rule, amount_inr)


def _pct(value: float) -> str:
    return f"{value:.0%}"


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
    """Gate an entry. Cheap checks run before portfolio-wide queries, and the
    kill switch runs before everything.

    Read-only by design — it never writes. The caller (services/execution.py
    process_decision) records the rejection as a RiskEvent, so this function
    stays safe to call from anywhere, including a what-if preview.

    `existing_exposure` > 0 signals that the caller has already vetted this as
    a pyramiding add (strategy.allow_pyramiding and the open position is
    currently profitable — see services/execution.py process_decision) and
    computed the rupees already committed via open_exposure_value(); the
    has_open_position block below only applies to the normal, non-pyramiding
    case.

    Portfolio-level rules (sector, small-company budget, liquidity, market
    conditions, cash reserve) are applied as *ceilings* on the position
    rather than as all-or-nothing vetoes: an entry that would overshoot a
    limit is shrunk to fit, and rejected only when what is left is smaller
    than the minimum sensible position for this account size. Rejecting a
    ₹1,00,000 position outright when ₹60,000 of room remains would leave
    room unused for no reason the owner could see.
    """
    if system_state.is_entries_halted(db):
        state = system_state.get_state(db)
        why = f": {state.halt_reason}" if state.halt_reason else ""
        return _reject("HALTED", f"New buys are paused{why}. Existing positions still sell normally.")

    limits = limits_for(portfolio_value, strategy)
    strategy_id = strategy.id if strategy else None
    params = (strategy.params or {}) if strategy else {}

    if existing_exposure <= 0 and has_open_position(db, mode, instrument_id, strategy_id):
        return _reject("ALREADY_OPEN", "Position already open in this instrument")

    cooldown_days = int(params.get("stop_loss_cooldown_days") or settings.STOP_LOSS_COOLDOWN_DAYS)
    if stopped_out_recently(db, mode, instrument_id, strategy_id, cooldown_days):
        return _reject(
            "COOLDOWN", f"Stopped out within the last {cooldown_days} days — cooling down"
        )

    symbol = db.execute(
        select(Instrument.tradingsymbol).where(Instrument.id == instrument_id)
    ).scalar_one_or_none()
    if symbol:
        reason = avoid.avoid_reason(db, symbol, datetime.now(ZoneInfo("Asia/Kolkata")).date())
        if reason:
            return _reject("AVOID", reason)

    open_count = open_position_count(db, mode)
    if open_count >= limits.max_positions:
        return _reject(
            "POSITION_LIMIT",
            f"You already hold {open_count} positions — the most allowed for an account "
            f"of {format_inr(portfolio_value)} is {limits.max_positions}",
        )

    # Judged on the value passed in — the book as it stands right now, not the
    # last daily snapshot (see current_drawdown).
    drawdown = current_drawdown(db, mode, portfolio_value)
    if drawdown >= limits.max_drawdown_pct:
        # Halts new entries only; existing positions still exit normally, so
        # the circuit breaker cannot trap capital in losing trades.
        return _reject(
            "DRAWDOWN",
            f"Your account is {_pct(drawdown)} below its peak — past the "
            f"{_pct(limits.max_drawdown_pct)} safety limit, so new buys are paused until it recovers",
            portfolio_value * drawdown,
        )

    if limits.max_share_price_inr is not None and price > limits.max_share_price_inr:
        return _reject(
            "SHARE_PRICE",
            f"One share costs {format_inr(price)} — at this account size the bot skips shares "
            f"above {format_inr(limits.max_share_price_inr)}, because a sensible position "
            "can't be built from one or two shares",
            price,
        )

    min_position = limits.min_position_inr
    ceilings: dict[str, float] = {}
    holdings = open_holdings(db, mode)

    # ---- cap tier (per strategy — see the limitation note below) ----
    # A position's cap tier is inferred from its strategy's model name
    # (strategies/tier.py); there is no per-stock market-cap data in the app.
    # So the tier rules apply to the strategy doing the buying, and a
    # non-ML strategy counts as large-cap.
    tier = cap_tier(params.get("model_name")) if strategy else LARGE
    if tier not in limits.allowed_cap_tiers:
        plain = {"midcap": "Mid-sized company", "smallcap": "Small-company"}.get(tier, tier)
        return _reject(
            "CAP_TIER",
            f"{plain} stocks are switched off for an account of {format_inr(portfolio_value)} — "
            "they unlock as the account grows, once one bad pick can't do outsized damage",
        )
    if tier == SMALL and limits.small_cap_budget_pct is not None:
        small_exposure = sum(h.value for h in holdings if h.tier == SMALL)
        budget = limits.small_cap_budget_pct * portfolio_value
        room = budget - small_exposure
        if room < min_position:
            return _reject(
                "CAP_TIER",
                f"Small-company stocks already take {format_inr(small_exposure)} "
                f"({_pct(small_exposure / portfolio_value)}) of your money — another position "
                f"would go over your {_pct(limits.small_cap_budget_pct)} limit for them",
                small_exposure,
            )
        ceilings["small-company budget"] = room

    # ---- sector ----
    symbol = db.execute(
        select(Instrument.tradingsymbol).where(Instrument.id == instrument_id)
    ).scalar_one_or_none()
    bucket = get_sector_bucket(symbol) if symbol else None
    if bucket is None:
        # Unmapped symbols are not grouped with each other — "unknown" is not
        # a sector, and treating it as one would block unrelated stocks
        # against each other. Logged so gaps in the sector map stay visible.
        log.info("risk.sector_unmapped", symbol=symbol, instrument_id=instrument_id)
    else:
        sector_name = sector_display_name(bucket)
        same_sector = [h for h in holdings if get_sector_bucket(h.tradingsymbol) == bucket]
        if limits.sector_rule == "one_per_sector":
            others = [h for h in same_sector if h.instrument_id != instrument_id]
            if others:
                return _reject(
                    "SECTOR_CAP",
                    f"You already hold {others[0].tradingsymbol} in {sector_name}. At this account "
                    "size the bot keeps to one stock per sector, so one bad day for a sector "
                    "can't hit two positions at once",
                    sum(h.value for h in others),
                )
        elif limits.sector_cap_pct is not None:
            exposure = sum(h.value for h in same_sector)
            room = limits.sector_cap_pct * portfolio_value - exposure
            if room < min_position:
                projected = (exposure + min_position) / portfolio_value
                return _reject(
                    "SECTOR_CAP",
                    f"{sector_name} would go to {_pct(projected)} of your money — over your "
                    f"{_pct(limits.sector_cap_pct)} limit for one sector (you already hold "
                    f"{format_inr(exposure)} there)",
                    exposure,
                )
            ceilings["sector limit"] = room

    # ---- liquidity ----
    if limits.max_adv_pct is not None:
        adv = average_daily_traded_value(db, instrument_id)
        if adv is None:
            log.info("risk.adv_unknown", symbol=symbol, instrument_id=instrument_id)
        else:
            room = limits.max_adv_pct * adv
            if room < min_position:
                return _reject(
                    "LIQUIDITY",
                    f"{symbol or 'This stock'} trades only about {format_inr(adv)} a day. "
                    f"A position may be at most {_pct(limits.max_adv_pct)} of that "
                    f"({format_inr(room)}), below the {format_inr(min_position)} minimum — "
                    "too thinly traded to get in and out cleanly",
                    adv,
                )
            ceilings["trading-volume limit"] = room

    # ---- market conditions and cash reserve ----
    invested = sum(h.value for h in holdings)
    context = deployable.current_deployable(db)
    ceiling = context.fraction * portfolio_value
    room = ceiling - invested
    if room < min_position:
        return _reject(
            "DEPLOYABLE",
            f"The market looks {context.plain_regime} right now, so the bot keeps at most "
            f"{_pct(context.fraction)} of your money invested ({format_inr(ceiling)}). You already "
            f"have {format_inr(invested)} invested, leaving {format_inr(max(room, 0.0))} — less "
            f"than the {format_inr(min_position)} minimum position",
            ceiling,
        )
    ceilings["market-conditions limit"] = room

    floor = limits.cash_floor_inr
    if floor > 0:
        spendable = available_cash - floor
        if spendable < min_position:
            return _reject(
                "CASH_FLOOR",
                f"Buying would leave less than {format_inr(floor)} in cash — the reserve kept "
                f"aside for an account of {format_inr(portfolio_value)}. You have "
                f"{format_inr(available_cash)} in cash",
                floor,
            )
        ceilings["cash reserve"] = spendable

    # ---- size ----
    quantity, binding, note = _size(
        price, stop_loss, portfolio_value, available_cash, strategy, existing_exposure,
        limits, ceilings,
    )
    value = quantity * price
    if quantity < 1 or value < min_position:
        rule = _CEILING_RULES.get(binding, "MIN_POSITION")
        return _reject(
            rule,
            f"The position would only be {format_inr(value)} (limited by the {binding}) — below "
            f"the {format_inr(min_position)} minimum that keeps fixed charges from eating the "
            f"trade at this account size",
            value,
        )

    cost = buy_cost(price, quantity)
    if cost > available_cash:
        return _reject(
            "CASH",
            f"Not enough cash: buying costs {format_inr(cost)} including charges, and you have "
            f"{format_inr(available_cash)}",
            cost,
        )

    return RiskDecision(True, quantity, note)
