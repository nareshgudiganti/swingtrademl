"""The risk gate's batch allocator.

v1's `check_entry` judges one stock against the account as it stands now.
v1 gets away with that because it places each order before checking the next
stock, so the next check sees it. The brain places no orders, so asking
check_entry about five stocks could approve three banks into room for one,
or five buys into cash for two.

`allocate` fixes that without re-implementing the rules. It walks the
candidates strongest first and keeps a running tally — cash, free slots,
sector room, market-conditions room — so each stock is judged against the
account as it would be after the stronger ideas were bought. `check` (v1's
check_entry in production) stays the rule book; this adds only the tally
and the market mode.

Pure: no database, so every case is tested exactly.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from swing_trade_ml.brain.contracts import MarketMode, RiskVerdict
from swing_trade_ml.services.limits import format_inr


@dataclass(frozen=True, slots=True)
class Candidate:
    symbol: str
    price: float
    strength: float  # 0..1; higher is judged first
    bucket: str | None  # sector bucket, None when the stock is not mapped
    instrument_id: int | None = None


@dataclass(frozen=True, slots=True)
class Account:
    portfolio_value: float
    cash: float
    free_slots: int
    min_position_inr: float
    sector_rule: str  # "pct_cap" | "one_per_sector"
    sector_cap_pct: float | None
    sector_exposure: dict[str, float] = field(default_factory=dict)
    deploy_room: float = 0.0  # rupees the market-conditions limit still allows


@dataclass(frozen=True, slots=True)
class CheckResult:
    allowed: bool
    qty: int = 0
    rule: str | None = None
    reason: str = ""
    amount_inr: float | None = None


@dataclass(frozen=True, slots=True)
class Policy:
    mode: MarketMode
    defensive_size_factor: float = 0.5
    defensive_max_new: int = 2
    # Pairs of symbols that moved closely together over 60 days (M14). An idea
    # that pairs with a stronger idea of the same run is judged after the rest.
    pairs: frozenset[frozenset[str]] = frozenset()


Check = Callable[[Candidate, float], CheckResult]
BuyCost = Callable[[float, int], float]

_SHRUNK = {
    "SECTOR_CAP": "sector limit",
    "DEPLOYABLE": "market-conditions limit",
    "DEFENSIVE_SIZE": "half size in a defensive market",
}


def _refuse(cand: Candidate, rule: str, reason: str, amount: float | None = None) -> RiskVerdict:
    return RiskVerdict(symbol=cand.symbol, allowed=False, rule=rule, reason=reason, amount_inr=amount)


def _with_notes(verdicts: list[RiskVerdict], notes: dict[str, str]) -> list[RiskVerdict]:
    return [replace(v, note=notes[v.symbol]) if v.symbol in notes else v for v in verdicts]


def _fit(qty: int, binding: str | None, room: float, price: float, rule: str) -> tuple[int, str | None]:
    """Shrink `qty` to the whole shares that fit in `room`; name the rule if it binds."""
    fits = max(0, math.floor(room / price))
    return (fits, rule) if fits < qty else (qty, binding)


def allocate(
    candidates: list[Candidate],
    account: Account,
    check: Check,
    policy: Policy,
    buy_cost: BuyCost,
) -> list[RiskVerdict]:
    order = sorted(candidates, key=lambda c: (-c.strength, c.symbol))
    notes: dict[str, str] = {}
    if policy.pairs:
        first, later = [], []
        for cand in order:
            twin = next((f.symbol for f in first if frozenset({cand.symbol, f.symbol}) in policy.pairs), None)
            if twin is None:
                first.append(cand)
            else:
                later.append(cand)
                notes[cand.symbol] = (
                    f"Judged after {twin}: it has moved closely with {twin} over 60 days, "
                    "so buying both is close to doubling one position."
                )
        order = first + later
    if policy.mode is MarketMode.NO_NEW_TRADES:
        return [
            _refuse(c, "MARKET", "The market mode is NO NEW TRADES, so no new buys are approved.")
            for c in order
        ]

    cash_left = account.cash
    slots_left = account.free_slots
    deploy_left = account.deploy_room
    sector_used = dict(account.sector_exposure)
    approved_buckets: set[str] = set()
    approved = 0
    verdicts: list[RiskVerdict] = []

    for cand in order:
        if policy.mode is MarketMode.DEFENSIVE and approved >= policy.defensive_max_new:
            verdicts.append(
                _refuse(
                    cand,
                    "DEFENSIVE_LIMIT",
                    f"The market is defensive, so only the {policy.defensive_max_new} strongest "
                    "new ideas are approved today.",
                )
            )
            continue
        if slots_left <= 0:
            verdicts.append(
                _refuse(
                    cand,
                    "POSITION_LIMIT",
                    "Every free position slot went to a stronger idea in this run."
                    if account.free_slots > 0
                    else "All position slots are already in use by your current holdings.",
                )
            )
            continue

        try:
            result = check(cand, cash_left)
        except Exception as exc:  # noqa: BLE001 — one bad stock must not stop the batch
            verdicts.append(
                _refuse(
                    cand,
                    "ERROR",
                    f"The risk check failed for this stock ({exc}), so it is refused to stay safe.",
                )
            )
            continue
        if not result.allowed:
            verdicts.append(_refuse(cand, result.rule or "REFUSED", result.reason, result.amount_inr))
            continue

        qty, binding = result.qty, None
        if cand.bucket is not None:
            if account.sector_rule == "one_per_sector" and cand.bucket in approved_buckets:
                verdicts.append(
                    _refuse(
                        cand,
                        "SECTOR_CAP",
                        "A stronger idea in the same sector was approved first, and at this account size "
                        "the bot keeps to one stock per sector.",
                    )
                )
                continue
            if account.sector_cap_pct is not None:
                room = account.sector_cap_pct * account.portfolio_value - sector_used.get(cand.bucket, 0.0)
                qty, binding = _fit(qty, binding, room, cand.price, "SECTOR_CAP")
        qty, binding = _fit(qty, binding, deploy_left, cand.price, "DEPLOYABLE")
        if policy.mode is MarketMode.DEFENSIVE:
            qty = math.floor(qty * policy.defensive_size_factor)
            binding = binding or "DEFENSIVE_SIZE"

        value = qty * cand.price
        if qty < 1 or value < account.min_position_inr:
            rule = binding or "MIN_POSITION"
            limit = _SHRUNK.get(rule, "limits")
            verdicts.append(
                _refuse(
                    cand,
                    rule,
                    f"After stronger ideas in this run, the {limit} leaves room for only "
                    f"{format_inr(value)} — below the "
                    f"{format_inr(account.min_position_inr)} minimum position.",
                    value,
                )
            )
            continue

        note = result.reason
        if binding is not None:
            note = f"{note}; shrunk to fit the {_SHRUNK[binding]}"
        verdicts.append(
            RiskVerdict(
                symbol=cand.symbol, allowed=True, max_qty=qty, rule=binding, reason=note, amount_inr=value
            )
        )
        approved += 1
        slots_left -= 1
        cash_left -= buy_cost(cand.price, qty)
        deploy_left -= value
        if cand.bucket is not None:
            sector_used[cand.bucket] = sector_used.get(cand.bucket, 0.0) + value
            approved_buckets.add(cand.bucket)

    return _with_notes(verdicts, notes)
