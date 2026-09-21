"""Buy & sell report and profit/loss for the real Zerodha account.

Profit is worked out first-bought-first-sold, the way Zerodha's own P&L does:
each sale is matched against the oldest shares still held. Matching always
runs over the *whole* history — a sale in this month can be matched to a buy
from last year — and the period only decides which sales are reported.

Charges come from the same cost model as everything else (`services/costs`),
so the number shown is profit after what Zerodha and the exchanges take.

A sale whose purchase is not on record (bought before capture began and no
tradebook imported) cannot be given a profit. It is listed separately rather
than guessed at, and never mixed into the totals.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from swing_trade_ml.db.models.fills import BrokerFill
from swing_trade_ml.services.costs import compute_charges

IST = ZoneInfo("Asia/Kolkata")


@dataclass
class _Lot:
    remaining: int
    price: float
    charge_per_share: float
    bought_at: datetime


def _charge(fill: BrokerFill) -> float:
    brokerage, taxes = compute_charges(fill.quantity * fill.price, fill.side)
    return brokerage + taxes


def _r(value: float) -> float:
    return round(value, 2)


def _match(
    fills: list[BrokerFill],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, deque[_Lot]]]:
    """FIFO over every fill. Returns (closed slices, unmatched sales, open lots)."""
    lots: dict[str, deque[_Lot]] = defaultdict(deque)
    closed: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []

    for f in sorted(fills, key=lambda x: (x.executed_at, x.id)):
        if f.side == "BUY":
            lots[f.symbol].append(
                _Lot(f.quantity, f.price, _charge(f) / f.quantity, f.executed_at)
            )
            continue

        sell_charge_per_share = _charge(f) / f.quantity
        to_sell = f.quantity
        queue = lots[f.symbol]
        while to_sell > 0 and queue:
            lot = queue[0]
            take = min(lot.remaining, to_sell)
            gross = (f.price - lot.price) * take
            charges = (lot.charge_per_share + sell_charge_per_share) * take
            cost = lot.price * take
            closed.append(
                {
                    "symbol": f.symbol,
                    "quantity": take,
                    "buy_date": lot.bought_at,
                    "sell_date": f.executed_at,
                    "buy_price": _r(lot.price),
                    "sell_price": _r(f.price),
                    "gross_pnl": _r(gross),
                    "charges": _r(charges),
                    "net_pnl": _r(gross - charges),
                    "pnl_pct": _r((gross - charges) / cost * 100) if cost else 0.0,
                    "holding_days": max((f.executed_at.date() - lot.bought_at.date()).days, 0),
                }
            )
            lot.remaining -= take
            to_sell -= take
            if lot.remaining == 0:
                queue.popleft()
        if to_sell > 0:
            unmatched.append(
                {
                    "symbol": f.symbol,
                    "quantity": to_sell,
                    "sell_date": f.executed_at,
                    "sell_price": _r(f.price),
                }
            )
    return closed, unmatched, lots


def _day(value: datetime) -> date:
    return value.astimezone(IST).date()


def build_report(
    db: Session,
    start: date | None,
    end: date | None,
    holdings: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """`holdings` is Zerodha's live holdings list, or None when not logged in."""
    fills = list(db.execute(select(BrokerFill)).scalars().all())
    closed_all, unmatched_all, _lots = _match(fills)

    def in_period(moment: datetime) -> bool:
        d = _day(moment)
        return (start is None or d >= start) and (end is None or d <= end)

    closed = [c for c in closed_all if in_period(c["sell_date"])]
    unmatched = [u for u in unmatched_all if in_period(u["sell_date"])]
    period_fills = [f for f in fills if in_period(f.executed_at)]

    by_symbol: dict[str, dict[str, Any]] = {}

    def row(symbol: str) -> dict[str, Any]:
        return by_symbol.setdefault(
            symbol,
            {
                "symbol": symbol,
                "bought_qty": 0,
                "bought_value": 0.0,
                "sold_qty": 0,
                "sold_value": 0.0,
                "realized_pnl": 0.0,
                "open_qty": 0,
                "open_avg_price": None,
                "last_price": None,
                "open_pnl": None,
            },
        )

    for f in period_fills:
        r = row(f.symbol)
        if f.side == "BUY":
            r["bought_qty"] += f.quantity
            r["bought_value"] += f.quantity * f.price
        else:
            r["sold_qty"] += f.quantity
            r["sold_value"] += f.quantity * f.price
    for c in closed:
        row(c["symbol"])["realized_pnl"] += c["net_pnl"]

    open_pnl_total: float | None = None
    open_value_total: float | None = None
    open_invested_total: float | None = None
    if holdings is not None:
        open_pnl_total = open_value_total = open_invested_total = 0.0
        for h in holdings:
            qty = h["quantity"]
            if not qty:
                continue
            r = row(h["symbol"])
            r["open_qty"] = qty
            r["open_avg_price"] = _r(h["average_price"])
            r["last_price"] = _r(h["last_price"])
            r["open_pnl"] = _r(h["pnl"])
            open_pnl_total += h["pnl"]
            open_value_total += qty * h["last_price"]
            open_invested_total += qty * h["average_price"]

    for r in by_symbol.values():
        r["bought_value"] = _r(r["bought_value"])
        r["sold_value"] = _r(r["sold_value"])
        r["realized_pnl"] = _r(r["realized_pnl"])

    net = sum(c["net_pnl"] for c in closed)
    wins = sum(1 for c in closed if c["net_pnl"] > 0)
    losses = sum(1 for c in closed if c["net_pnl"] < 0)
    per_symbol_net: dict[str, float] = defaultdict(float)
    for c in closed:
        per_symbol_net[c["symbol"]] += c["net_pnl"]
    best = max(per_symbol_net.items(), key=lambda kv: kv[1], default=None)
    worst = min(per_symbol_net.items(), key=lambda kv: kv[1], default=None)

    first_at, last_at, total_fills = db.execute(
        select(func.min(BrokerFill.executed_at), func.max(BrokerFill.executed_at), func.count(BrokerFill.id))
    ).one()

    return {
        "period": {"start": start, "end": end},
        "summary": {
            "bought_value": _r(sum(f.quantity * f.price for f in period_fills if f.side == "BUY")),
            "sold_value": _r(sum(f.quantity * f.price for f in period_fills if f.side == "SELL")),
            "buy_count": sum(1 for f in period_fills if f.side == "BUY"),
            "sell_count": sum(1 for f in period_fills if f.side == "SELL"),
            "realized_pnl": _r(net),
            "gross_pnl": _r(sum(c["gross_pnl"] for c in closed)),
            "charges": _r(sum(c["charges"] for c in closed)),
            "winning_sales": wins,
            "losing_sales": losses,
            "average_holding_days": (
                _r(sum(c["holding_days"] for c in closed) / len(closed)) if closed else None
            ),
            "best_stock": {"symbol": best[0], "pnl": _r(best[1])} if best and best[1] > 0 else None,
            "worst_stock": {"symbol": worst[0], "pnl": _r(worst[1])} if worst and worst[1] < 0 else None,
            "open_pnl": _r(open_pnl_total) if open_pnl_total is not None else None,
            "open_value": _r(open_value_total) if open_value_total is not None else None,
            "open_invested": _r(open_invested_total) if open_invested_total is not None else None,
        },
        "by_stock": sorted(by_symbol.values(), key=lambda r: r["symbol"]),
        "closed": sorted(closed, key=lambda c: c["sell_date"], reverse=True),
        "unmatched_sales": sorted(unmatched, key=lambda u: u["sell_date"], reverse=True),
        "fills": [
            {
                "id": f.id,
                "symbol": f.symbol,
                "side": f.side,
                "quantity": f.quantity,
                "price": _r(f.price),
                "value": _r(f.quantity * f.price),
                "executed_at": f.executed_at,
                "source": f.source,
            }
            for f in sorted(period_fills, key=lambda x: (x.executed_at, x.id), reverse=True)
        ],
        "records": {
            "total_fills": total_fills,
            "first_at": first_at,
            "last_at": last_at,
        },
    }
