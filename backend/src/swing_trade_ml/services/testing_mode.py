"""Testing mode: the brain's idea words ignore the account's money limits during practice.

While the brain is in practice (shadow) the owner wants to see how stocks behave on the model's
score alone, not which ideas a full paper account happened to have room for. So when
`TESTING_NO_LIMITS` is on, the brain's risk gate (M07) asks version 1's entry check to skip the
money rules: the market-conditions ceiling, positions, one-stock %, sector %, cash reserve,
liquidity, share price, cap tier and the drawdown halt.

Never relaxed: the owner's halt switch, an open position or cool-down in the same stock, the
avoid list, the cash actually in the account and the minimum position size.

Safe by construction:
  * Off by default.
  * Never on in live trading (`TRADING_MODE=live`, or both live latches open).
  * Only while the M18 stage is practice. The moment it moves to approval or auto the limits are
    back, with nothing to remember to switch.
  * Only the brain's risk gate passes the waiver. Version 1's own order path never does.
  * An unreadable stage keeps the limits.
"""

from __future__ import annotations

from dataclasses import replace

from sqlalchemy.orm import Session

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.services.brain_golive.stage import current_stage
from swing_trade_ml.services.limits import LARGE, MID, SMALL, Limits

log = get_logger(__name__)

NO_LIMIT_POSITIONS = 100_000


def live_trading_possible() -> bool:
    """True if real money could be at risk, or the mode asks for it."""
    return settings.TRADING_MODE == "live" or settings.is_live_trading


def limits_waived(db: Session) -> bool:
    if not settings.TESTING_NO_LIMITS or live_trading_possible():
        return False
    try:
        return current_stage(db) == "shadow"
    except Exception as exc:  # noqa: BLE001 — an unreadable stage must keep the limits
        log.warning("testing_mode.stage_unreadable", error=str(exc))
        return False


def relaxed(limits: Limits) -> Limits:
    """`limits` with every money percentage and count removed."""
    return replace(
        limits,
        max_positions=NO_LIMIT_POSITIONS,
        max_position_pct=1.0,
        sector_rule="pct_cap",
        sector_cap_pct=None,
        max_adv_pct=None,
        max_share_price_inr=None,
        allowed_cap_tiers=frozenset({LARGE, MID, SMALL}),
        small_cap_budget_pct=None,
        cash_floor_pct=0.0,
        max_drawdown_pct=float("inf"),
    )
