"""What a planned trade would do to the portfolio: the stock's and its
sector's share before and after, the cash left, and plain warnings where a
limit would be crossed. It answers a question; it never places or approves
anything (the risk gate still decides). Pure.
"""

from __future__ import annotations

from swing_trade_ml.brain.modules.m11_sector.ranking import plain_name
from swing_trade_ml.ml.sector_map import _SECTOR_INDEX, get_sector_bucket
from swing_trade_ml.services.limits import format_inr


def what_if(
    symbol: str,
    qty: int,
    price: float,
    portfolio_value: float,
    cash: float,
    holdings: dict[str, float],
    max_position_pct: float,
    sector_cap_pct: float | None,
) -> dict:
    symbol = symbol.upper()
    value = qty * price
    pv = portfolio_value if portfolio_value > 0 else 1.0
    bucket = get_sector_bucket(symbol)
    sector_before = sum(
        v for s, v in holdings.items() if bucket is not None and get_sector_bucket(s) == bucket
    )
    stock_before = holdings.get(symbol, 0.0)
    out = {
        "symbol": symbol,
        "qty": qty,
        "price": price,
        "value": value,
        "cash_before": cash,
        "cash_after": cash - value,
        "stock_share_before": stock_before / pv,
        "stock_share_after": (stock_before + value) / pv,
        "sector": bucket,
        "sector_name": plain_name(_SECTOR_INDEX[bucket]) if bucket in _SECTOR_INDEX else None,
        "sector_share_before": sector_before / pv if bucket else None,
        "sector_share_after": (sector_before + value) / pv if bucket else None,
        "warnings": [],
    }
    if out["stock_share_after"] > max_position_pct:
        out["warnings"].append(
            f"This would put {out['stock_share_after']:.0%} of the portfolio in {symbol}, above the "
            f"{max_position_pct:.0%} limit for one stock."
        )
    if bucket and sector_cap_pct is not None and out["sector_share_after"] > sector_cap_pct:
        out["warnings"].append(
            f"{out['sector_name'] or bucket} would be {out['sector_share_after']:.0%} of the portfolio, "
            f"above the {sector_cap_pct:.0%} sector limit."
        )
    if value > cash:
        out["warnings"].append(
            f"It costs {format_inr(value)}, more than the {format_inr(cash)} cash available."
        )
    return out
