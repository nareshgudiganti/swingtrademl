# Mutual Funds Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Track mutual fund holdings (units, purchase NAV/date) against free official AMFI NAV data, showing current value, returns, and basic risk per holding, in a new Finance tab. Track-and-analyze only — no fund recommendations.

**Architecture:** Three new tables (`MutualFund` scheme master, `MutualFundNav` time series, `MutualFundHolding` user positions), a daily AMFI-sync job, a new router, and an 8th tab on the existing Finance page.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, APScheduler, `httpx` (already a dependency — used by the Kite broker client) for the AMFI download, pytest, React, TanStack Query.

**Spec:** `docs/superpowers/specs/2026-09-12-mutual-funds-tracking-design.md`

## Global Constraints

- Data source is AMFI's own public `NAVAll.txt` disclosure only — no scraping, no third-party wrapper API (spec §4).
- Only `is_tracked=True` schemes get NAV history synced; the full ~10,000-scheme AMFI list is stored for search but not historically backfilled (spec §5-6).
- Track and analyze only — no fund ranking/recommendation logic in this plan (spec §2).
- Manual holding entry only — no CAMS/KFintech import (spec §3).

---

### Task 1: Data model + migration

**Files:**
- Create: `backend/src/swing_trade_ml/db/models/mutual_funds.py`
- Modify: `backend/src/swing_trade_ml/db/models/__init__.py` (register the new models)
- Create: `backend/alembic/versions/<timestamp>_mutual_funds.py`
- Test: `backend/tests/test_mutual_funds_models.py`

**Interfaces:**
- Produces: `MutualFund(id, scheme_code, name, amc_name, category, is_tracked)`, `MutualFundNav(scheme_id, date, nav)`, `MutualFundHolding(id, scheme_id, units, purchase_nav, purchase_date, notes)` — every later task in this plan imports these exact names from `swing_trade_ml.db.models.mutual_funds`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_mutual_funds_models.py
"""Shape tests for the mutual fund tables — see
docs/superpowers/specs/2026-09-12-mutual-funds-tracking-design.md §5."""

from __future__ import annotations

from datetime import date

from swing_trade_ml.db.models.mutual_funds import MutualFund, MutualFundHolding, MutualFundNav


def test_mutual_fund_and_nav_and_holding_round_trip(db_session):
    fund = MutualFund(
        scheme_code="100033",
        name="Test Bluechip Fund - Direct Growth",
        amc_name="Test AMC",
        category="Equity",
        is_tracked=True,
    )
    db_session.add(fund)
    db_session.flush()

    nav_row = MutualFundNav(scheme_id=fund.id, date=date(2026, 1, 1), nav=45.67)
    holding = MutualFundHolding(
        scheme_id=fund.id, units=100.0, purchase_nav=40.0, purchase_date=date(2025, 6, 1),
    )
    db_session.add_all([nav_row, holding])
    db_session.flush()

    assert fund.is_tracked is True
    assert nav_row.nav == 45.67
    assert holding.units == 100.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_mutual_funds_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'swing_trade_ml.db.models.mutual_funds'`

- [ ] **Step 3: Write the model file**

```python
# backend/src/swing_trade_ml/db/models/mutual_funds.py
"""Mutual fund tracking: scheme master, NAV history, and the user's own
holdings. Unrelated to the trading engine, same as db/models/finance.py —
personal net-worth data sharing this app's infrastructure.

Data source is AMFI's own public NAVAll.txt disclosure (see
services/finance/mutual_funds.py) — the fund industry's own regulator-
mandated publication, not a scrape of a third party's page.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from swing_trade_ml.db.base import Base, TimestampMixin


class MutualFund(Base, TimestampMixin):
    """One AMFI scheme. The full AMFI universe (~10,000 schemes) is stored
    here for search, but only is_tracked=True schemes get NAV history
    synced — see services/finance/mutual_funds.py::sync_nav_snapshot."""

    __tablename__ = "mutual_funds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scheme_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    amc_name: Mapped[str | None] = mapped_column(String(128))
    category: Mapped[str | None] = mapped_column(String(64))
    is_tracked: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    navs: Mapped[list["MutualFundNav"]] = relationship(back_populates="scheme")
    holdings: Mapped[list["MutualFundHolding"]] = relationship(back_populates="scheme")


class MutualFundNav(Base):
    """One NAV observation. No surrogate id and no TimestampMixin, same
    reasoning as db/models/market.py::Candle — one row per scheme per date
    is the natural key, nothing foreign-keys to an individual NAV row, and
    this table is large enough that two extra timestamptz columns matter."""

    __tablename__ = "mutual_fund_navs"
    __table_args__ = (UniqueConstraint("scheme_id", "date", name="uq_mf_nav_scheme_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scheme_id: Mapped[int] = mapped_column(ForeignKey("mutual_funds.id", ondelete="CASCADE"), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    nav: Mapped[float] = mapped_column(Float)

    scheme: Mapped[MutualFund] = relationship(back_populates="navs")


class MutualFundHolding(Base, TimestampMixin):
    """One purchase lot. Multiple lots per scheme are allowed — average
    cost is computed at read time (services/finance/mutual_funds.py), never
    stored, matching FinanceLoan's "compute fresh, never persist" pattern."""

    __tablename__ = "mutual_fund_holdings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scheme_id: Mapped[int] = mapped_column(ForeignKey("mutual_funds.id", ondelete="CASCADE"), index=True)
    units: Mapped[float] = mapped_column(Float)
    purchase_nav: Mapped[float] = mapped_column(Float)
    purchase_date: Mapped[date] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)

    scheme: Mapped[MutualFund] = relationship(back_populates="holdings")
```

- [ ] **Step 4: Register the models**

In `backend/src/swing_trade_ml/db/models/__init__.py`, add:

```python
from swing_trade_ml.db.models.mutual_funds import MutualFund, MutualFundHolding, MutualFundNav
```

and add `"MutualFund", "MutualFundHolding", "MutualFundNav",` to the `__all__` list (alphabetically, after `"MLModel",` per the file's existing sort order).

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/test_mutual_funds_models.py -v`
Expected: PASS

- [ ] **Step 6: Generate and edit the Alembic migration**

Run: `cd backend && alembic revision -m "mutual_funds"`

Edit the generated file's body to:

```python
def upgrade() -> None:
    op.create_table(
        "mutual_funds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scheme_code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("amc_name", sa.String(length=128), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("is_tracked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_mutual_funds_scheme_code", "mutual_funds", ["scheme_code"], unique=True)
    op.create_index("ix_mutual_funds_name", "mutual_funds", ["name"])
    op.create_index("ix_mutual_funds_is_tracked", "mutual_funds", ["is_tracked"])

    op.create_table(
        "mutual_fund_navs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scheme_id", sa.Integer(), sa.ForeignKey("mutual_funds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("nav", sa.Float(), nullable=False),
        sa.UniqueConstraint("scheme_id", "date", name="uq_mf_nav_scheme_date"),
    )
    op.create_index("ix_mutual_fund_navs_scheme_id", "mutual_fund_navs", ["scheme_id"])
    op.create_index("ix_mutual_fund_navs_date", "mutual_fund_navs", ["date"])

    op.create_table(
        "mutual_fund_holdings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scheme_id", sa.Integer(), sa.ForeignKey("mutual_funds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("units", sa.Float(), nullable=False),
        sa.Column("purchase_nav", sa.Float(), nullable=False),
        sa.Column("purchase_date", sa.Date(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_mutual_fund_holdings_scheme_id", "mutual_fund_holdings", ["scheme_id"])


def downgrade() -> None:
    op.drop_table("mutual_fund_holdings")
    op.drop_index("ix_mutual_fund_navs_date", table_name="mutual_fund_navs")
    op.drop_index("ix_mutual_fund_navs_scheme_id", table_name="mutual_fund_navs")
    op.drop_table("mutual_fund_navs")
    op.drop_index("ix_mutual_funds_is_tracked", table_name="mutual_funds")
    op.drop_index("ix_mutual_funds_name", table_name="mutual_funds")
    op.drop_index("ix_mutual_funds_scheme_code", table_name="mutual_funds")
    op.drop_table("mutual_funds")
```

(Keep the auto-generated `revision`/`down_revision`/docstring header exactly as generated — same rule as every migration in this codebase.)

- [ ] **Step 7: Verify the migration applies**

Run: `cd backend && alembic upgrade head`
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add backend/src/swing_trade_ml/db/models/mutual_funds.py backend/src/swing_trade_ml/db/models/__init__.py backend/alembic/versions/ backend/tests/test_mutual_funds_models.py
git commit -m "feat: add mutual fund data model

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: AMFI NAV sync service

**Files:**
- Create: `backend/src/swing_trade_ml/services/finance/mutual_funds.py`
- Test: `backend/tests/test_mutual_funds_sync.py`

**Interfaces:**
- Consumes: `MutualFund`, `MutualFundNav` (Task 1)
- Produces: `parse_navall(raw_text: str) -> list[dict]`, `sync_nav_snapshot(db: Session, raw_text: str | None = None) -> int`, `backfill_scheme_history(db: Session, scheme_id: int, nav_rows: list[dict]) -> int` — Task 3's job calls `sync_nav_snapshot`; Task 4's API calls `backfill_scheme_history`.

AMFI's `NAVAll.txt` format (pipe-delimited, category header lines with no
pipes, a blank line before each category):

```
Scheme Code;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date

Open Ended Schemes(Equity Scheme - Large Cap Fund)

100033;INF204K01UN8;-;Test Bluechip Fund - Direct Growth;45.6700;01-Jan-2026
```

(Real AMFI files use `;` as the delimiter, and a scheme's ISIN fields are
often `-` when not applicable — both handled below.)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_mutual_funds_sync.py
"""AMFI NAVAll.txt parsing and sync — see
docs/superpowers/specs/2026-09-12-mutual-funds-tracking-design.md §4, §6."""

from __future__ import annotations

from datetime import date

from swing_trade_ml.db.models.mutual_funds import MutualFund, MutualFundNav

SAMPLE_NAVALL = """Scheme Code;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date

Open Ended Schemes(Equity Scheme - Large Cap Fund)

100033;INF204K01UN8;-;Test Bluechip Fund - Direct Growth;45.6700;01-Jan-2026
100034;INF204K01UN9;-;Test Bluechip Fund - Regular Growth;44.1200;01-Jan-2026

Open Ended Schemes(Debt Scheme - Liquid Fund)

200011;INF109K01234;-;Test Liquid Fund - Direct Growth;1234.5600;01-Jan-2026
"""


def test_parse_navall_extracts_rows_with_category():
    from swing_trade_ml.services.finance.mutual_funds import parse_navall

    rows = parse_navall(SAMPLE_NAVALL)

    assert len(rows) == 3
    first = rows[0]
    assert first["scheme_code"] == "100033"
    assert first["name"] == "Test Bluechip Fund - Direct Growth"
    assert first["nav"] == 45.67
    assert first["date"] == date(2026, 1, 1)
    assert first["category"] == "Equity Scheme - Large Cap Fund"
    assert rows[2]["category"] == "Debt Scheme - Liquid Fund"


def test_sync_nav_snapshot_only_appends_navs_for_tracked_schemes(db_session):
    from swing_trade_ml.services.finance.mutual_funds import sync_nav_snapshot

    tracked = MutualFund(scheme_code="100033", name="old name", is_tracked=True)
    db_session.add(tracked)
    db_session.commit()

    count = sync_nav_snapshot(db_session, raw_text=SAMPLE_NAVALL)

    # 3 schemes seen in the feed -> 3 MutualFund rows upserted (name/category
    # kept fresh for all of them), but NAV history only appended for the one
    # already marked is_tracked.
    assert db_session.query(MutualFund).count() == 3
    assert count == 1
    nav_rows = db_session.query(MutualFundNav).filter_by(scheme_id=tracked.id).all()
    assert len(nav_rows) == 1
    assert nav_rows[0].nav == 45.67

    db_session.refresh(tracked)
    assert tracked.name == "Test Bluechip Fund - Direct Growth"  # kept in sync


def test_sync_nav_snapshot_is_idempotent_for_the_same_date(db_session):
    from swing_trade_ml.services.finance.mutual_funds import sync_nav_snapshot

    tracked = MutualFund(scheme_code="100033", name="Test Bluechip Fund - Direct Growth", is_tracked=True)
    db_session.add(tracked)
    db_session.commit()

    sync_nav_snapshot(db_session, raw_text=SAMPLE_NAVALL)
    sync_nav_snapshot(db_session, raw_text=SAMPLE_NAVALL)  # same date, run twice

    nav_rows = db_session.query(MutualFundNav).filter_by(scheme_id=tracked.id).all()
    assert len(nav_rows) == 1  # not duplicated
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_mutual_funds_sync.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement the service**

```python
# backend/src/swing_trade_ml/services/finance/mutual_funds.py
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
    A category header is any non-empty line with no ';' — it applies to
    every scheme line until the next header. The first (column-name) line
    is skipped because it also has no ';'-separated numeric fields we can
    use, but does contain ';' — detected by its Scheme Code field not being
    parseable as a code (it's the literal word "Scheme Code")."""
    rows: list[dict[str, Any]] = []
    current_category = ""

    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        if ";" not in line:
            # "Open Ended Schemes(Equity Scheme - Large Cap Fund)" -> the text
            # inside the parentheses is the category; fall back to the raw
            # line if the shape doesn't match (defensive, not expected).
            if "(" in line and line.endswith(")"):
                current_category = line[line.index("(") + 1 : -1]
            else:
                current_category = line
            continue

        fields = [f.strip() for f in line.split(";")]
        if len(fields) < 6 or fields[0] == "Scheme Code":
            continue  # header row or malformed line

        scheme_code, _isin1, _isin2, name, nav_str, date_str = fields[:6]
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
        response = httpx.get(NAVALL_URL, timeout=30.0)
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
```

Add `httpx` to `backend/pyproject.toml`'s dependencies if it isn't already there — check first:

Run: `cd backend && grep -n "httpx" pyproject.toml`

(It is very likely already a dependency via the Kite broker client — `brokers/kite.py` — confirm before adding a duplicate.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_mutual_funds_sync.py -v`
Expected: PASS

- [ ] **Step 5: Add unit tests for `holding_value` and `holding_risk`**

Add to `backend/tests/test_mutual_funds_sync.py`:

```python
from swing_trade_ml.db.models.mutual_funds import MutualFundHolding


def test_holding_value_computes_absolute_and_annualized_return():
    from swing_trade_ml.services.finance.mutual_funds import holding_value

    holding = MutualFundHolding(units=100.0, purchase_nav=40.0, purchase_date=date(2025, 1, 1))
    result = holding_value(holding, latest_nav=44.0)

    assert result["current_value"] == 4400.0
    assert result["cost_basis"] == 4000.0
    assert result["absolute_return"] == 400.0
    assert round(result["absolute_return_pct"], 4) == 0.10


def test_holding_risk_computes_volatility_and_drawdown():
    from swing_trade_ml.services.finance.mutual_funds import holding_risk

    # Rises to 110, falls to 90 (an 18.2% drawdown from the 110 peak), recovers to 100.
    result = holding_risk([100, 105, 110, 95, 90, 100])

    assert result["volatility"] > 0
    assert round(result["max_drawdown"], 3) == -0.182
```

- [ ] **Step 6: Run all tests to verify they pass**

Run: `cd backend && pytest tests/test_mutual_funds_sync.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/src/swing_trade_ml/services/finance/mutual_funds.py backend/tests/test_mutual_funds_sync.py backend/pyproject.toml
git commit -m "feat: AMFI NAV sync and holding value/risk calculations

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: Daily sync job

**Files:**
- Modify: `backend/src/swing_trade_ml/workers/jobs.py`
- Modify: `backend/src/swing_trade_ml/workers/scheduler.py`

**Interfaces:**
- Consumes: `sync_nav_snapshot` (Task 2)
- Produces: `job_sync_mutual_fund_navs()`

- [ ] **Step 1: Add the job function**

In `backend/src/swing_trade_ml/workers/jobs.py`, add near the other end-of-day jobs:

```python
def job_sync_mutual_fund_navs() -> None:
    """Daily AMFI NAV pull for every tracked mutual fund scheme."""
    try:
        from swing_trade_ml.services.finance import mutual_funds

        with session_scope() as db:
            mutual_funds.sync_nav_snapshot(db)
    except Exception as exc:  # noqa: BLE001
        _report_error("sync_mutual_fund_navs", exc)
```

- [ ] **Step 2: Register it in the scheduler**

In `backend/src/swing_trade_ml/workers/scheduler.py`, add after the `daily_summary` job registration (`hour=16, minute=0`) — AMFI typically publishes the day's NAVs late evening, so this runs well after market-hours jobs:

```python
    scheduler.add_job(
        jobs.job_sync_mutual_fund_navs,
        CronTrigger(day_of_week=WEEKDAYS, hour=21, minute=30, timezone=IST),
        id="sync_mutual_fund_navs",
        replace_existing=True,
    )
```

- [ ] **Step 3: Verify the job runs standalone**

Run: `cd backend && python -c "from swing_trade_ml.workers.jobs import job_sync_mutual_fund_navs; job_sync_mutual_fund_navs()"`
Expected: no exception. With zero tracked schemes yet, this makes one real HTTP call to AMFI and appends nothing — confirm it doesn't error even with an empty tracked set.

- [ ] **Step 4: Commit**

```bash
git add backend/src/swing_trade_ml/workers/jobs.py backend/src/swing_trade_ml/workers/scheduler.py
git commit -m "feat: schedule daily mutual fund NAV sync

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: API endpoints

**Files:**
- Create: `backend/src/swing_trade_ml/api/v1/endpoints/mutual_funds.py`
- Modify: `backend/src/swing_trade_ml/api/v1/router.py` (or wherever routers are registered — check `api/v1/` for the existing aggregation point, e.g. `grep -rn "include_router" backend/src/swing_trade_ml/api/v1/`)
- Modify: `backend/src/swing_trade_ml/schemas/__init__.py`
- Test: `backend/tests/test_mutual_funds_api.py`

**Interfaces:**
- Consumes: `MutualFund`, `MutualFundHolding`, `MutualFundNav` (Task 1), `holding_value`, `holding_risk`, `backfill_scheme_history` (Task 2).
- Produces: `GET /mutual-funds/search`, `POST /mutual-funds/holdings`, `GET /mutual-funds/holdings`, `PATCH/DELETE /mutual-funds/holdings/{id}`, `GET /mutual-funds/{scheme_id}/history`.

- [ ] **Step 1: Add schemas**

In `backend/src/swing_trade_ml/schemas/__init__.py`, add a new section at the end:

```python
# --------------------------------------------------------------- mutual funds --


class MutualFundSearchResult(BaseModel):
    scheme_id: int
    scheme_code: str
    name: str
    amc_name: str | None
    category: str | None
    is_tracked: bool


class MutualFundHoldingCreate(BaseModel):
    scheme_id: int
    units: float = Field(..., gt=0)
    purchase_nav: float = Field(..., gt=0)
    purchase_date: date
    notes: str | None = None


class MutualFundHoldingUpdate(BaseModel):
    units: float | None = Field(None, gt=0)
    purchase_nav: float | None = Field(None, gt=0)
    purchase_date: date | None = None
    notes: str | None = None


class MutualFundHoldingOut(BaseModel):
    id: int
    scheme_id: int
    scheme_name: str
    category: str | None
    units: float
    purchase_nav: float
    purchase_date: date
    latest_nav: float | None
    current_value: float | None
    cost_basis: float
    absolute_return: float | None
    absolute_return_pct: float | None
    annualized_return_pct: float | None
    volatility: float | None
    max_drawdown: float | None


class MutualFundNavPoint(BaseModel):
    date: date
    nav: float
```

(Add `date` to this file's existing `from datetime import ...` import line if it isn't already imported — check the top of `schemas/__init__.py` first.)

- [ ] **Step 2: Write the failing tests**

```python
# backend/tests/test_mutual_funds_api.py
"""API tests for mutual fund holdings — see
docs/superpowers/specs/2026-09-12-mutual-funds-tracking-design.md §8."""

from __future__ import annotations

from datetime import date

from swing_trade_ml.db.models.mutual_funds import MutualFund, MutualFundNav

HEADERS = {"X-API-Key": "test-api-key"}


def _fund(db_session, scheme_code="100033", name="Test Fund - Direct Growth", tracked=False):
    fund = MutualFund(scheme_code=scheme_code, name=name, category="Equity", is_tracked=tracked)
    db_session.add(fund)
    db_session.flush()
    return fund


def test_search_finds_scheme_by_name(client, db_session):
    _fund(db_session, name="Test Bluechip Fund - Direct Growth")
    db_session.commit()

    resp = client.get("/api/v1/mutual-funds/search", params={"q": "Bluechip"}, headers=HEADERS)

    assert resp.status_code == 200
    results = resp.json()
    assert any(r["name"] == "Test Bluechip Fund - Direct Growth" for r in results)


def test_add_holding_marks_scheme_tracked(client, db_session):
    fund = _fund(db_session, tracked=False)
    db_session.commit()

    resp = client.post(
        "/api/v1/mutual-funds/holdings",
        json={"scheme_id": fund.id, "units": 100.0, "purchase_nav": 40.0, "purchase_date": "2025-06-01"},
        headers=HEADERS,
    )

    assert resp.status_code == 201
    db_session.refresh(fund)
    assert fund.is_tracked is True


def test_list_holdings_includes_computed_returns(client, db_session):
    fund = _fund(db_session, tracked=True)
    db_session.add(MutualFundNav(scheme_id=fund.id, date=date(2026, 1, 1), nav=44.0))
    db_session.commit()

    create_resp = client.post(
        "/api/v1/mutual-funds/holdings",
        json={"scheme_id": fund.id, "units": 100.0, "purchase_nav": 40.0, "purchase_date": "2025-06-01"},
        headers=HEADERS,
    )
    assert create_resp.status_code == 201

    resp = client.get("/api/v1/mutual-funds/holdings", headers=HEADERS)

    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["latest_nav"] == 44.0
    assert rows[0]["current_value"] == 4400.0
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_mutual_funds_api.py -v`
Expected: FAIL — 404 (router not registered yet)

- [ ] **Step 4: Implement the router**

```python
# backend/src/swing_trade_ml/api/v1/endpoints/mutual_funds.py
"""Mutual fund holdings — search, add/edit/remove a lot, list with computed
returns and risk. See
docs/superpowers/specs/2026-09-12-mutual-funds-tracking-design.md §8.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from swing_trade_ml.api.deps import DbSession
from swing_trade_ml.db.models.mutual_funds import MutualFund, MutualFundHolding, MutualFundNav
from swing_trade_ml.schemas import (
    MessageResponse,
    MutualFundHoldingCreate,
    MutualFundHoldingOut,
    MutualFundHoldingUpdate,
    MutualFundNavPoint,
    MutualFundSearchResult,
)
from swing_trade_ml.services.finance import mutual_funds as mf_service

router = APIRouter(prefix="/mutual-funds", tags=["mutual-funds"])


@router.get("/search", response_model=list[MutualFundSearchResult])
def search(db: DbSession, q: str = Query(..., min_length=2)) -> list[MutualFund]:
    funds = db.execute(
        select(MutualFund).where(MutualFund.name.ilike(f"%{q}%")).limit(25)
    ).scalars().all()
    return [
        MutualFundSearchResult(
            scheme_id=f.id, scheme_code=f.scheme_code, name=f.name,
            amc_name=f.amc_name, category=f.category, is_tracked=f.is_tracked,
        )
        for f in funds
    ]


def _holding_out(db: DbSession, holding: MutualFundHolding) -> MutualFundHoldingOut:
    fund = db.get(MutualFund, holding.scheme_id)
    latest = db.execute(
        select(MutualFundNav)
        .where(MutualFundNav.scheme_id == holding.scheme_id)
        .order_by(MutualFundNav.date.desc())
        .limit(1)
    ).scalar_one_or_none()

    value = mf_service.holding_value(holding, latest.nav) if latest else None
    history = [
        n.nav for n in db.execute(
            select(MutualFundNav).where(MutualFundNav.scheme_id == holding.scheme_id).order_by(MutualFundNav.date)
        ).scalars().all()
    ]
    risk = mf_service.holding_risk(history) if len(history) >= 2 else None

    return MutualFundHoldingOut(
        id=holding.id, scheme_id=holding.scheme_id, scheme_name=fund.name if fund else "Unknown",
        category=fund.category if fund else None, units=holding.units, purchase_nav=holding.purchase_nav,
        purchase_date=holding.purchase_date, latest_nav=latest.nav if latest else None,
        current_value=value["current_value"] if value else None,
        cost_basis=holding.units * holding.purchase_nav,
        absolute_return=value["absolute_return"] if value else None,
        absolute_return_pct=value["absolute_return_pct"] if value else None,
        annualized_return_pct=value["annualized_return_pct"] if value else None,
        volatility=risk["volatility"] if risk else None,
        max_drawdown=risk["max_drawdown"] if risk else None,
    )


@router.post("/holdings", response_model=MutualFundHoldingOut, status_code=status.HTTP_201_CREATED)
def create_holding(payload: MutualFundHoldingCreate, db: DbSession) -> MutualFundHoldingOut:
    fund = db.get(MutualFund, payload.scheme_id)
    if fund is None:
        raise HTTPException(status_code=404, detail="Scheme not found")

    holding = MutualFundHolding(
        scheme_id=payload.scheme_id, units=payload.units, purchase_nav=payload.purchase_nav,
        purchase_date=payload.purchase_date, notes=payload.notes,
    )
    db.add(holding)

    was_tracked = fund.is_tracked
    fund.is_tracked = True
    db.commit()
    db.refresh(holding)

    if not was_tracked:
        # New to tracking — seed at least today's NAV so the holdings list
        # isn't empty of price data until tomorrow's sync job runs. A full
        # historical backfill (spec §6) is a separate, explicitly deferred
        # follow-up once the AMFI historical-file endpoint is confirmed
        # (see the spec's §11 open items) — this seed keeps the feature
        # usable in the meantime.
        mf_service.sync_nav_snapshot(db)

    return _holding_out(db, holding)


@router.get("/holdings", response_model=list[MutualFundHoldingOut])
def list_holdings(db: DbSession) -> list[MutualFundHoldingOut]:
    holdings = db.execute(select(MutualFundHolding)).scalars().all()
    return [_holding_out(db, h) for h in holdings]


@router.patch("/holdings/{holding_id}", response_model=MutualFundHoldingOut)
def update_holding(holding_id: int, payload: MutualFundHoldingUpdate, db: DbSession) -> MutualFundHoldingOut:
    holding = db.get(MutualFundHolding, holding_id)
    if holding is None:
        raise HTTPException(status_code=404, detail="Holding not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(holding, field, value)
    db.commit()
    db.refresh(holding)
    return _holding_out(db, holding)


@router.delete("/holdings/{holding_id}", response_model=MessageResponse)
def delete_holding(holding_id: int, db: DbSession) -> MessageResponse:
    holding = db.get(MutualFundHolding, holding_id)
    if holding is None:
        raise HTTPException(status_code=404, detail="Holding not found")
    db.delete(holding)
    db.commit()
    return MessageResponse(message="Holding removed")


@router.get("/{scheme_id}/history", response_model=list[MutualFundNavPoint])
def scheme_history(scheme_id: int, db: DbSession) -> list[MutualFundNavPoint]:
    rows = db.execute(
        select(MutualFundNav).where(MutualFundNav.scheme_id == scheme_id).order_by(MutualFundNav.date)
    ).scalars().all()
    return [MutualFundNavPoint(date=r.date, nav=r.nav) for r in rows]
```

- [ ] **Step 5: Register the router**

Run: `cd backend && grep -n "include_router" src/swing_trade_ml/api/v1/router.py`

Add, following the exact pattern the existing `finance` router registration uses in that file:

```python
from swing_trade_ml.api.v1.endpoints import mutual_funds

api_router.include_router(mutual_funds.router)
```

(Match the existing import/variable names in that file exactly — `router.py`'s aggregator variable may be named differently; adjust to match.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_mutual_funds_api.py -v`
Expected: PASS

- [ ] **Step 7: Run the full backend test suite**

Run: `cd backend && pytest -v`
Expected: PASS, no regressions.

- [ ] **Step 8: Commit**

```bash
git add backend/src/swing_trade_ml/api/v1/endpoints/mutual_funds.py backend/src/swing_trade_ml/api/v1/router.py backend/src/swing_trade_ml/schemas/__init__.py backend/tests/test_mutual_funds_api.py
git commit -m "feat: add mutual fund holdings API

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: Extend `/net-worth` to include mutual fund value

**Files:**
- Modify: `backend/src/swing_trade_ml/api/v1/endpoints/finance.py` (the `net_worth` function, ~line 267)
- Modify: `backend/src/swing_trade_ml/schemas/__init__.py` (`FinanceNetWorth`)
- Test: `backend/tests/test_finance_calculation.py` (existing file — add one test)

**Interfaces:**
- Consumes: `MutualFundHolding`, `MutualFundNav`, `holding_value` (Tasks 1-2)
- Produces: `FinanceNetWorth.mutual_funds_value: float` — a new field, additive to the existing response shape.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_finance_calculation.py` (check that file's existing imports/fixtures first and match its style):

```python
def test_net_worth_includes_mutual_fund_value(client, db_session):
    from datetime import date
    from swing_trade_ml.db.models.mutual_funds import MutualFund, MutualFundHolding, MutualFundNav

    fund = MutualFund(scheme_code="100033", name="Test Fund", is_tracked=True)
    db_session.add(fund)
    db_session.flush()
    db_session.add(MutualFundNav(scheme_id=fund.id, date=date(2026, 1, 1), nav=44.0))
    db_session.add(MutualFundHolding(scheme_id=fund.id, units=100.0, purchase_nav=40.0, purchase_date=date(2025, 6, 1)))
    db_session.commit()

    resp = client.get("/api/v1/finance/net-worth", headers={"X-API-Key": "test-api-key"})

    assert resp.status_code == 200
    assert resp.json()["mutual_funds_value"] == 4400.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_finance_calculation.py::test_net_worth_includes_mutual_fund_value -v`
Expected: FAIL — `KeyError: 'mutual_funds_value'`

- [ ] **Step 3: Add the field to the schema**

In `backend/src/swing_trade_ml/schemas/__init__.py`, find `class FinanceNetWorth(BaseModel):` and add a field: `mutual_funds_value: float = 0.0`.

- [ ] **Step 4: Compute it in the endpoint**

In `backend/src/swing_trade_ml/api/v1/endpoints/finance.py`'s `net_worth` function, before the `return FinanceNetWorth(...)`, add:

```python
    from swing_trade_ml.db.models.mutual_funds import MutualFund, MutualFundHolding, MutualFundNav
    from swing_trade_ml.services.finance import mutual_funds as mf_service

    mf_holdings = db.execute(select(MutualFundHolding)).scalars().all()
    mutual_funds_value = 0.0
    for holding in mf_holdings:
        latest = db.execute(
            select(MutualFundNav)
            .where(MutualFundNav.scheme_id == holding.scheme_id)
            .order_by(MutualFundNav.date.desc())
            .limit(1)
        ).scalar_one_or_none()
        if latest:
            mutual_funds_value += mf_service.holding_value(holding, latest.nav)["current_value"]
```

And add `mutual_funds_value=mutual_funds_value,` to the `FinanceNetWorth(...)` construction, and `+ mutual_funds_value` to the existing `net_worth=cash_surplus + investments_total - liabilities` line (making it `net_worth=cash_surplus + investments_total + mutual_funds_value - liabilities`).

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/test_finance_calculation.py -v`
Expected: PASS (including all pre-existing tests in the file — confirms the addition didn't change net worth for accounts with no MF holdings, since `mutual_funds_value` defaults to `0.0`).

- [ ] **Step 6: Commit**

```bash
git add backend/src/swing_trade_ml/api/v1/endpoints/finance.py backend/src/swing_trade_ml/schemas/__init__.py backend/tests/test_finance_calculation.py
git commit -m "feat: include mutual fund value in net worth

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 6: Frontend — Mutual Funds tab on Finance page

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/pages/Finance.tsx`

**Interfaces:**
- Consumes: `MutualFundHoldingOut`/`MutualFundSearchResult` shapes (Task 4), `Stat`, `Modal` (existing components), `formatCurrency`/`formatDate` (existing).

- [ ] **Step 1: Add types**

In `frontend/src/api/types.ts`, add:

```typescript
export interface MutualFundSearchResult {
  scheme_id: number
  scheme_code: string
  name: string
  amc_name: string | null
  category: string | null
  is_tracked: boolean
}

export interface MutualFundHolding {
  id: number
  scheme_id: number
  scheme_name: string
  category: string | null
  units: number
  purchase_nav: number
  purchase_date: string
  latest_nav: number | null
  current_value: number | null
  cost_basis: number
  absolute_return: number | null
  absolute_return_pct: number | null
  annualized_return_pct: number | null
  volatility: number | null
  max_drawdown: number | null
}
```

- [ ] **Step 2: Add client methods**

In `frontend/src/api/client.ts`, following the file's existing `get`/`post`/`patch`/`del` wrapper conventions (check how `financeLoans` or similar is implemented and match exactly):

```typescript
  mutualFundSearch: (q: string) => get<MutualFundSearchResult[]>(`/mutual-funds/search?q=${encodeURIComponent(q)}`),
  mutualFundHoldings: () => get<MutualFundHolding[]>('/mutual-funds/holdings'),
  createMutualFundHolding: (payload: { scheme_id: number; units: number; purchase_nav: number; purchase_date: string; notes?: string }) =>
    post<MutualFundHolding>('/mutual-funds/holdings', payload),
  deleteMutualFundHolding: (id: number) => del(`/mutual-funds/holdings/${id}`),
```

Add `MutualFundHolding`, `MutualFundSearchResult` to this file's type imports.

- [ ] **Step 3: Add the tab**

In `frontend/src/pages/Finance.tsx`:

1. Add `{ key: 'mutual-funds', label: 'Mutual Funds' }` to the `TABS` array.
2. Add `{tab === 'mutual-funds' && <MutualFundsTab />}` alongside the other `{tab === '...' && <...Tab />}` lines.
3. Add a new component in the same file, following the file's existing tab-component pattern (check `LoansTab`'s shape and match its structure — `useQuery`/`useMutation`, a `Modal`-based add form, a `Stat` summary row):

```typescript
function MutualFundsTab() {
  const queryClient = useQueryClient()
  const [showAdd, setShowAdd] = useState(false)
  const [search, setSearch] = useState('')
  const [selectedScheme, setSelectedScheme] = useState<{ id: number; name: string } | null>(null)
  const [units, setUnits] = useState('')
  const [purchaseNav, setPurchaseNav] = useState('')
  const [purchaseDate, setPurchaseDate] = useState('')

  const holdings = useQuery({ queryKey: ['mutualFundHoldings'], queryFn: api.mutualFundHoldings })
  const searchResults = useQuery({
    queryKey: ['mutualFundSearch', search],
    queryFn: () => api.mutualFundSearch(search),
    enabled: search.length >= 2,
  })

  const createHolding = useMutation({
    mutationFn: api.createMutualFundHolding,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['mutualFundHoldings'] })
      setShowAdd(false)
      setSelectedScheme(null)
      setUnits('')
      setPurchaseNav('')
      setPurchaseDate('')
    },
  })

  const deleteHolding = useMutation({
    mutationFn: api.deleteMutualFundHolding,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['mutualFundHoldings'] }),
  })

  const rows = holdings.data ?? []
  const totalCurrentValue = rows.reduce((sum, r) => sum + (r.current_value ?? 0), 0)
  const totalCostBasis = rows.reduce((sum, r) => sum + r.cost_basis, 0)
  const totalReturn = totalCurrentValue - totalCostBasis

  return (
    <>
      <div className="grid">
        <Stat label="Current value" value={formatCurrency(totalCurrentValue)} />
        <Stat label="Invested" value={formatCurrency(totalCostBasis)} />
        <Stat
          label="Return"
          value={formatCurrency(totalReturn)}
          tone={totalReturn >= 0 ? 'pos' : 'neg'}
        />
      </div>

      <button onClick={() => setShowAdd(true)}>Add holding</button>

      {holdings.isLoading && <Loading />}
      {!holdings.isLoading && rows.length === 0 && <Empty message="No mutual fund holdings yet." />}

      {rows.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Scheme</th>
                <th>Category</th>
                <th>Units</th>
                <th>Current value</th>
                <th>Return</th>
                <th>Annualized</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td>{r.scheme_name}</td>
                  <td>{r.category ?? '—'}</td>
                  <td>{r.units}</td>
                  <td>{r.current_value != null ? formatCurrency(r.current_value) : '—'}</td>
                  <td className={(r.absolute_return ?? 0) >= 0 ? 'pos' : 'neg'}>
                    {r.absolute_return_pct != null ? `${(r.absolute_return_pct * 100).toFixed(1)}%` : '—'}
                  </td>
                  <td>
                    {r.annualized_return_pct != null ? `${(r.annualized_return_pct * 100).toFixed(1)}%` : '—'}
                  </td>
                  <td>
                    <button onClick={() => deleteHolding.mutate(r.id)}>Remove</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showAdd && (
        <Modal onClose={() => setShowAdd(false)}>
          <h2>Add mutual fund holding</h2>
          <input
            placeholder="Search fund by name"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          {searchResults.data?.map((r) => (
            <div key={r.scheme_id} onClick={() => setSelectedScheme({ id: r.scheme_id, name: r.name })}>
              {r.name}
            </div>
          ))}
          {selectedScheme && (
            <>
              <p>Selected: {selectedScheme.name}</p>
              <input placeholder="Units" value={units} onChange={(e) => setUnits(e.target.value)} />
              <input
                placeholder="Purchase NAV"
                value={purchaseNav}
                onChange={(e) => setPurchaseNav(e.target.value)}
              />
              <input type="date" value={purchaseDate} onChange={(e) => setPurchaseDate(e.target.value)} />
              <button
                className="primary"
                disabled={!units || !purchaseNav || !purchaseDate}
                onClick={() =>
                  createHolding.mutate({
                    scheme_id: selectedScheme.id,
                    units: Number(units),
                    purchase_nav: Number(purchaseNav),
                    purchase_date: purchaseDate,
                  })
                }
              >
                Add
              </button>
            </>
          )}
        </Modal>
      )}
    </>
  )
}
```

Check `Finance.tsx`'s top-of-file imports for `useMutation`, `useQueryClient`, `Modal`, `Stat`, `Loading`, `Empty` — they are almost certainly already imported (used by other tabs in the same file); do not duplicate an import.

- [ ] **Step 4: Verify it builds and typechecks**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: no errors.

- [ ] **Step 5: Visual check**

Use the `run` skill / `browser-automation` skill against the running dev containers to confirm the Mutual Funds tab renders, search works, and adding a holding shows up in the table.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/client.ts frontend/src/pages/Finance.tsx
git commit -m "feat: add Mutual Funds tab to Finance page

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```
