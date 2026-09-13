"""AMFI NAV sync and holding calculations — see
docs/superpowers/specs/2026-09-12-mutual-funds-tracking-design.md.

Data source is AMFI's own public NAVAll.txt disclosure
(https://www.amfiindia.com/spages/NAVAll.txt), the mutual fund industry
body's regulator-mandated daily NAV publication — official data, not a
scrape of a third party's rendered page.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.mutual_funds import MutualFund, MutualFundHolding, MutualFundNav

log = get_logger(__name__)

NAVALL_URL = "https://www.amfiindia.com/spages/NAVAll.txt"


def parse_navall(raw_text: str) -> list[dict[str, Any]]:
    """Parse AMFI's pipe(;)-delimited NAVAll.txt into one dict per scheme.
    A category header is any non-empty line with no ';' whose text is
    wrapped as "Open Ended Schemes(...)"/"Close Ended Schemes(...)" — it
    applies to every scheme line until the next header. Any other line with
    no ';' (an AMC name banner like "Axis Mutual Fund", which AMFI prints
    between a category header and its scheme rows) is noise and is skipped
    without disturbing the current category.

    The scheme-row column count has drifted over time — older dumps are
    "Code;ISIN;ISIN;Name;NAV;Date" (6 fields); AMFI's current live format
    splits the plan/option out of the name into two extra columns, "Code;
    ISIN;ISIN;Name;Plan;Option;NAV;Date" (8 fields). Rather than assume a
    fixed column count, NAV and Date are always the *last* two fields and
    Name is always the 4th — both shapes agree on that."""
    rows: list[dict[str, Any]] = []
    current_category = ""

    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        if ";" not in line:
            # "Open Ended Schemes(Equity Scheme - Large Cap Fund)" -> the text
            # inside the parentheses is the category. A line with no parens
            # (e.g. an AMC name banner) isn't a category header — leave
            # current_category as-is rather than overwriting it with noise.
            if "(" in line and line.endswith(")"):
                current_category = line[line.index("(") + 1 : -1]
            continue

        fields = [f.strip() for f in line.split(";")]
        if len(fields) < 6 or fields[0] == "Scheme Code":
            continue  # header row or malformed line

        scheme_code, name = fields[0], fields[3]
        nav_str, date_str = fields[-2], fields[-1]
        try:
            nav = float(nav_str)
            nav_date = datetime.strptime(date_str, "%d-%b-%Y").date()
        except ValueError:
            continue  # a scheme with "N.A." NAV or unparseable date — skip it

        rows.append({
            "scheme_code": scheme_code,
            "name": name,
            "nav": nav,
            "date": nav_date,
            "category": current_category,
        })

    return rows


def sync_nav_snapshot(db: Session, raw_text: str | None = None) -> int:
    """Download (or accept, for tests) today's NAVAll.txt, upsert every
    scheme's name/category so search stays current, and append a NAV row
    only for schemes already marked is_tracked. Returns the count of NAV
    rows appended (not the count of schemes seen)."""
    if raw_text is None:
        # AMFI 302-redirects www.amfiindia.com to portal.amfiindia.com as of
        # 2026 — follow it rather than hardcoding the new host, since it has
        # moved before and may again.
        response = httpx.get(NAVALL_URL, timeout=30.0, follow_redirects=True)
        response.raise_for_status()
        raw_text = response.text

    rows = parse_navall(raw_text)
    appended = 0

    for row in rows:
        fund = db.execute(
            select(MutualFund).where(MutualFund.scheme_code == row["scheme_code"])
        ).scalar_one_or_none()
        if fund is None:
            fund = MutualFund(scheme_code=row["scheme_code"], name=row["name"], category=row["category"])
            db.add(fund)
            db.flush()
        else:
            fund.name = row["name"]
            fund.category = row["category"]

        if not fund.is_tracked:
            continue

        existing = db.execute(
            select(MutualFundNav).where(MutualFundNav.scheme_id == fund.id, MutualFundNav.date == row["date"])
        ).scalar_one_or_none()
        if existing is not None:
            continue

        db.add(MutualFundNav(scheme_id=fund.id, date=row["date"], nav=row["nav"]))
        appended += 1

    db.commit()
    if appended:
        log.info("mutual_funds.nav_synced", count=appended)
    return appended


def backfill_scheme_history(db: Session, scheme_id: int, nav_rows: list[dict[str, Any]]) -> int:
    """One-time historical load for a newly-tracked scheme. nav_rows is the
    already-parsed [{date, nav}, ...] list for that one scheme (from
    whichever historical AMFI endpoint the API layer fetched — see the
    endpoint layer for the actual HTTP call, kept out of this pure function
    so it stays testable without network access)."""
    added = 0
    for row in nav_rows:
        existing = db.execute(
            select(MutualFundNav).where(MutualFundNav.scheme_id == scheme_id, MutualFundNav.date == row["date"])
        ).scalar_one_or_none()
        if existing is not None:
            continue
        db.add(MutualFundNav(scheme_id=scheme_id, date=row["date"], nav=row["nav"]))
        added += 1
    db.commit()
    return added


def holding_value(holding: MutualFundHolding, latest_nav: float) -> dict[str, float]:
    """Current value and returns for one lot, computed fresh — never
    persisted, matching services/finance/loans.py's convention."""
    current_value = holding.units * latest_nav
    cost_basis = holding.units * holding.purchase_nav
    absolute_return = current_value - cost_basis
    absolute_return_pct = (absolute_return / cost_basis) if cost_basis else 0.0

    days_held = (date.today() - holding.purchase_date).days
    years_held = days_held / 365.25
    annualized_return_pct = (
        ((current_value / cost_basis) ** (1 / years_held) - 1) if cost_basis and years_held > 0 else 0.0
    )

    return {
        "current_value": current_value,
        "cost_basis": cost_basis,
        "absolute_return": absolute_return,
        "absolute_return_pct": absolute_return_pct,
        "annualized_return_pct": annualized_return_pct,
    }


def holding_risk(nav_history: list[float]) -> dict[str, float]:
    """Trailing volatility (stdev of daily returns) and max drawdown over
    whatever history is available — same statistical shape as
    ml/features.py's volatility_20, reused conceptually for a different
    domain rather than imported (mutual fund NAVs aren't a Candle)."""
    if len(nav_history) < 2:
        return {"volatility": 0.0, "max_drawdown": 0.0}

    returns = [
        (nav_history[i] - nav_history[i - 1]) / nav_history[i - 1]
        for i in range(1, len(nav_history))
        if nav_history[i - 1]
    ]
    if not returns:
        return {"volatility": 0.0, "max_drawdown": 0.0}

    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / len(returns)
    volatility = variance ** 0.5

    peak = nav_history[0]
    max_drawdown = 0.0
    for nav in nav_history:
        peak = max(peak, nav)
        drawdown = (nav - peak) / peak if peak else 0.0
        max_drawdown = min(max_drawdown, drawdown)

    return {"volatility": volatility, "max_drawdown": max_drawdown}
