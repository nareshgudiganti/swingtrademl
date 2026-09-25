# Factor Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every instrument a real market-cap tier and sector from NSE index membership, add cross-sectional factor scoring (trend and low volatility), and stop advisory strategies from stealing position slots.

**Architecture:** NSE publishes index constituent CSVs on the same archive host the codebase already pulls bhavcopy from, so membership follows the existing `fetch` / `parse_*` / `load_*` pattern in `services/market_feeds.py`. Factor scores are cross-sectional percentile ranks over the day's universe, computed in a new pure `services/factors.py` that takes a feature frame and returns scores — no database access, so it is fully table-testable.

**Tech Stack:** Python 3.12, SQLAlchemy 2.x, Alembic, pandas, httpx, pytest, Postgres.

**Spec:** `docs/superpowers/specs/2026-09-25-factor-selection-and-experiments-design.md`

## Global Constraints

- Test command is `./.venv/Scripts/python.exe -m pytest` run from `backend/`. A bare `python -m pytest` has no pytest installed and fails with "No module named pytest".
- Tests need Postgres on `localhost:5433`. It is running. Docker's CLI returns HTTP 500 from an API version mismatch, which does **not** mean the database is down — check the port, not `docker ps`.
- Factor scores are percentile ranks 0-100 computed **across stocks on one day**, never against absolute thresholds.
- `FEATURE_COLUMNS` in `ml/features.py` and the trained model are **not** to be modified. `return_120d` and `return_250d` are factor inputs only. Appending factor scores to the model's features is explicitly out of scope (spec section 3, and four prior attempts moved nothing).
- A stock in none of the three NSE lists gets tier `unknown` and is excluded from tier-filtered universes. Never default to `large` — that defaulting is the bug being fixed.
- Migrations live in `backend/alembic/versions/` named `YYYYMMDD_HHMM_description.py`.
- Every new NSE fetch must fail loudly rather than serve stale data (tracker risk R6).

## Review Focus

1. **NSE returns an HTML block page instead of CSV.** The site blocks bots without notice. The parser must raise rather than write zero rows that look like a successful empty day. *(Task 1)*
2. **A symbol appears in two index lists at once.** NSE overlaps lists during rebalance windows. Tier assignment must be deterministic, not dependent on dict iteration order. *(Task 1)*
3. **A universe of one stock.** Percentile ranking a single row must produce a valid score, not a division error. *(Task 5)*
4. **Every stock identical on a factor.** Ranks must all be equal and the composite still valid, not NaN. *(Task 5)*
5. **A watchlisted instrument in none of the three lists.** Must end `unknown` and be excluded, never silently treated as large-cap. *(Task 3)*

---

### Task 1: Parse NSE index constituent CSVs

**Files:**
- Modify: `backend/src/swing_trade_ml/services/market_feeds.py`
- Test: `backend/tests/test_index_membership.py` (create)

**Interfaces:**
- Consumes: `fetch(url)` and the module's existing `HEADERS` / `TIMEOUT`.
- Produces: `INDEX_LISTS: dict[str, str]` mapping tier to URL, and `parse_index_list(content: bytes, tier: str) -> list[dict]` returning rows of `{"symbol": str, "tier": str, "industry": str}`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_index_membership.py`:

```python
"""NSE index constituent lists — the source of every stock's cap tier."""

from __future__ import annotations

import pytest

from swing_trade_ml.services.market_feeds import INDEX_LISTS, parse_index_list

SAMPLE = (
    b"Company Name,Industry,Symbol,Series,ISIN Code\r\n"
    b"ABB India Ltd.,Capital Goods,ABB,EQ,INE117A01022\r\n"
    b"Adani Enterprises Ltd.,Metals & Mining,ADANIENT,EQ,INE423A01024\r\n"
)


def test_parses_symbol_tier_and_industry():
    rows = parse_index_list(SAMPLE, "large")
    assert rows == [
        {"symbol": "ABB", "tier": "large", "industry": "Capital Goods"},
        {"symbol": "ADANIENT", "tier": "large", "industry": "Metals & Mining"},
    ]


def test_all_three_tiers_have_urls():
    assert set(INDEX_LISTS) == {"large", "midcap", "smallcap"}
    for url in INDEX_LISTS.values():
        assert url.startswith("https://nsearchives.nseindia.com/")


def test_html_block_page_raises_rather_than_returning_no_rows():
    """NSE blocks bots without notice. An empty list would look like a
    successful empty day and silently wipe every tier on load."""
    with pytest.raises(ValueError, match="not a constituent CSV"):
        parse_index_list(b"<html><body>Access Denied</body></html>", "large")


def test_row_missing_symbol_is_skipped_not_fatal():
    content = (
        b"Company Name,Industry,Symbol,Series,ISIN Code\r\n"
        b"Broken Ltd.,Power,,EQ,INE000A01001\r\n"
        b"Good Ltd.,Power,GOOD,EQ,INE000A01002\r\n"
    )
    assert parse_index_list(content, "midcap") == [
        {"symbol": "GOOD", "tier": "midcap", "industry": "Power"}
    ]


def test_symbol_is_uppercased_and_stripped():
    content = (
        b"Company Name,Industry,Symbol,Series,ISIN Code\r\n"
        b"Spaced Ltd.,Power, good ,EQ,INE000A01002\r\n"
    )
    assert parse_index_list(content, "midcap")[0]["symbol"] == "GOOD"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_index_membership.py -v`
Expected: FAIL with `ImportError: cannot import name 'INDEX_LISTS'`

- [ ] **Step 3: Implement the parser**

In `backend/src/swing_trade_ml/services/market_feeds.py`, add beside the other URL constants (near line 51, after `GSM_URL`):

```python
#: NSE's index constituent lists — membership IS the cap tier. Only current
#: membership is published, so load_index_membership() snapshots each fetch
#: with its date; anything before the first snapshot carries survivorship bias.
INDEX_LISTS: dict[str, str] = {
    "large": "https://nsearchives.nseindia.com/content/indices/ind_nifty100list.csv",
    "midcap": "https://nsearchives.nseindia.com/content/indices/ind_niftymidcap150list.csv",
    "smallcap": "https://nsearchives.nseindia.com/content/indices/ind_niftysmallcap250list.csv",
}
```

Add the parser at the end of the module:

```python
# -------------------------------------------------------- index membership --


def parse_index_list(content: bytes, tier: str) -> list[dict]:
    """Constituents of one NSE index list, tagged with the tier it came from.

    Raises when the body is not a constituent CSV. NSE blocks bots without
    notice and serves an HTML page instead; returning an empty list there
    would look like a successful empty day and wipe every stored tier.
    """
    reader = csv.reader(io.StringIO(content.decode("utf-8-sig")))
    header = [c.strip().upper() for c in next(reader, [])]
    if "SYMBOL" not in header:
        raise ValueError(f"{tier}: response is not a constituent CSV (no SYMBOL column)")

    rows: list[dict] = []
    for line in reader:
        rec = dict(zip(header, (c.strip() for c in line), strict=False))
        symbol = (rec.get("SYMBOL") or "").upper()
        if not symbol:
            continue
        rows.append({"symbol": symbol, "tier": tier, "industry": rec.get("INDUSTRY") or ""})
    return rows
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_index_membership.py -v`
Expected: PASS, 5 tests

- [ ] **Step 5: Commit**

```bash
git add backend/src/swing_trade_ml/services/market_feeds.py backend/tests/test_index_membership.py
git commit -m "Parse NSE index constituent lists into cap tiers"
```

---

### Task 2: Schema for cap tier, sector and dated membership snapshots

**Files:**
- Modify: `backend/src/swing_trade_ml/db/models/market.py`
- Modify: `backend/src/swing_trade_ml/db/models/feeds.py`
- Create: `backend/alembic/versions/20260925_1000_index_membership.py`
- Test: `backend/tests/test_index_membership.py` (extend)

**Interfaces:**
- Consumes: `Base`, `TimestampMixin` from the existing model modules.
- Produces: `Instrument.cap_tier: str | None`, `Instrument.sector: str | None`, and `IndexMembershipSnapshot` with columns `id, fetched_on, symbol, tier, industry`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_index_membership.py`:

```python
from datetime import date

from swing_trade_ml.db.models.feeds import IndexMembershipSnapshot
from swing_trade_ml.db.models.market import Instrument


def test_instrument_carries_tier_and_sector(db_session):
    inst = Instrument(
        instrument_token=99001, tradingsymbol="TIERTEST", exchange="NSE",
        cap_tier="midcap", sector="Power",
    )
    db_session.add(inst)
    db_session.flush()
    assert inst.cap_tier == "midcap"
    assert inst.sector == "Power"


def test_snapshot_is_unique_per_day_and_symbol(db_session):
    from sqlalchemy.exc import IntegrityError

    day = date(2026, 9, 25)
    db_session.add(
        IndexMembershipSnapshot(fetched_on=day, symbol="ABB", tier="large", industry="Capital Goods")
    )
    db_session.flush()
    db_session.add(
        IndexMembershipSnapshot(fetched_on=day, symbol="ABB", tier="midcap", industry="Capital Goods")
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_index_membership.py -k "tier_and_sector or unique_per_day" -v`
Expected: FAIL with `ImportError: cannot import name 'IndexMembershipSnapshot'`

- [ ] **Step 3: Add the columns and the model**

In `backend/src/swing_trade_ml/db/models/market.py`, inside `Instrument` immediately after the `is_active` column:

```python
    # Real market-cap tier, from NSE index membership (services/market_feeds.py
    # INDEX_LISTS) — large / midcap / smallcap / unknown. Replaces the old
    # proxy in strategies/tier.py, which read a suffix off a strategy's model
    # name and so labelled every stock a strategy touched with that strategy's
    # tier. None until the first membership load runs.
    cap_tier: Mapped[str | None] = mapped_column(String(16), index=True)
    # The stock's own sector, from the same lists' Industry column. Distinct
    # from ml/sector_map.py, which maps a stock to a sector *index* for
    # relative-strength features.
    sector: Mapped[str | None] = mapped_column(String(64))
```

In `backend/src/swing_trade_ml/db/models/feeds.py`, append:

```python
class IndexMembershipSnapshot(Base, TimestampMixin):
    """Which NSE index each symbol belonged to on the day we fetched it.

    NSE publishes current membership only — there is no historical archive.
    Dating every fetch is what makes membership point-in-time safe from the
    day we start recording; anything earlier carries survivorship bias.
    """

    __tablename__ = "index_membership_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    fetched_on: Mapped[date] = mapped_column(Date, index=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    tier: Mapped[str] = mapped_column(String(16))
    industry: Mapped[str] = mapped_column(String(64), default="")

    __table_args__ = (
        UniqueConstraint("fetched_on", "symbol", name="uq_index_membership_day_symbol"),
    )
```

Check the imports at the top of `feeds.py` include `BigInteger`, `Date`, `String`, `UniqueConstraint` and `date`; add any that are missing.

- [ ] **Step 4: Write the migration**

Create `backend/alembic/versions/20260925_1000_index_membership.py`. The current head is `b7d1e94c2a58` in `20260921_1600_avoid_lists.py` — this repo uses hex revision ids, not date strings, so match that convention:

```python
"""Cap tier, sector, and dated index-membership snapshots.

Revision ID: c5e2a83f1b70
Revises: b7d1e94c2a58
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "c5e2a83f1b70"
down_revision: str | None = "b7d1e94c2a58"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("instruments", sa.Column("cap_tier", sa.String(16), nullable=True))
    op.add_column("instruments", sa.Column("sector", sa.String(64), nullable=True))
    op.create_index("ix_instruments_cap_tier", "instruments", ["cap_tier"])

    op.create_table(
        "index_membership_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("fetched_on", sa.Date(), nullable=False),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("tier", sa.String(16), nullable=False),
        sa.Column("industry", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("fetched_on", "symbol", name="uq_index_membership_day_symbol"),
    )
    op.create_index("ix_index_membership_fetched_on", "index_membership_snapshots", ["fetched_on"])
    op.create_index("ix_index_membership_symbol", "index_membership_snapshots", ["symbol"])


def downgrade() -> None:
    op.drop_table("index_membership_snapshots")
    op.drop_index("ix_instruments_cap_tier", table_name="instruments")
    op.drop_column("instruments", "sector")
    op.drop_column("instruments", "cap_tier")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_index_membership.py -v`
Expected: PASS, 7 tests

- [ ] **Step 6: Commit**

```bash
git add backend/src/swing_trade_ml/db/models/ backend/alembic/versions/ backend/tests/test_index_membership.py
git commit -m "Add cap tier, sector and dated index-membership snapshots"
```

---

### Task 3: Load membership and stamp tiers onto instruments

**Files:**
- Modify: `backend/src/swing_trade_ml/services/market_feeds.py`
- Modify: `backend/src/swing_trade_ml/workers/jobs.py`
- Test: `backend/tests/test_index_membership.py` (extend)

**Interfaces:**
- Consumes: `parse_index_list`, `INDEX_LISTS`, `fetch`, `_insert_ignoring_duplicates` from Task 1; `IndexMembershipSnapshot`, `Instrument.cap_tier` from Task 2.
- Produces: `load_index_membership(db: Session, today: date | None = None) -> dict[str, int]` returning `{"snapshots": n, "instruments_updated": n}`.

**Tier precedence:** when a symbol appears in more than one list — which NSE allows during rebalance — the **narrower** list wins, smallcap over midcap over large. A stock newly promoted still trades with smallcap liquidity, so the more conservative tier is the safer one for risk limits.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_index_membership.py`:

```python
TIER_PRECEDENCE_ROWS = [
    {"symbol": "BOTH", "tier": "large", "industry": "Power"},
    {"symbol": "BOTH", "tier": "smallcap", "industry": "Power"},
]


def test_narrower_tier_wins_when_a_symbol_is_in_two_lists():
    """NSE overlaps lists during rebalance. A stock promoted out of smallcap
    still trades with smallcap liquidity, so the conservative tier wins — and
    the result must not depend on which list was fetched first."""
    from swing_trade_ml.services.market_feeds import resolve_tier

    assert resolve_tier(["large", "smallcap"]) == "smallcap"
    assert resolve_tier(["smallcap", "large"]) == "smallcap"
    assert resolve_tier(["large", "midcap"]) == "midcap"
    assert resolve_tier([]) == "unknown"


def test_load_stamps_tier_and_sector_onto_matching_instruments(db_session, monkeypatch):
    from swing_trade_ml.services import market_feeds

    db_session.add(
        Instrument(instrument_token=99002, tradingsymbol="ABB", exchange="NSE", is_watchlisted=True)
    )
    db_session.flush()

    monkeypatch.setattr(market_feeds, "fetch", lambda url: SAMPLE)
    result = market_feeds.load_index_membership(db_session, today=date(2026, 9, 25))

    assert result["instruments_updated"] == 1
    inst = db_session.query(Instrument).filter_by(tradingsymbol="ABB").one()
    assert inst.cap_tier in {"large", "midcap", "smallcap"}
    assert inst.sector == "Capital Goods"


def test_instrument_in_no_list_becomes_unknown_not_large(db_session, monkeypatch):
    """The defaulting that made the old model-name proxy wrong. A stock we
    cannot classify must be excluded, never assumed to be large-cap."""
    from swing_trade_ml.services import market_feeds

    db_session.add(
        Instrument(instrument_token=99003, tradingsymbol="NOTLISTED", exchange="NSE", is_watchlisted=True)
    )
    db_session.flush()

    monkeypatch.setattr(market_feeds, "fetch", lambda url: SAMPLE)
    market_feeds.load_index_membership(db_session, today=date(2026, 9, 25))

    inst = db_session.query(Instrument).filter_by(tradingsymbol="NOTLISTED").one()
    assert inst.cap_tier == "unknown"
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_index_membership.py -k "tier_wins or stamps_tier or no_list" -v`
Expected: FAIL with `ImportError: cannot import name 'resolve_tier'`

- [ ] **Step 3: Implement the loader**

Append to `backend/src/swing_trade_ml/services/market_feeds.py`:

```python
#: Narrowest first — a symbol in two lists takes the more conservative tier,
#: because a stock just promoted still trades with the smaller tier's liquidity.
TIER_PRECEDENCE: tuple[str, ...] = ("smallcap", "midcap", "large")


def resolve_tier(tiers: list[str]) -> str:
    """The tier a symbol takes when it appears in more than one list.

    Order-independent by construction: precedence is a fixed tuple, never the
    order the lists happened to be fetched in.
    """
    for tier in TIER_PRECEDENCE:
        if tier in tiers:
            return tier
    return "unknown"


def load_index_membership(db: Session, today: date | None = None) -> dict[str, int]:
    """Fetch all three NSE index lists, snapshot them, and stamp every
    watchlisted instrument with its cap tier and sector.

    Every watchlisted instrument is written, including ones in no list — they
    become "unknown" so a stock we cannot classify is excluded rather than
    silently treated as large-cap.
    """
    day = today or datetime.now(IST).date()

    by_symbol: dict[str, list[str]] = {}
    industry_of: dict[str, str] = {}
    snapshot_rows: list[dict] = []

    for tier, url in INDEX_LISTS.items():
        content = fetch(url)
        if content is None:
            raise ValueError(f"NSE has no {tier} constituent list at {url}")
        for row in parse_index_list(content, tier):
            by_symbol.setdefault(row["symbol"], []).append(tier)
            if row["industry"]:
                industry_of[row["symbol"]] = row["industry"]

    for symbol, tiers in by_symbol.items():
        snapshot_rows.append(
            {
                "fetched_on": day,
                "symbol": symbol,
                "tier": resolve_tier(tiers),
                "industry": industry_of.get(symbol, ""),
            }
        )

    snapshots = _insert_ignoring_duplicates(
        db, IndexMembershipSnapshot, snapshot_rows, ["fetched_on", "symbol"]
    )

    updated = 0
    instruments = db.execute(
        select(Instrument).where(Instrument.is_watchlisted.is_(True))
    ).scalars().all()
    for inst in instruments:
        tier = resolve_tier(by_symbol.get(inst.tradingsymbol.upper(), []))
        sector = industry_of.get(inst.tradingsymbol.upper())
        if inst.cap_tier != tier or (sector and inst.sector != sector):
            inst.cap_tier = tier
            if sector:
                inst.sector = sector
            updated += 1
    db.commit()

    log.info("feeds.index_membership", snapshots=snapshots, instruments_updated=updated)
    return {"snapshots": snapshots, "instruments_updated": updated}
```

The module already imports `select` and defines `IST`, which is why `load_index_membership` uses `datetime.now(IST)` like its neighbours. Add only what is missing: `from swing_trade_ml.db.models.feeds import IndexMembershipSnapshot` and `from swing_trade_ml.db.models.market import Instrument`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_index_membership.py -v`
Expected: PASS, 10 tests

- [ ] **Step 5: Wire it into the daily feed driver**

`run_daily_feeds` in the same module already isolates each feed and collects failures into `FeedRun.errors`, which the worker turns into a Telegram alert. Adding membership to that loop gets the alerting for free — no change to `workers/jobs.py` is needed.

In `run_daily_feeds`, add one entry to the existing loader tuple:

```python
    for name, loader in (
        ("deals", lambda: load_deals(db)),
        ("institutional_flows", lambda: load_fii_dii(db)),
        ("upcoming_events", lambda: load_upcoming_events(db, today)),
        ("restrictions", lambda: load_restrictions(db, today)),
        ("index_membership", lambda: load_index_membership(db, today)["snapshots"]),
    ):
```

- [ ] **Step 6: Run the feed driver tests**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/ -k "feeds or market_feeds or job" -v`
Expected: PASS, no regressions

- [ ] **Step 7: Commit**

```bash
git add backend/src/swing_trade_ml/services/market_feeds.py backend/tests/test_index_membership.py
git commit -m "Load NSE index membership and stamp real cap tiers on instruments"
```

---

### Task 4: Stop advisory strategies stealing position slots

**Files:**
- Modify: `backend/src/swing_trade_ml/services/risk.py:87-96`
- Test: `backend/tests/test_portfolio_risk_layer.py` (extend)

**Interfaces:**
- Consumes: `core.strategy_policy.is_advisory`.
- Produces: `active_strategy_count(db, mode)` unchanged in signature, now counting only strategies that can actually take a position.

This is the latent bug from `[[position-slot-starvation-bug]]`. Shadow experiments in plan 2 are advisory, and without this each one would shrink every real strategy's slot share.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_portfolio_risk_layer.py`:

```python
def test_advisory_strategies_do_not_shrink_the_automatic_share(db_session):
    """Shadow experiments are advisory and hold nothing. Counting them would
    cut every real strategy's slot share — 8 // 14 floors to 1 — which is the
    starvation that blocked buying from 16 Sept all over again."""
    from swing_trade_ml.db.models.trading import Strategy
    from swing_trade_ml.services.risk import active_strategy_count

    for i in range(3):
        db_session.add(
            Strategy(
                name=f"auto_{i}", strategy_type="ml_swing", mode="paper",
                execution_mode="auto", is_active=True,
            )
        )
    db_session.flush()
    baseline = active_strategy_count(db_session, "paper")

    for i in range(10):
        db_session.add(
            Strategy(
                name=f"shadow_{i}", strategy_type="ml_swing", mode="paper",
                execution_mode="advisory", is_active=True,
            )
        )
    db_session.flush()

    assert active_strategy_count(db_session, "paper") == baseline
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_portfolio_risk_layer.py -k advisory_strategies_do_not -v`
Expected: FAIL, asserting 13 == 3

- [ ] **Step 3: Exclude advisory strategies**

Replace `active_strategy_count` in `backend/src/swing_trade_ml/services/risk.py`:

```python
def active_strategy_count(db: Session, mode: str) -> int:
    """How many strategies are competing for this mode's position slots.

    Advisory strategies are excluded: they record signals and never hold a
    position, so counting them would shrink every automatic strategy's share
    for no gain. Shadow experiments are advisory, so without this each one
    added would starve the strategies that actually trade.
    """
    strategies = db.execute(
        select(Strategy).where(Strategy.is_active.is_(True), Strategy.mode == mode)
    ).scalars().all()
    return sum(1 for s in strategies if not is_advisory(s))
```

`risk.py` does not import this yet — add `from swing_trade_ml.core.strategy_policy import is_advisory` to its imports, beside the existing `from swing_trade_ml.strategies.tier import cap_tier` at line 38.

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_portfolio_risk_layer.py -v`
Expected: PASS, including the existing `test_one_strategy_cannot_consume_every_account_slot`

- [ ] **Step 5: Run the full suite for regressions**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: PASS. `engine._rank_out_reasons` also calls this function, and `test_correctness_release.py` stubs it — if that stub breaks, update it there as `3d3d99e` did previously.

- [ ] **Step 6: Commit**

```bash
git add backend/src/swing_trade_ml/services/risk.py backend/tests/test_portfolio_risk_layer.py
git commit -m "Exclude advisory strategies from the position-slot share"
```

---

### Task 5: Cross-sectional factor scoring

**Files:**
- Create: `backend/src/swing_trade_ml/services/factors.py`
- Test: `backend/tests/test_factors.py` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks — pure pandas, no database.
- Produces: `FACTOR_INPUTS: dict[str, tuple[tuple[str, int], ...]]`, `AVAILABLE_FACTORS: frozenset[str]`, `STUBBED_FACTORS: dict[str, str]`, `percentile_rank(series) -> pd.Series`, `factor_scores(frame) -> pd.DataFrame`, `composite_score(scores, weights) -> pd.Series`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_factors.py`:

```python
"""Factor scoring — cross-sectional percentile ranks over one day's universe."""

from __future__ import annotations

import pandas as pd
import pytest

from swing_trade_ml.services.factors import (
    AVAILABLE_FACTORS,
    STUBBED_FACTORS,
    composite_score,
    factor_scores,
    percentile_rank,
)


def test_percentile_rank_spreads_over_0_to_100():
    ranked = percentile_rank(pd.Series([1.0, 2.0, 3.0, 4.0]))
    assert ranked.min() == pytest.approx(25.0)
    assert ranked.max() == pytest.approx(100.0)


def test_single_stock_universe_scores_without_error():
    """A one-row universe must produce a valid score, not a division error."""
    ranked = percentile_rank(pd.Series([42.0]))
    assert ranked.tolist() == [100.0]


def test_all_identical_values_rank_equal_and_are_not_nan():
    ranked = percentile_rank(pd.Series([5.0, 5.0, 5.0]))
    assert ranked.notna().all()
    assert ranked.nunique() == 1


def test_low_volatility_inverts_so_calm_stocks_rank_higher():
    frame = pd.DataFrame(
        {
            "volatility_20": [0.10, 0.50],
            "atr_14_pct": [0.01, 0.05],
            "volatility_percentile_rank": [0.10, 0.90],
        },
        index=["CALM", "WILD"],
    )
    scores = factor_scores(frame)
    assert scores.loc["CALM", "low_volatility"] > scores.loc["WILD", "low_volatility"]


def test_trend_rewards_the_stronger_uptrend():
    frame = pd.DataFrame(
        {
            "sma_50_ratio": [1.10, 0.90], "sma_200_ratio": [1.20, 0.85],
            "sma_50_200_cross": [1, 0], "adx_14": [35.0, 12.0],
            "trend_strength": [0.8, 0.1], "relative_strength_20d": [0.05, -0.04],
            "return_20d": [0.08, -0.06], "return_120d": [0.30, -0.10],
            "return_250d": [0.50, -0.20],
        },
        index=["STRONG", "WEAK"],
    )
    scores = factor_scores(frame)
    assert scores.loc["STRONG", "trend"] > scores.loc["WEAK", "trend"]


def test_composite_renormalises_weights_of_enabled_factors_only():
    """Disabling a factor redistributes its weight rather than shrinking
    every score toward zero."""
    scores = pd.DataFrame({"trend": [80.0, 40.0]}, index=["A", "B"])
    composite = composite_score(scores, {"trend": 70, "low_volatility": 30})
    assert composite.tolist() == pytest.approx([80.0, 40.0])


def test_composite_blends_two_factors_by_weight():
    scores = pd.DataFrame(
        {"trend": [100.0, 0.0], "low_volatility": [0.0, 100.0]}, index=["A", "B"]
    )
    composite = composite_score(scores, {"trend": 75, "low_volatility": 25})
    assert composite["A"] == pytest.approx(75.0)
    assert composite["B"] == pytest.approx(25.0)


def test_zero_total_weight_raises_rather_than_dividing_by_zero():
    scores = pd.DataFrame({"trend": [50.0]}, index=["A"])
    with pytest.raises(ValueError, match="at least one factor"):
        composite_score(scores, {"trend": 0})


def test_value_and_quality_are_stubbed_not_available():
    assert AVAILABLE_FACTORS == frozenset({"trend", "low_volatility"})
    assert set(STUBBED_FACTORS) == {"value", "quality", "size"}
    for reason in STUBBED_FACTORS.values():
        assert reason


def test_missing_input_column_is_skipped_not_fatal():
    """A frame without return_250d still scores trend on its other inputs."""
    frame = pd.DataFrame(
        {"sma_50_ratio": [1.1, 0.9], "adx_14": [30.0, 10.0]}, index=["A", "B"]
    )
    scores = factor_scores(frame)
    assert scores.loc["A", "trend"] > scores.loc["B", "trend"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_factors.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'swing_trade_ml.services.factors'`

- [ ] **Step 3: Implement the scorer**

Create `backend/src/swing_trade_ml/services/factors.py`:

```python
"""Factor scoring: ranking stocks against each other, one day at a time.

A factor is a *cross-sectional* percentile rank — every stock scored against
the others in that day's universe, never against an absolute threshold. That
is what keeps a score meaningful when the whole market moves together: in a
falling market the best-trending stock still ranks 100, because the question
is which stock to prefer, not whether the market is good.

Scores are inputs to candidate *selection* (see the spec's algorithm), not to
the model. They are deliberately not appended to ml/features.py's
FEATURE_COLUMNS: adding feature families inside the model has been tried four
times — sector, breadth, VIX, delivery percentage — and moved nothing each
time. The leverage here is narrowing the pool the model starts from.
"""

from __future__ import annotations

import pandas as pd

#: factor -> ((feature column, direction), ...) where direction is +1 when a
#: higher raw value is better and -1 when lower is better.
FACTOR_INPUTS: dict[str, tuple[tuple[str, int], ...]] = {
    "trend": (
        ("sma_50_ratio", 1),
        ("sma_200_ratio", 1),
        ("sma_50_200_cross", 1),
        ("adx_14", 1),
        ("trend_strength", 1),
        ("relative_strength_20d", 1),
        ("return_20d", 1),
        ("return_120d", 1),
        ("return_250d", 1),
    ),
    "low_volatility": (
        ("volatility_20", -1),
        ("atr_14_pct", -1),
        ("volatility_percentile_rank", -1),
    ),
}

AVAILABLE_FACTORS: frozenset[str] = frozenset(FACTOR_INPUTS)

#: Shown in the UI, disabled, with the reason — never faked with placeholder
#: numbers. Value and Quality need company financials (an NSE XBRL project);
#: a continuous Size rank needs real market capitalisation, which we do not
#: have. Cap *tier* is a universe filter instead (services/market_feeds.py).
STUBBED_FACTORS: dict[str, str] = {
    "value": "Needs company financials (earnings, book value)",
    "quality": "Needs company financials (profitability, debt)",
    "size": "Needs market capitalisation; use the cap-tier filter instead",
}


def percentile_rank(series: pd.Series) -> pd.Series:
    """0-100 rank of each value against the others present.

    Ties share the average rank. A single-row universe ranks 100 rather than
    raising, and an all-identical universe returns one shared rank rather than
    NaN — both are real cases on a thin day.
    """
    return series.rank(pct=True, method="average") * 100.0


def factor_scores(frame: pd.DataFrame) -> pd.DataFrame:
    """One 0-100 score per available factor, per row of `frame`.

    `frame` is one row per stock for a single day, indexed by symbol, holding
    whatever feature columns are available. Inputs missing from the frame are
    skipped, so a factor still scores on the inputs it does have.
    """
    scores: dict[str, pd.Series] = {}
    for factor, inputs in FACTOR_INPUTS.items():
        parts = [
            percentile_rank(frame[column] * direction)
            for column, direction in inputs
            if column in frame.columns
        ]
        if not parts:
            continue
        scores[factor] = pd.concat(parts, axis=1).mean(axis=1)
    return pd.DataFrame(scores, index=frame.index)


def composite_score(scores: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """Weighted blend of the factors actually present in `scores`.

    Weights are renormalised over the factors that survive, so disabling one
    redistributes its weight instead of dragging every composite toward zero.
    A configuration weighting only unavailable factors is a configuration
    error and raises rather than silently scoring everything the same.
    """
    usable = {f: float(w) for f, w in weights.items() if f in scores.columns and w > 0}
    total = sum(usable.values())
    if total <= 0:
        raise ValueError("Weights must enable at least one available factor")

    blended = sum(scores[factor] * weight for factor, weight in usable.items())
    return blended / total
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_factors.py -v`
Expected: PASS, 10 tests

- [ ] **Step 5: Commit**

```bash
git add backend/src/swing_trade_ml/services/factors.py backend/tests/test_factors.py
git commit -m "Add cross-sectional factor scoring for trend and low volatility"
```

---

### Task 6: Long-horizon return inputs for a real momentum factor

**Files:**
- Modify: `backend/src/swing_trade_ml/ml/features.py`
- Test: `backend/tests/test_factors.py` (extend)

**Interfaces:**
- Consumes: nothing.
- Produces: `build_features()` output gains `return_120d` and `return_250d` columns. `FEATURE_COLUMNS` is **not** extended — these are factor inputs only, so the trained model's input contract is unchanged.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_factors.py`:

```python
def test_long_horizon_returns_are_built_but_not_model_features():
    """return_120d/250d feed the trend factor. They must NOT enter
    FEATURE_COLUMNS: the trained model's input contract is fixed, and a
    silent change there would invalidate every stored model."""
    import numpy as np

    from swing_trade_ml.ml.features import FEATURE_COLUMNS, build_features

    assert "return_120d" not in FEATURE_COLUMNS
    assert "return_250d" not in FEATURE_COLUMNS

    n = 300
    rng = np.random.default_rng(0)
    close = pd.Series(100 + np.arange(n) * 0.1 + rng.normal(0, 0.2, n))
    frame = pd.DataFrame(
        {
            "open": close, "high": close * 1.01, "low": close * 0.99,
            "close": close, "volume": pd.Series([100000] * n),
        },
        index=pd.date_range("2025-01-01", periods=n, freq="D"),
    )

    built = build_features(frame)
    assert "return_120d" in built.columns
    assert "return_250d" in built.columns
    assert built["return_120d"].notna().any()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_factors.py -k long_horizon -v`
Expected: FAIL, `assert 'return_120d' in built.columns`

- [ ] **Step 3: Compute the columns**

In `backend/src/swing_trade_ml/ml/features.py`, find where the existing `return_5d` / `return_10d` / `return_20d` columns are computed inside `build_features` and add alongside them:

```python
    # Long-horizon returns — inputs to the trend factor in services/factors.py,
    # which needs a momentum window closer to the academic 12-month definition
    # than return_20d gives. Deliberately NOT added to FEATURE_COLUMNS: the
    # trained models' input contract is fixed, and widening it silently would
    # invalidate every stored model.
    out["return_120d"] = close.pct_change(120)
    out["return_250d"] = close.pct_change(250)
```

These go immediately after `out["return_10d"] = close.pct_change(10)` at `ml/features.py:305`, matching the surrounding style exactly — that block builds into `out` and reads from the local `close` series.

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_factors.py -v`
Expected: PASS, 11 tests

- [ ] **Step 5: Confirm the model contract is untouched**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_features.py tests/test_correctness_release.py -v`
Expected: PASS. Any failure here means `FEATURE_COLUMNS` changed and must be reverted.

- [ ] **Step 6: Commit**

```bash
git add backend/src/swing_trade_ml/ml/features.py backend/tests/test_factors.py
git commit -m "Compute 120d and 250d returns as trend-factor inputs"
```

---

### Task 7: Expose factors and cap tiers over the API

**Files:**
- Create: `backend/src/swing_trade_ml/api/v1/endpoints/selection.py`
- Modify: `backend/src/swing_trade_ml/api/v1/__init__.py` (or wherever routers are registered)
- Test: `backend/tests/test_selection_api.py` (create)

**Interfaces:**
- Consumes: `AVAILABLE_FACTORS`, `STUBBED_FACTORS`, `FACTOR_INPUTS` from Task 5; `Instrument.cap_tier` from Task 2.
- Produces: `GET /api/v1/selection/factors` and `GET /api/v1/selection/universe`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_selection_api.py`:

```python
"""The selection API — what the Lab tab reads."""

from __future__ import annotations

from swing_trade_ml.db.models.market import Instrument


def test_factors_endpoint_lists_available_and_stubbed(client):
    response = client.get("/api/v1/selection/factors")
    assert response.status_code == 200
    body = response.json()

    by_name = {f["name"]: f for f in body["factors"]}
    assert by_name["trend"]["available"] is True
    assert by_name["trend"]["inputs"]
    assert by_name["value"]["available"] is False
    assert "financials" in by_name["value"]["unavailable_reason"].lower()


def test_universe_endpoint_counts_by_cap_tier(client, db_session):
    for i, tier in enumerate(["large", "large", "midcap", "unknown"]):
        db_session.add(
            Instrument(
                instrument_token=97000 + i, tradingsymbol=f"UNIV{i}",
                exchange="NSE", is_watchlisted=True, cap_tier=tier,
            )
        )
    db_session.commit()

    body = client.get("/api/v1/selection/universe").json()
    assert body["by_tier"]["large"] >= 2
    assert body["by_tier"]["midcap"] >= 1
    assert body["by_tier"]["unknown"] >= 1
```

The `client` fixture is defined in `backend/tests/conftest.py:69` and depends on `db_session`, so both fixtures above resolve as written.

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_selection_api.py -v`
Expected: FAIL with 404

- [ ] **Step 3: Implement the endpoints**

Create `backend/src/swing_trade_ml/api/v1/endpoints/selection.py`:

```python
"""Factor definitions and the tradable universe, for the Lab tab.

Read-only. Selection itself runs in the scan; this endpoint only describes
what is available and why the rest is not, so the UI can show a disabled
factor with its real reason rather than an empty slider.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import func, select

from swing_trade_ml.api.deps import DbSession
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.services.factors import (
    AVAILABLE_FACTORS,
    FACTOR_INPUTS,
    STUBBED_FACTORS,
)

router = APIRouter()

PLAIN_NAMES = {
    "trend": "Trend",
    "low_volatility": "Steadiness",
    "value": "Value",
    "quality": "Quality",
    "size": "Size",
}

PLAIN_DESCRIPTIONS = {
    "trend": "Stocks moving up and holding above their long averages",
    "low_volatility": "Stocks that move calmly rather than in sharp jumps",
    "value": "Stocks cheap against their earnings",
    "quality": "Profitable companies carrying little debt",
    "size": "How large the company is",
}


@router.get("/factors")
def list_factors() -> dict[str, Any]:
    factors: list[dict[str, Any]] = []
    for name in sorted(AVAILABLE_FACTORS):
        factors.append(
            {
                "name": name,
                "label": PLAIN_NAMES.get(name, name),
                "description": PLAIN_DESCRIPTIONS.get(name, ""),
                "available": True,
                "unavailable_reason": None,
                "inputs": [column for column, _ in FACTOR_INPUTS[name]],
            }
        )
    for name, reason in STUBBED_FACTORS.items():
        factors.append(
            {
                "name": name,
                "label": PLAIN_NAMES.get(name, name),
                "description": PLAIN_DESCRIPTIONS.get(name, ""),
                "available": False,
                "unavailable_reason": reason,
                "inputs": [],
            }
        )
    return {"factors": factors}


@router.get("/universe")
def universe(db: DbSession) -> dict[str, Any]:
    """How many watchlisted instruments sit in each cap tier.

    An "unknown" count above zero means those stocks are in none of NSE's
    three index lists and are excluded from tier-filtered selection.
    """
    rows = db.execute(
        select(Instrument.cap_tier, func.count(Instrument.id))
        .where(Instrument.is_watchlisted.is_(True))
        .group_by(Instrument.cap_tier)
    ).all()
    by_tier = {(tier or "unclassified"): count for tier, count in rows}
    return {"by_tier": by_tier, "total": sum(by_tier.values())}
```

The router carries its own prefix, so declare it at the top of the new file:

```python
router = APIRouter(prefix="/selection", tags=["selection"])
```

Register it in `backend/src/swing_trade_ml/api/v1/router.py` beside the other protected routers (they sit around lines 41-46), using the same `protected` dependency list so this endpoint needs an API key like its neighbours:

```python
from swing_trade_ml.api.v1.endpoints import selection

api_router.include_router(selection.router, dependencies=protected)
```

`DbSession` is already defined in `backend/src/swing_trade_ml/api/deps.py:18` as `Annotated[Session, Depends(get_db)]`, so the import in the endpoint file is correct as written.

- [ ] **Step 4: Run to verify they pass**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_selection_api.py -v`
Expected: PASS, 2 tests

- [ ] **Step 5: Run the whole suite**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: PASS, no regressions

- [ ] **Step 6: Commit**

```bash
git add backend/src/swing_trade_ml/api/ backend/tests/test_selection_api.py
git commit -m "Expose factor definitions and the cap-tier universe over the API"
```

---

## Deployment

- [ ] **Step 1: Confirm the full suite is green**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/ -q`

- [ ] **Step 2: Push the branch**

The branch is `develop`, and `c394823` ("Say why the scan bought nothing") is still unpushed from a previous session — it ships with this work.

```bash
git push origin develop
```

- [ ] **Step 3: Verify the migration ran and membership loaded**

After deploy, membership fills on the next `daily_market_feeds` run (19:20 IST weekdays). To confirm without waiting, check the universe split:

```bash
KEY=$(grep -E "^API_KEY=" .env | cut -d= -f2- | tr -d '\r"')
curl -s -H "X-API-Key: $KEY" https://swingtrademl.com/api/v1/selection/universe
```

Expected: counts across `large` / `midcap` / `smallcap`, and an `unknown` count. Every instrument still showing `unclassified` means the load has not run yet.

- [ ] **Step 4: Confirm the slot share is unchanged**

```bash
curl -s -H "X-API-Key: $KEY" https://swingtrademl.com/api/v1/risk/limits
```

Expected: `max_positions` 8, `open_positions` at whatever the book holds. Task 4 changes only the divisor, and with no advisory paper strategies yet the live share should not move — a change here means something else was affected.

---

## What this plan does not cover

Spec build items 4-7 become their own plans, each dependent on this one:

- **Plan 2 — selection and experiments:** wiring the shortlist into the scan behind a `params.selection` block, experiment CRUD, the shadow runner, and the comparison view with its sample-size guardrails.
- **Plan 3 — the money calculator:** the allocation projection and the added-capital what-if.
