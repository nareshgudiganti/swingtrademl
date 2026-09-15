"""Per-strategy exit policy: partial profit booking and the time stop.

One place, read by both the live/paper exit check (services/execution.py's
check_exits) and the backtest replay (services/backtest.py), for the same
reason services/costs.py exists: if the two paths each parsed these knobs
themselves, a backtest and a paper result would quietly stop meaning the same
thing the first time one of them was edited.

Everything here is opt-in through `Strategy.params` (JSON, so no migration):

* ``scale_out_at_pct`` — gain from entry at which part of the position is sold,
  e.g. ``0.05`` for +5%. Absent or null means scale-out is off, which is how
  every strategy created before this existed keeps behaving exactly as it did.
* ``scale_out_fraction`` — share of the held quantity sold at that point.
  Default 0.5 (bank half, let the rest run).
* ``time_stop_days`` — calendar days after entry at which a still-open position
  is closed regardless of P&L. Default 60, the value that was hard-coded before.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from swing_trade_ml.core.config import settings

DEFAULT_SCALE_OUT_FRACTION = 0.5
DEFAULT_TIME_STOP_DAYS = 60


@dataclass(frozen=True, slots=True)
class ExitPolicy:
    scale_out_at_pct: float | None = None
    scale_out_fraction: float = DEFAULT_SCALE_OUT_FRACTION
    time_stop_days: int = DEFAULT_TIME_STOP_DAYS

    @property
    def scale_out_enabled(self) -> bool:
        return self.scale_out_at_pct is not None


def exit_policy_for(params: dict[str, Any] | None) -> ExitPolicy:
    """Read the exit knobs from a strategy's params, falling back to today's
    behaviour for anything absent or nonsensical.

    Malformed values switch the feature OFF rather than raising: this runs
    inside the 60-second exit job, and a typo in one strategy's JSON must not
    stop stop-losses being honoured for every other position.
    """
    params = params or {}

    scale_out_at_pct: float | None = None
    raw_at = params.get("scale_out_at_pct")
    if raw_at is not None:
        try:
            value = float(raw_at)
        except (TypeError, ValueError):
            value = 0.0
        scale_out_at_pct = value if value > 0 else None

    fraction = DEFAULT_SCALE_OUT_FRACTION
    raw_fraction = params.get("scale_out_fraction")
    if raw_fraction is not None:
        try:
            fraction = float(raw_fraction)
        except (TypeError, ValueError):
            fraction = 0.0
        if not 0.0 < fraction < 1.0:
            # 0 sells nothing and 1 is just a full exit at the wrong level —
            # neither is a partial exit, so there is nothing sensible to do.
            scale_out_at_pct = None
            fraction = DEFAULT_SCALE_OUT_FRACTION

    time_stop_days = DEFAULT_TIME_STOP_DAYS
    raw_days = params.get("time_stop_days")
    if raw_days is not None:
        try:
            days = int(raw_days)
        except (TypeError, ValueError):
            days = 0
        if days > 0:
            time_stop_days = days

    return ExitPolicy(scale_out_at_pct, fraction, time_stop_days)


def scale_out_quantity(
    policy: ExitPolicy,
    *,
    entry_price: float,
    price: float,
    quantity: int,
    already_scaled_out: bool,
    min_position_value: float | None = None,
) -> int:
    """How many shares to sell at the first target right now — 0 means don't.

    Pure, so the live exit check and the backtest make the identical call.
    Returns 0 when: the strategy hasn't opted in; this position has already
    scaled out once; price hasn't reached the first target; the position is
    too small for a second flat depository fee to be worth paying
    (settings.SCALE_OUT_MIN_POSITION_INR); or the fraction rounds down to no
    shares, or to all of them (a 1-share position cannot be halved).
    """
    if not policy.scale_out_enabled or already_scaled_out or quantity < 2 or entry_price <= 0:
        return 0
    if price < entry_price * (1 + policy.scale_out_at_pct):
        return 0
    floor = settings.SCALE_OUT_MIN_POSITION_INR if min_position_value is None else min_position_value
    if price * quantity < floor:
        return 0
    # Round down: selling fewer shares than intended is harmless, selling
    # more than the strategy asked for is not. The epsilon stops float noise
    # (100 * 0.29 == 28.999999999999996) from costing a whole share.
    sell = math.floor(quantity * policy.scale_out_fraction + 1e-9)
    if sell < 1 or sell >= quantity:
        return 0
    return sell
