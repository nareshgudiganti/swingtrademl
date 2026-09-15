"""What the account-size ladder currently allows, and where the money
already is — the read side of the risk layer.

check_entry (services/risk.py) is where these numbers are ENFORCED; this
module is where the dashboard reads them, so the capital-ladder view and the
"why was this blocked" story can be built without duplicating any of that
logic.
"""

from __future__ import annotations

from fastapi import APIRouter

from swing_trade_ml.api.deps import DbSession
from swing_trade_ml.brokers import get_broker
from swing_trade_ml.ml.sector_map import get_sector_bucket, sector_display_name
from swing_trade_ml.schemas import CurrentLimitsOut, SectorExposureOut
from swing_trade_ml.services import deployable, risk
from swing_trade_ml.services.limits import limits_for
from swing_trade_ml.services.portfolio import portfolio_value_and_cash

router = APIRouter(prefix="/risk", tags=["risk"])


@router.get("/limits", response_model=CurrentLimitsOut)
def current_limits(db: DbSession) -> CurrentLimitsOut:
    """Everything a capital-ladder screen needs in one call: the resolved
    limits for the account's actual current size, how much the market
    conditions allow deployed right now, and where the money already sits
    by sector — the same inputs check_entry itself reads, so this can never
    show a rosier picture than what would actually be enforced.
    """
    mode = get_broker().mode
    portfolio_value, cash = portfolio_value_and_cash(db, mode)
    limits = limits_for(portfolio_value)
    context = deployable.current_deployable(db)

    holdings = risk.open_holdings(db, mode)
    invested = sum(h.value for h in holdings)

    by_sector: dict[str, float] = {}
    for h in holdings:
        bucket = get_sector_bucket(h.tradingsymbol)
        key = sector_display_name(bucket) if bucket else "Unclassified"
        by_sector[key] = by_sector.get(key, 0.0) + h.value

    return CurrentLimitsOut(
        portfolio_value=portfolio_value,
        cash=cash,
        rung_value=limits.rung_value,
        max_positions=limits.max_positions,
        open_positions=len(holdings),
        max_position_pct=limits.max_position_pct,
        min_position_inr=limits.min_position_inr,
        sector_rule=limits.sector_rule,
        sector_cap_pct=limits.sector_cap_pct,
        max_adv_pct=limits.max_adv_pct,
        scale_out_enabled=limits.scale_out_enabled,
        max_share_price_inr=limits.max_share_price_inr,
        allowed_cap_tiers=sorted(limits.allowed_cap_tiers),
        small_cap_budget_pct=limits.small_cap_budget_pct,
        cash_floor_inr=limits.cash_floor_inr,
        risk_per_trade_pct=limits.risk_per_trade_pct,
        max_drawdown_pct=limits.max_drawdown_pct,
        regime=context.regime,
        plain_regime=context.plain_regime,
        deployable_fraction=context.fraction,
        deployable_ceiling_inr=context.fraction * portfolio_value,
        invested_inr=invested,
        room_inr=max(context.fraction * portfolio_value - invested, 0.0),
        sectors=[
            SectorExposureOut(sector=name, value_inr=value, pct_of_portfolio=value / portfolio_value)
            for name, value in sorted(by_sector.items(), key=lambda kv: kv[1], reverse=True)
        ]
        if portfolio_value > 0
        else [],
    )
