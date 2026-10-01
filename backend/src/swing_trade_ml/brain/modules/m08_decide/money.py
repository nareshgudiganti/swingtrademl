"""Money helpers for decisions: round-trip cost and expected result in R."""

from __future__ import annotations

from swing_trade_ml.brain.modules.m08_decide.policy import DecidePolicy
from swing_trade_ml.core.enums import TransactionType
from swing_trade_ml.services.costs import apply_slippage, compute_charges


def cost_pct(price: float, qty: int) -> float:
    """Round-trip cost (both legs' slippage and charges) as a share of the buy value."""
    buy_fill = apply_slippage(price, TransactionType.BUY)
    sell_fill = apply_slippage(price, TransactionType.SELL)
    charges = sum(compute_charges(buy_fill * qty, TransactionType.BUY)) + sum(
        compute_charges(sell_fill * qty, TransactionType.SELL)
    )
    return ((buy_fill - sell_fill) * qty + charges) / (price * qty)


def expected_r(p_win: float, round_trip_cost_pct: float, policy: DecidePolicy) -> float:
    """Average result per trade in R (1 R = the stop distance): a target hit is
    worth `reward_r`, a stop costs 1, and costs come off the top."""
    return p_win * policy.reward_r - (1 - p_win) * 1.0 - round_trip_cost_pct / policy.stop_pct
