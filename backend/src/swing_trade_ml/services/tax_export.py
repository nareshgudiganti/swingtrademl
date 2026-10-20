"""Real-account sales for one Indian financial year, laid out for tax records.

Read-only. It takes the same real Zerodha trades as the buy & sell report
(`broker_fills`: the daily Kite capture plus any imported Console tradebook) —
never the bot's paper book or the tester book — and the same first-in,
first-out matching (`real_report._match`), run over the whole history so a sale
this year can be matched to a buy from an earlier year.

It sorts each matched slice into short-term (held 12 months or less),
long-term (more than 12 months) or same-day, and adds them up. It does not
work out tax owed, rates or exemptions: that is for Zerodha's Tax P&L and a
tax adviser.

Charges are the app's cost-model estimate (`services/costs`); Zerodha's
actual contract-note charges are not stored.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.db.models.fills import BrokerFill
from swing_trade_ml.services.real_report import _match

IST = ZoneInfo("Asia/Kolkata")

SHORT = "Short-term"
LONG = "Long-term"
SAME_DAY = "Same day (intraday)"

ADVICE_NOTE = (
    "For your records — check against Zerodha's Tax P&L (Console) and ask a tax adviser. "
    "This file does not work out any tax."
)
METHOD_NOTE = (
    "Sales are matched to the oldest shares bought first (first in, first out), the way Zerodha does. "
    "A sale split across several buys is shown as one row per buy."
)
TERM_NOTE = (
    "Short-term = held 12 months or less; long-term = held more than 12 months. "
    "Bought and sold on the same day is listed apart, because Zerodha reports it as intraday."
)
CHARGES_NOTE = (
    "Charges are estimated with this app's cost model (STT, exchange and SEBI fees, stamp duty, GST and the "
    "DP fee on sells; no brokerage on delivery). Your Zerodha contract notes show the exact amounts."
)
MISSING_NOTE = (
    "Rows marked 'Buy details missing' are sales whose purchase is not saved in the app, so no gain is "
    "worked out and they are left out of the totals. Import your Zerodha tradebook to fill them in."
)
LIMITS_NOTE = (
    "Not covered: share splits, bonus shares and other corporate actions, and shares received as gifts or "
    "transfers — these change the buy price and are not adjusted here."
)

CSV_HEADER = [
    "Stock",
    "Bought on",
    "Sold on",
    "Shares",
    "Buy value (₹)",
    "Sell value (₹)",
    "Estimated charges (₹)",
    "Gain or loss after charges (₹)",
    "Days held",
    "Short-term or long-term",
    "Note",
]

_YEAR = re.compile(r"^(\d{4})-(\d{2})$")


def _r(value: float) -> float:
    return round(value, 2)


def _day(moment: datetime) -> date:
    return moment.astimezone(IST).date()


def fy_label(day: date) -> str:
    """The Indian financial year a date falls in, e.g. 1 Apr 2025 to 31 Mar 2026 is "2025-26"."""
    start = day.year if day.month >= 4 else day.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def fy_bounds(label: str) -> tuple[date, date]:
    """First and last day of a financial year written like "2025-26". ValueError if it isn't."""
    m = _YEAR.match(label or "")
    if not m or int(m.group(2)) != (int(m.group(1)) + 1) % 100:
        raise ValueError(f"'{label}' is not a financial year. Write it like 2025-26.")
    start = int(m.group(1))
    return date(start, 4, 1), date(start + 1, 3, 31)


def current_fy(today: date | None = None) -> str:
    return fy_label(today or datetime.now(IST).date())


def _one_year_after(day: date) -> date:
    try:
        return day.replace(year=day.year + 1)
    except ValueError:  # 29 February
        return day.replace(year=day.year + 1, day=28)


def holding_type(buy_day: date, sell_day: date) -> str:
    if sell_day == buy_day:
        return SAME_DAY
    return LONG if sell_day > _one_year_after(buy_day) else SHORT


def build_tax_export(db: Session, year: str) -> dict[str, Any]:
    start, end = fy_bounds(year)
    fills = list(db.execute(select(BrokerFill)).scalars().all())
    closed, unmatched, _lots = _match(fills)

    rows: list[dict[str, Any]] = []
    for c in closed:
        sold = _day(c["sell_date"])
        if not start <= sold <= end:
            continue
        bought = _day(c["buy_date"])
        rows.append(
            {
                "stock": c["symbol"],
                "buy_date": bought,
                "sell_date": sold,
                "quantity": c["quantity"],
                "buy_value": c["buy_value"],
                "sell_value": c["sell_value"],
                "charges": c["charges"],
                # From the rounded columns, so each row adds up in a spreadsheet.
                "gain": _r(c["sell_value"] - c["buy_value"] - c["charges"]),
                "days_held": (sold - bought).days,
                "type": holding_type(bought, sold),
                "buy_missing": False,
            }
        )
    for u in unmatched:
        sold = _day(u["sell_date"])
        if not start <= sold <= end:
            continue
        rows.append(
            {
                "stock": u["symbol"],
                "buy_date": None,
                "sell_date": sold,
                "quantity": u["quantity"],
                "buy_value": None,
                "sell_value": _r(u["sell_price"] * u["quantity"]),
                "charges": None,
                "gain": None,
                "days_held": None,
                "type": None,
                "buy_missing": True,
            }
        )
    rows.sort(key=lambda r: (r["sell_date"], r["stock"], r["buy_missing"], r["buy_date"] or date.min))

    counted = [r for r in rows if not r["buy_missing"]]

    def total(kind: str) -> float:
        return _r(sum(r["gain"] for r in counted if r["type"] == kind))

    years = {fy_label(_day(f.executed_at)) for f in fills if f.side == "SELL"}
    years.add(current_fy())
    years.add(year)

    return {
        "year": year,
        "start": start,
        "end": end,
        "years": sorted(years, reverse=True),
        "rows": rows,
        "totals": {
            "short_term": total(SHORT),
            "long_term": total(LONG),
            "same_day": total(SAME_DAY),
            "charges": _r(sum(r["charges"] for r in counted)),
            "buy_value": _r(sum(r["buy_value"] for r in counted)),
            "sell_value": _r(sum(r["sell_value"] for r in counted)),
            "sales": len(counted),
            "missing_buy_count": len(rows) - len(counted),
        },
        "charges_are_estimates": True,
        "method": "FIFO",
        "notes": [ADVICE_NOTE, METHOD_NOTE, TERM_NOTE, CHARGES_NOTE, MISSING_NOTE, LIMITS_NOTE],
    }


def _text(value: str) -> str:
    """A spreadsheet must never read a stock name as a formula."""
    return f"'{value}" if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


def _blank(value: Any) -> Any:
    return "" if value is None else value


def to_csv(export: dict[str, Any]) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\r\n")
    w.writerow(CSV_HEADER)
    for r in export["rows"]:
        w.writerow(
            [
                _text(r["stock"]),
                _blank(r["buy_date"] and r["buy_date"].isoformat()),
                r["sell_date"].isoformat(),
                r["quantity"],
                _blank(r["buy_value"]),
                r["sell_value"],
                _blank(r["charges"]),
                _blank(r["gain"]),
                _blank(r["days_held"]),
                _blank(r["type"]),
                "Buy details missing — not in the totals" if r["buy_missing"] else "",
            ]
        )
    t = export["totals"]
    start, end = export["start"], export["end"]
    w.writerow([])
    title = f"Financial year {export['year']} (1 Apr {start.year} to 31 Mar {end.year}), real Zerodha account"
    w.writerow([title])
    w.writerow(["Short-term gain or loss after charges (₹)", t["short_term"]])
    w.writerow(["Long-term gain or loss after charges (₹)", t["long_term"]])
    w.writerow(["Same-day (intraday) gain or loss after charges (₹)", t["same_day"]])
    w.writerow(["Total estimated charges (₹)", t["charges"]])
    w.writerow(["Sales counted", t["sales"]])
    w.writerow(["Sales with buy details missing (not counted)", t["missing_buy_count"]])
    w.writerow([])
    for note in export["notes"]:
        w.writerow([note])
    return out.getvalue()
