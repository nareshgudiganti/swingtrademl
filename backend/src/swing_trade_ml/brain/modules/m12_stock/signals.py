"""Who is buying: delivery percentage and big-investor deals.

Delivery: the share of traded shares actually taken home rather than traded
within the day. Above its own 20-day average on at least 3 of the last 5
days → "high" (buyers are holding, not flipping).

Deals: NSE's bulk and block deals are mostly high-frequency trading firms
buying and selling the same stock the same day (seen in our stored data:
QE Securities, HRTI, Jump Trading and the like). Those say nothing about
long-term buyers, so only KNOWN INSTITUTIONS count — mutual funds, insurers,
pension and sovereign funds, and the big foreign banks' investment arms —
and a client's buy and sell of one stock on the same day cancel out.
Pure: the caller passes rows known by the run's date.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from swing_trade_ml.brain.modules.m13_news.calendar import trading_days_until

AVERAGE_DAYS = 20
RECENT_DAYS = 5
ABOVE_NEEDED = 3
DEAL_DAYS = 10  # trading days

_INSTITUTION = re.compile(
    r"\bMUTUAL FUND\b|\bFUND\b|INSURANCE|ASSURANCE|PENSION|PROVIDENT|GOVERNMENT OF|"
    r"INVESTMENT AUTHORITY|MONETARY AUTHORITY|SOVEREIGN|ASSET MANAGEMENT|"
    r"GOLDMAN SACHS|MORGAN STANLEY|SOCIETE GENERALE|BNP PARIBAS|CITIGROUP|NOMURA|"
    r"BLACKROCK|VANGUARD|FIDELITY|J\.?P\.? ?MORGAN|MERRILL LYNCH|\bCLSA\b|\bUBS\b"
)


@dataclass(frozen=True, slots=True)
class DealRow:
    symbol: str
    day: date
    client: str
    side: str  # BUY | SELL
    quantity: int


def delivery_signal(rows: list[tuple[date, float | None]]) -> tuple[str | None, str | None]:
    values = [pct for _, pct in sorted(rows, key=lambda r: r[0]) if pct is not None]
    if len(values) < AVERAGE_DAYS + RECENT_DAYS:
        return None, None
    above = 0
    for i in range(len(values) - RECENT_DAYS, len(values)):
        before = values[i - AVERAGE_DAYS : i]
        if values[i] > sum(before) / len(before):
            above += 1
    if above >= ABOVE_NEEDED:
        return "high", (
            f"Delivery above average {above} of the last {RECENT_DAYS} days (buyers are taking shares home)."
        )
    return None, None


def is_institution(name: str) -> bool:
    return bool(_INSTITUTION.search(name.upper()))


def _indian(n: int) -> str:
    """1,20,000 style grouping."""
    s = str(abs(int(n)))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = ",".join(re.findall(r"\d{1,2}", head[::-1]))[::-1] if head else ""
        s = f"{head},{tail}"
    return s


def deal_signal(rows: list[DealRow], today: date) -> tuple[int, str | None]:
    """+1 net institutional buying, -1 net selling, 0 none, with a plain line
    naming the biggest deal."""
    recent = [
        r for r in rows if is_institution(r.client) and -DEAL_DAYS <= trading_days_until(today, r.day) <= 0
    ]
    sides: dict[tuple[str, date], set[str]] = defaultdict(set)
    for r in recent:
        sides[(r.client, r.day)].add(r.side)
    real = [r for r in recent if len(sides[(r.client, r.day)]) == 1]  # drop same-day round trips
    if not real:
        return 0, None
    net = sum(r.quantity if r.side == "BUY" else -r.quantity for r in real)
    if net == 0:
        return 0, None
    side = "BUY" if net > 0 else "SELL"
    biggest = max((r for r in real if r.side == side), key=lambda r: r.quantity)
    verb, word = ("bought", "buying") if side == "BUY" else ("sold", "selling")
    line = (
        f"Big-investor {word}: {biggest.client} {verb} {_indian(biggest.quantity)} shares "
        f"on {biggest.day:%d %b}."
    )
    return (1 if net > 0 else -1), line
