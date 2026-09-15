"""Account-size-aware risk limits — the capital ladder.

The owner's plan is a ladder from ₹10,000 to ₹1 crore, not one fixed account
size. A single set of constants cannot serve that range: at ₹10,000 a
"10% in one stock" rule allows ₹1,000, which often cannot buy one share, and
at ₹1 crore a position sized like a ₹10 lakh one begins to move the price of
the stock it is buying. So every portfolio-level limit is a *function of
account value*, resolved here and nowhere else.

Three readers must agree on these numbers or the live scan, the risk gate and
the backtest silently drift apart: `services/risk.py` (`calculate_quantity`,
`check_entry`), `services/engine.py` (how many BUY candidates a scan acts on)
and `services/backtest.py` (the in-memory replay). All three call
`limits_for()`.

How values between rungs are chosen
-----------------------------------
* Continuous fields (position count, single-stock cap, minimum position,
  liquidity ceiling, small-cap budget, cash floor) are interpolated on
  log(portfolio value) between the two neighbouring rungs. The ladder itself
  is geometric (each rung roughly 2-10x the last), so a linear blend would put
  a ₹5 lakh account almost entirely on the ₹1 lakh settings; log spacing puts
  it roughly halfway, which is what "between rungs" means to a person.
  Integer fields are rounded.
* Discrete fields (whether the sector rule is "one per sector" or a
  percentage, which cap tiers are allowed, the share-price cap, whether
  scaling out is on) take the LOWER rung's value. A rule should switch on
  when the account has actually reached the size it was designed for, not
  partway there. The same applies to a continuous field that simply does not
  exist at the lower rung (the liquidity ceiling below ₹10 lakh, the
  small-cap budget below ₹10 lakh): it stays off until the rung that
  introduces it.
* Outside the ladder, values clamp to the nearest end rung.

The cash floor
--------------
The owner's decision is "₹1,00,000 never deployed at ₹10 lakh". Expressed as a
flat rupee amount that would make a ₹10,000 or ₹1 lakh account untradeable,
so it is a percentage of the account that grows with it: 0% at ₹10,000 (two
half-size positions are the whole design at that rung), 5% at ₹1 lakh and 10%
from ₹10 lakh upward, interpolated on the log scale between. That gives
exactly ₹1,00,000 at ₹10 lakh and keeps the floor proportionate at every
other size. Above ₹10 lakh it stays at 10% rather than rising further: the
market-regime ceiling (services/deployable.py) already holds back far more
than that in anything but a strong market.

Per-strategy overrides
----------------------
A strategy row can already carry `max_positions` and `capital_allocation`
(used as its single-stock cap). Where set they win over the ladder — they are
a deliberate, per-strategy choice made by the owner, and silently ignoring
them would be worse than the ladder being slightly less tidy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal

from swing_trade_ml.core.config import settings

if TYPE_CHECKING:
    from swing_trade_ml.db.models.trading import Strategy

SectorRule = Literal["one_per_sector", "pct_cap"]

LARGE = "large"
MID = "midcap"
SMALL = "smallcap"


@dataclass(frozen=True, slots=True)
class Limits:
    """Every limit the entry path enforces, for one account size.

    `rung_value` is the ladder rung the discrete rules came from, so a
    rejection can say which stage of the ladder the account is on.
    """

    portfolio_value: float
    rung_value: float
    max_positions: int
    max_position_pct: float
    min_position_inr: float
    sector_rule: SectorRule
    # Only meaningful when sector_rule == "pct_cap".
    sector_cap_pct: float | None
    # Max fraction of a stock's 20-day average daily traded value one position
    # may take. None = no liquidity ceiling at this size.
    max_adv_pct: float | None
    scale_out_enabled: bool
    # Shares priced above this are skipped. None = no cap.
    max_share_price_inr: float | None
    allowed_cap_tiers: frozenset[str]
    # Max fraction of the account in small-cap positions. None when small
    # caps are not allowed at all.
    small_cap_budget_pct: float | None
    cash_floor_pct: float
    # Not rung-dependent (owner decisions, read from settings), but carried
    # here so the entry path reads every limit from one object.
    risk_per_trade_pct: float
    max_drawdown_pct: float

    @property
    def cash_floor_inr(self) -> float:
        return self.portfolio_value * self.cash_floor_pct


@dataclass(frozen=True, slots=True)
class _Rung:
    value: float
    max_positions: int
    max_position_pct: float
    min_position_inr: float
    sector_rule: SectorRule
    sector_cap_pct: float | None
    max_adv_pct: float | None
    scale_out_enabled: bool
    max_share_price_inr: float | None
    allowed_cap_tiers: frozenset[str]
    small_cap_budget_pct: float | None
    cash_floor_pct: float


# The published ladder (see the capital-ladder design, "The ladder").
RUNGS: tuple[_Rung, ...] = (
    _Rung(
        value=10_000, max_positions=2, max_position_pct=0.50, min_position_inr=4_000,
        sector_rule="one_per_sector", sector_cap_pct=None, max_adv_pct=None,
        scale_out_enabled=False, max_share_price_inr=2_500,
        allowed_cap_tiers=frozenset({LARGE}), small_cap_budget_pct=None, cash_floor_pct=0.0,
    ),
    _Rung(
        value=100_000, max_positions=4, max_position_pct=0.25, min_position_inr=15_000,
        sector_rule="pct_cap", sector_cap_pct=0.25, max_adv_pct=None,
        scale_out_enabled=True, max_share_price_inr=None,
        allowed_cap_tiers=frozenset({LARGE, MID}), small_cap_budget_pct=None, cash_floor_pct=0.05,
    ),
    _Rung(
        value=1_000_000, max_positions=8, max_position_pct=0.10, min_position_inr=40_000,
        sector_rule="pct_cap", sector_cap_pct=0.25, max_adv_pct=0.02,
        scale_out_enabled=True, max_share_price_inr=None,
        allowed_cap_tiers=frozenset({LARGE, MID, SMALL}), small_cap_budget_pct=0.20,
        cash_floor_pct=0.10,
    ),
    _Rung(
        value=2_500_000, max_positions=12, max_position_pct=0.08, min_position_inr=60_000,
        sector_rule="pct_cap", sector_cap_pct=0.25, max_adv_pct=0.02,
        scale_out_enabled=True, max_share_price_inr=None,
        allowed_cap_tiers=frozenset({LARGE, MID, SMALL}), small_cap_budget_pct=0.20,
        cash_floor_pct=0.10,
    ),
    _Rung(
        value=5_000_000, max_positions=16, max_position_pct=0.06, min_position_inr=100_000,
        sector_rule="pct_cap", sector_cap_pct=0.25, max_adv_pct=0.015,
        scale_out_enabled=True, max_share_price_inr=None,
        allowed_cap_tiers=frozenset({LARGE, MID, SMALL}), small_cap_budget_pct=0.12,
        cash_floor_pct=0.10,
    ),
    _Rung(
        value=10_000_000, max_positions=22, max_position_pct=0.045, min_position_inr=150_000,
        sector_rule="pct_cap", sector_cap_pct=0.25, max_adv_pct=0.01,
        scale_out_enabled=True, max_share_price_inr=None,
        allowed_cap_tiers=frozenset({LARGE, MID, SMALL}), small_cap_budget_pct=0.08,
        cash_floor_pct=0.10,
    ),
)


def _blend(lo: float | None, hi: float | None, t: float) -> float | None:
    """Log-scale blend; a field absent at the lower rung stays absent (it
    switches on at the rung that introduces it, never partway there)."""
    if lo is None:
        return None
    if hi is None:
        return lo
    return lo + (hi - lo) * t


def limits_for(portfolio_value: float, strategy: Strategy | None = None) -> Limits:
    """Resolve the limits for an account of this value.

    A non-positive or missing value resolves to the smallest rung — the most
    restrictive reading, which is the safe one when the account value itself
    could not be read.
    """
    value = portfolio_value if portfolio_value and portfolio_value > 0 else RUNGS[0].value

    if value <= RUNGS[0].value:
        lo = hi = RUNGS[0]
        t = 0.0
    elif value >= RUNGS[-1].value:
        lo = hi = RUNGS[-1]
        t = 0.0
    else:
        idx = next(i for i in range(len(RUNGS) - 1) if RUNGS[i].value <= value < RUNGS[i + 1].value)
        lo, hi = RUNGS[idx], RUNGS[idx + 1]
        t = (math.log(value) - math.log(lo.value)) / (math.log(hi.value) - math.log(lo.value))

    limits = Limits(
        portfolio_value=float(portfolio_value or 0.0),
        rung_value=float(lo.value),
        max_positions=int(round(lo.max_positions + (hi.max_positions - lo.max_positions) * t)),
        max_position_pct=float(_blend(lo.max_position_pct, hi.max_position_pct, t)),
        min_position_inr=float(_blend(lo.min_position_inr, hi.min_position_inr, t)),
        sector_rule=lo.sector_rule,
        sector_cap_pct=_blend(lo.sector_cap_pct, hi.sector_cap_pct, t),
        max_adv_pct=_blend(lo.max_adv_pct, hi.max_adv_pct, t),
        scale_out_enabled=lo.scale_out_enabled,
        max_share_price_inr=lo.max_share_price_inr,
        allowed_cap_tiers=lo.allowed_cap_tiers,
        small_cap_budget_pct=_blend(lo.small_cap_budget_pct, hi.small_cap_budget_pct, t),
        cash_floor_pct=float(_blend(lo.cash_floor_pct, hi.cash_floor_pct, t)),
        risk_per_trade_pct=settings.RISK_PER_TRADE_PCT,
        max_drawdown_pct=settings.MAX_PORTFOLIO_DRAWDOWN_PCT,
    )

    if strategy is not None:
        overrides: dict[str, object] = {}
        if strategy.max_positions:
            overrides["max_positions"] = int(strategy.max_positions)
        if strategy.capital_allocation:
            overrides["max_position_pct"] = float(strategy.capital_allocation)
        if overrides:
            limits = replace(limits, **overrides)

    return limits


def format_inr(amount: float) -> str:
    """Indian digit grouping (₹1,00,000, not ₹100,000) — the way the owner
    reads money, so rejection reasons read naturally."""
    negative = amount < 0
    whole = str(int(round(abs(amount))))
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups) + "," + tail
    return f"{'-' if negative else ''}₹{whole}"
