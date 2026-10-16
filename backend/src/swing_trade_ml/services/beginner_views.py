"""Read-only helpers that turn trade plans into beginner-friendly numbers.

Pure functions: no database, no settings writes.
"""

from __future__ import annotations

from swing_trade_ml.core.config import settings
from swing_trade_ml.services.costs import compute_charges


def _charges(turnover: float, side: str) -> float:
    brokerage, taxes = compute_charges(turnover, side)
    return brokerage + taxes


def _unavailable(why: str) -> dict:
    return {
        "available": False,
        "why": why,
        "invested": 0.0,
        "loss_if_stop": 0.0,
        "gain_if_target": 0.0,
        "gain_if_half_out": 0.0,
        "charges_round_trip": 0.0,
    }


def money_at_stake(
    entry: float | None,
    stop: float | None,
    target: float | None,
    qty: int,
) -> dict:
    """Rupees at stake for a plan, after real charges.

    `loss_if_stop` and `gain_if_target` are net of the buy leg plus the sell
    leg at their own exit price. `charges_round_trip` is the buy leg plus the
    sell leg at the TARGET price. `gain_if_half_out` sells qty // 2 at
    entry * (1 + ML_FIRST_TARGET_PCT) and the rest at target, each sell leg
    paying its own charges (including the flat depository fee).
    """
    if qty is None or qty <= 0:
        return _unavailable("No shares allowed")
    if entry is None or stop is None or target is None or stop >= entry or target <= entry:
        return _unavailable("Plan incomplete")

    invested = qty * entry
    buy = _charges(invested, "BUY")
    sell_stop = _charges(qty * stop, "SELL")
    sell_target = _charges(qty * target, "SELL")

    loss = (entry - stop) * qty + buy + sell_stop
    gain = (target - entry) * qty - buy - sell_target

    first_qty = qty // 2
    rest_qty = qty - first_qty
    first_price = entry * (1 + settings.ML_FIRST_TARGET_PCT)
    half = (first_price - entry) * first_qty + (target - entry) * rest_qty - buy
    if first_qty > 0:
        half -= _charges(first_qty * first_price, "SELL")
    half -= _charges(rest_qty * target, "SELL")

    return {
        "available": True,
        "why": None,
        "invested": round(invested, 2),
        "loss_if_stop": round(loss, 2),
        "gain_if_target": round(gain, 2),
        "gain_if_half_out": round(half, 2),
        "charges_round_trip": round(buy + sell_target, 2),
    }
