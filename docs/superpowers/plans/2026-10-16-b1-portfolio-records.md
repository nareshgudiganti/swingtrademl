# Release B1: Portfolio Records and Backfill Implementation Plan (revision 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every money row an owner portfolio (house, tester, real) without changing a single number the app shows, a single trading decision, or anything a user can see.

**Architecture:** A `portfolios` table holds one row each for the house account, Vijay's testing book and My Holdings. A nullable `portfolio_id` is added to six money tables, and existing rows are backfilled by today's strategy-name rule. New rows are stamped by **Postgres `BEFORE INSERT` triggers**, not an ORM listener, so every write path is covered: ORM, Core/bulk, raw SQL, and old code after a rollback. The migration is **self-contained SQL**: it imports no application code, so it stays reproducible however the app changes. Reads don't change; scoping reads is release B2.

**Tech Stack:** Postgres 16 / TimescaleDB image, PL/pgSQL triggers, Alembic, SQLAlchemy 2, pytest (`client` and `db_session` fixtures).

**Spec:** `docs/superpowers/specs/2026-10-16-multi-user-portfolios-design.md` (rev 2): §1.2, §2.1 `portfolios`, §2.2, §2.4, §8, §9, §10 release B.

**Status:** revision 2 after the owner review of 2026-10-16. **Not approved for execution yet.**

---

## Changes since revision 1 (owner review items 1–10)

| # | Owner requirement | What changed |
|---|---|---|
| 1 | Audit the ownership mapping against prod data | Read-only prod census done (below). The full SQL census of all six tables on a sanitized prod copy is now **Task 1 and a hard gate**. Any live-mode row that would map to house **aborts the migration** (verification V3) |
| 2 | Stronger constraints; missing owners; user deletion | Exact kind→mode CHECK; status CHECK; archived ⇔ archived_at; generation ≥ 1; member requires an owner; owner FK **ON DELETE RESTRICT** (users are disabled, never deleted); one live member portfolio per user |
| 3 | The listener is no guarantee | **Replaced by DB triggers**, tested against ORM, Core `insert()`, `executemany`, `bulk_save_objects`, raw SQL and old code. Postgres transaction-failure behaviour documented (§D4) |
| 4 | Fuller verification | V1–V9: NULLs, parent/child agreement, row mode vs portfolio mode, owner linkage, one book each, snapshot ownership, strategy→portfolio agreement, exact numeric totals, triggers present |
| 5 | Stronger golden tests | Every house/tester/real API view (summary, detailed positions, trades, equity curve, risk limits) and risk state (drawdown, peak, slot counts, a sample `check_entry`) compared **byte for byte** before and after |
| 6 | Prod-copy rehearsal | Owner-side export script with counts manifest; sanitizing (secrets and personal finance excluded, hashes and emails scrubbed); strict `pg_restore` error policy; counts verified; `try/finally` cleanup; downgrade → schema-gone check → re-upgrade |
| 7 | Reproducible migrations | All SQL lives in the migration file. The app and tests load it from there. No app import inside the migration |
| 8 | Locking, rollback, model/SQL mismatches | `lock_timeout`; worker stopped and off-hours deploy; old-code-on-new-schema rehearsal (old inserts are stamped by the trigger); schema-vs-model comparison; column-type facts listed (§D6) |
| 9 | No exposure, decisions or real orders; trial untouched | Explicit guarantees (§D7) plus tests that pin them |
| 10 | Revised design, acceptance, risks, gates | §D below, the Acceptance section and the Rollout gates |

### Read-only production census (2026-10-16, via the API with the API key)

| Rows | Strategy | Mode | → book | Count / net P&L |
|---|---|---|---|---|
| positions | `real_trading` (id 6, type `ml_swing`, advisory) | live | real | 21 (2 open) |
| positions | `ml_swing_main` / `_midcap` / `_smallcap` | paper | house | 23 / 57 (2 open) / 4 |
| positions | `tester_paper` (id 8) | paper | tester | 14 (7 open) |
| trades | house strategies | paper | house | 82, ₹−22,639.85 |
| trades | `tester_paper` | paper | tester | 11, ₹+9,412.61 |
| trades | `real_trading` | live | real | 20, ₹−1,394.96 |

**Finding:** every live-mode position and trade is `real_trading`, and no live row would map to house. Strategies 2 (`sma_crossover_benchmark`) and 7 (`TradeMind brain`) have no positions. The API does not expose orders, risk events, snapshots or approvals by strategy and mode, so **Task 1's SQL census on the prod copy is mandatory before Task 2 starts.** The mapping uses the strategy **name** (`real_trading`'s type is `ml_swing`, so the type cannot be used).

---

## D. Design

**D1. Rule (exact):**
- `orders`, `trades`, `brain_approvals`: the portfolio of their `position_id`'s position when it has one.
- Otherwise, by strategy name: `real_trading` → real, `tester_paper` → tester, any other strategy or no strategy → house.
- `portfolio_snapshots` (no strategy): mode `paper` → house, `live` → real.
- `positions`, `risk_events`: by strategy name.

**D2. Constraints on `portfolios`:**
- `kind IN ('house','tester','real','member')`.
- Exact mode: `(kind='real' AND mode='live') OR (kind<>'real' AND mode='paper')`.
- `status IN ('active','paused','archived')`; `(status='archived') = (archived_at IS NOT NULL)`.
- `generation >= 1`; `length(trim(name)) > 0`; `auto_follow = false` (until release D).
- `kind <> 'member' OR owner_user_id IS NOT NULL`.
- Partial unique index: one row each of house/tester/real.
- Partial unique index: one non-archived member portfolio per owner.
- `owner_user_id` FK **ON DELETE RESTRICT**: a user who owns a portfolio cannot be deleted. Users are disabled (`swingtrade disable-user`), never deleted, so history keeps its owner.
- House has no owner. A missing `vijay` or `sudeeksha` leaves that book's owner NULL. Verification V4 reports it, and the prod-copy rehearsal requires both to be linked.

**D3. Triggers:** three PL/pgSQL functions, one per table shape, so no function references a column its table lacks:
- `pf_stamp_via_position()`: orders, trades, brain_approvals.
- `pf_stamp_via_strategy()`: positions, risk_events.
- `pf_stamp_snapshot()`: portfolio_snapshots.

Each one sets `NEW.portfolio_id` only when it is NULL, using D1, and **never raises**. They use only `SELECT … INTO` (no row gives NULL, not an error) and no `RAISE`. If the books haven't been seeded (a fresh DB), the row stays NULL.

**D4. Postgres failure behaviour:** any error inside a transaction aborts the whole transaction, and nothing in Python can rescue it afterwards. A trigger that errors would therefore fail the trade insert it fires on. That is why the triggers reference only objects the B1 migration creates and are written so they cannot raise. The downgrade drops the triggers **before** the column and table, and the rehearsal (Task 5) exercises inserts after the upgrade, after the downgrade and after the re-upgrade.

**D5. Self-contained migration:** the SQL lives as constants and functions **in the migration file**. `swing_trade_ml/db/portfolio_records.py` loads that file by path (the alembic dir is found the same way `db/session._find_alembic_dir` finds it), so the CLI and tests reuse exactly what the migration ran. The migration never imports `swing_trade_ml`.

**D6. Locking and model facts:**
- Six money tables, each well under 1,000 rows in prod. Adding a nullable column without a default only changes metadata. The FK, index and backfill UPDATE each touch a few hundred rows.
- `SET LOCAL lock_timeout = '5s'` and `statement_timeout = '120s'`: the migration fails fast rather than queue behind a job.
- The worker (scheduler) is **stopped** for the deploy, which happens **after 22:30 IST and before 06:00 IST**, when no job writes money tables. Only the `api` container migrates (the worker has `DB_AUTO_MIGRATE=false`).
- Money columns are `Float`, so totals are compared as `SUM(col::numeric)` (exact, independent of row order).
- `brain_approvals` has no `mode`, and its `strategy_id` is NOT NULL.
- `risk_events` and `portfolio_snapshots` have no `position_id`. `portfolio_snapshots` has no `strategy_id`.
- `orders.strategy_id` and `orders.position_id` are nullable.

**D7. What B1 guarantees not to change:**
- No API route, schema field or screen reads or shows `portfolio_id` or `portfolios`, so nothing new is exposed to anyone.
- No read query, risk check, sizing, scan, brain module or order path is modified. The files listed under Global Constraints are untouched (verified by `git diff --stat`).
- `TRADING_MODE`, `ALLOW_LIVE_TRADING`, `REAL_ACCOUNT_USERS` and the brain's stage are untouched. Brain tables are untouched. Only `brain_approvals` gains a column, and nothing reads it.
- The frozen trial's figures are proven identical (golden test, Task 3).

---

## Global Constraints

- Branch `feature/b1-portfolios` from `develop` (P0 at `7562526` + plans). **No push, merge, deploy or prod change** without the owner's separate approval.
- **Do not modify:** `services/execution.py`, `services/risk.py`, `services/engine.py`, `brokers/*`, `services/portfolio.py`, `services/tester_paper.py`, `services/real_orders.py`, `services/brain_golive/*`, `brain/*`, `strategies/*`, any `api/v1/endpoints/*` file, any `schemas` or `frontend` file. Task 6 checks this with `git diff --stat develop..HEAD`.
- `portfolio_id` stays **nullable** in B1. NOT NULL is B2's first migration, after one clean prod day.
- Exact book rows (created by the migration):
  - `house` "House account", `paper`, owner NULL
  - `tester` "Testing book", `paper`, owner = `vijay` if present
  - `real` "My Holdings", `live`, owner = `sudeeksha` if present
  - all with `status='active'`, `generation=1`, `auto_follow=false`, `starting_capital=NULL`
- Alembic revision `f2b1p0r7f0l1`, down `e1p0s2e3c4u5`. Confirm the single head first.
- The migration file imports only `alembic` and `sqlalchemy`.
- Python `D:/machine learning/swing-trade-bot/backend/.venv/Scripts/python.exe`. Tests run from `backend` with `env -u API_KEY -u DATABASE_URL -u JWT_SECRET_KEY -u TRADING_MODE <python> -m pytest … -q`. Docker Postgres `stml-postgres` on 5433 must be up.
- `ruff format` only files you created. Never read or print `.env`. Never use bare `git stash`. The prod copy never enters git.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A live-mode order, risk event or snapshot under a non-`real_trading` strategy** in the prod copy. V3 must abort the migration with the table named, never silently file it under house. Pinned in Task 2 (test) and Task 1 (census gate).
2. **A trade or order on a tester position whose own `strategy_id` is NULL or different.** It follows the position (V2). Pinned in Task 2.
3. **Old code inserting after a rollback.** The trigger still stamps it, and if the schema was downgraded, re-upgrading backfills it. Pinned in Tasks 4 and 5.
4. **Inserts that bypass the ORM** (Core `insert()`, `executemany`, `bulk_save_objects`, raw `INSERT`) are stamped identically. Pinned in Task 4.
5. **Float money totals compared inexactly.** Every comparison uses `SUM(…::numeric)`. Pinned in Task 2 (a census test with values like 0.1 + 0.2).

---

## File map

| File | Responsibility | Task |
|---|---|---|
| `backend/scripts/export_prod_copy.sh` (new) | owner runs on droplet: sanitized dump + counts manifest | 1 |
| `backend/scripts/prod_census.sql` (new) | read-only census of all six tables by strategy/mode | 1 |
| `backend/src/swing_trade_ml/db/models/portfolio.py` (new) | `Portfolio` model mirroring D2 | 2 |
| `backend/src/swing_trade_ml/db/models/trading.py`, `safety.py`, `brain_golive.py`, `__init__.py` | `portfolio_id` columns; register model | 2 |
| `backend/alembic/versions/20261017_1000_b1_portfolios.py` (new) | self-contained schema, seed, backfill, triggers, census, verify, downgrade | 2, 4 |
| `backend/src/swing_trade_ml/db/portfolio_records.py` (new) | loads the migration's SQL by path for CLI/tests | 2 |
| `backend/src/swing_trade_ml/cli.py` | `portfolios-check`, `portfolios-backfill` | 2 |
| `backend/tests/conftest.py` | install B1 triggers + seed books after `create_all` | 4 |
| `backend/tests/test_b1_portfolio_model.py`, `test_b1_backfill.py`, `test_b1_golden.py`, `test_b1_triggers.py`, `test_b1_guarantees.py` (new) | tests | 2–4, 6 |
| `backend/scripts/rehearse_b1_on_prod_copy.py` (new), `docs/deploy/B1-portfolios-runbook.md` (new), `.gitignore` | rehearsal, runbook | 5 |

---

### Task 0: Branch, head, database

- [ ] **Step 1:** create the worktree: `git worktree add -b feature/b1-portfolios .claude/worktrees/b1-portfolios develop`. Work only there.
- [ ] **Step 2:** `cd backend && <python> -m alembic heads`. Expected: `e1p0s2e3c4u5` only. If another head is printed, stop and report.
- [ ] **Step 3:** `docker exec stml-postgres pg_isready`. Expected: `accepting connections`.

---

### Task 1: Owner-side export and read-only census (gate)

**Files:** Create `backend/scripts/export_prod_copy.sh`, `backend/scripts/prod_census.sql`, and add `.local/` to `.gitignore`.

**Interfaces:** Produces `.local/b1_rehearsal.dump` (a pg_dump custom-format file) and `.local/b1_counts.json` (row counts per table), both written by the owner. `prod_census.sql` is read-only (`BEGIN READ ONLY; … ROLLBACK;`).

- [ ] **Step 1: Write `prod_census.sql`.** One `SELECT` per table, grouping by `(strategy name or '<none>', mode or '*')`, with `COUNT(*)` and `SUM(…::numeric)` of every money column:
  - positions: quantity, entry_price*quantity, total_charges, realized_pnl, unrealized_pnl; open locked
  - trades: gross_pnl, charges, net_pnl
  - orders: quantity, filled_quantity, brokerage, taxes
  - snapshots: cash, total_value, by mode
  - risk_events: amount_inr
  - brain_approvals: count

  Also list explicitly:
  - (a) every row with mode `live` whose strategy is not `real_trading`;
  - (b) orders, trades and approvals whose `position_id`'s position has a different strategy book than their own `strategy_id`;
  - (c) rows whose `strategy_id` points at a missing strategy;
  - (d) `users` id/username for `vijay` and `sudeeksha` only.

  Wrap the whole file in `BEGIN READ ONLY;` … `ROLLBACK;`.
- [ ] **Step 2: Write `export_prod_copy.sh`** (bash, `set -euo pipefail`):
  1. Run `prod_census.sql` with `docker compose exec -T postgres psql -U swingtrade -d swing_trade_ml -f -` and save the output to `b1_census.txt`.
  2. Write `b1_counts.json` with a row count for every table in the public schema, using `psql -At` and a `json_object_agg` query.
  3. Run `pg_dump -Fc --no-owner` and exclude the **data** of these tables: `broker_sessions`, `login_codes`, `audit_log`, `fills`, and every table defined in `db/models/finance.py` and `db/models/mutual_funds.py`. List their `__tablename__` values explicitly in the script, taken from those files.
  4. Print the three file names and the exact `scp` command to copy them to `D:\machine learning\swing-trade-bot\.local\`. Then say to delete them from the droplet.

  The script never prints row contents.
- [ ] **Step 3:** Add `.local/` to `.gitignore`. Commit both scripts plus `.gitignore` with the message `B1: owner-run export (sanitized) and read-only census for the production copy` and the trailer.
- [ ] **Step 4: Gate.** 🔒 The owner runs the export and shares `b1_census.txt`. If list (a), (b) or (c) is non-empty, **stop**: the owner decides those rows' book before Task 2 runs. Record the decision as an explicit SQL override in Task 2's migration, with the row ids, and test it. If all three are empty, record "census clean" in the ledger and continue. **Without the census, Task 2 must not start.**

---

### Task 2: Self-contained migration (schema, seed, backfill, verify) + model + CLI

**Files:**
- Create: `backend/src/swing_trade_ml/db/models/portfolio.py`; `backend/alembic/versions/20261017_1000_b1_portfolios.py`; `backend/src/swing_trade_ml/db/portfolio_records.py`
- Modify: `db/models/trading.py` (`Order`, `Position`, `Trade`, `PortfolioSnapshot`), `db/models/safety.py` (`RiskEvent`), `db/models/brain_golive.py` (`BrainApproval`), `db/models/__init__.py`, `cli.py`
- Test: `backend/tests/test_b1_portfolio_model.py`, `backend/tests/test_b1_backfill.py`

**Interfaces (produced):**
- In the migration module: `BOOK_DDL` (portfolios table plus constraints), `MONEY_TABLES`, `SEED_SQL`, `BACKFILL_SQL` (ordered: positions first), `TRIGGER_DDL` / `DROP_TRIGGER_DDL` (Task 4 fills these in), and these functions, all taking a SQLAlchemy `Connection`:
  - `census(conn, *, legacy_only=False) -> list[dict]`
  - `verify(conn) -> dict[str, int]`
  - `seed(conn) -> dict[str, int]`
  - `backfill(conn) -> dict[str, int]`
- `swing_trade_ml.db.portfolio_records.load() -> ModuleType`: imports the migration file by path (`importlib.util.spec_from_file_location`) and caches it.
- `Portfolio` model and `PORTFOLIO_KINDS = ("house","tester","real","member")`. `portfolio_id: int | None` on the six models (FK `portfolios.id` ON DELETE RESTRICT, indexed).

- [ ] **Step 1: Reset the test DB schema** (create_all can't add columns):

```bash
cd backend && <python> - <<'EOF'
from sqlalchemy import create_engine, text
url = "postgresql+psycopg://swingtrade:swingtrade_local_pw@localhost:5433/swing_trade_ml_test"
assert url.endswith("_test")
with create_engine(url).begin() as c:
    c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
EOF
```

- [ ] **Step 2: Write the failing model tests** `tests/test_b1_portfolio_model.py`:

```python
"""B1: portfolio constraints (spec §2.1, plan §D2)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from swing_trade_ml.db.models.brain_golive import BrainApproval
from swing_trade_ml.db.models.portfolio import PORTFOLIO_KINDS, Portfolio
from swing_trade_ml.db.models.safety import RiskEvent
from swing_trade_ml.db.models.session import User
from swing_trade_ml.db.models.trading import Order, PortfolioSnapshot, Position, Trade


def _owner(db, name="b1-owner"):
    u = User(username=name, hashed_password="x", role="member")
    db.add(u)
    db.flush()
    return u


def _refused(db, **kw):
    db.add(Portfolio(**kw))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_kinds_and_money_columns():
    assert PORTFOLIO_KINDS == ("house", "tester", "real", "member")
    for model in (Order, Position, Trade, PortfolioSnapshot, RiskEvent, BrainApproval):
        col = model.__table__.c.portfolio_id
        assert col.nullable and {fk.column.table.name for fk in col.foreign_keys} == {"portfolios"}
        assert next(iter(col.foreign_keys)).ondelete == "RESTRICT"


def test_member_defaults(db_session):
    pf = Portfolio(kind="member", name="Practice", mode="paper", owner_user_id=_owner(db_session).id)
    db_session.add(pf)
    db_session.flush()
    assert (pf.generation, pf.status, pf.auto_follow, pf.starting_capital, pf.archived_at) == (1, "active", False, None, None)


@pytest.mark.parametrize("kw", [
    {"kind": "member", "mode": "live"},          # members are paper only
    {"kind": "house", "mode": "live"},           # house is paper
    {"kind": "real", "mode": "paper"},           # real is live
    {"kind": "member", "mode": "paper", "auto_follow": True},  # release D
    {"kind": "member", "mode": "paper", "status": "deleted"},  # unknown status
    {"kind": "member", "mode": "paper", "status": "archived"},  # archived needs archived_at
    {"kind": "member", "mode": "paper", "generation": 0},
    {"kind": "member", "mode": "paper", "name": "  "},
    {"kind": "boss", "mode": "paper"},
])
def test_constraint_refusals(db_session, kw):
    kw = {"name": "x", **kw}
    if kw["kind"] == "member":
        kw["owner_user_id"] = _owner(db_session, f"b1-o-{abs(hash(str(kw)))}").id
    _refused(db_session, **kw)


def test_member_needs_an_owner(db_session):
    _refused(db_session, kind="member", name="Orphan", mode="paper")


def test_one_house_and_one_live_member_portfolio_per_user(db_session):
    db_session.execute(text("DELETE FROM portfolios WHERE kind = 'house'"))
    db_session.add(Portfolio(kind="house", name="H1", mode="paper"))
    db_session.flush()
    _refused(db_session, kind="house", name="H2", mode="paper")
    owner = _owner(db_session, "b1-two")
    db_session.add(Portfolio(kind="member", name="Run 1", mode="paper", owner_user_id=owner.id,
                             status="archived", archived_at=datetime.now(UTC)))
    db_session.add(Portfolio(kind="member", name="Run 2", mode="paper", owner_user_id=owner.id))
    db_session.flush()  # archived + live is fine
    _refused(db_session, kind="member", name="Run 3", mode="paper", owner_user_id=owner.id)


def test_a_user_who_owns_a_portfolio_cannot_be_deleted(db_session):
    owner = _owner(db_session, "b1-keep")
    db_session.add(Portfolio(kind="member", name="Mine", mode="paper", owner_user_id=owner.id))
    db_session.flush()
    with pytest.raises(IntegrityError):
        db_session.execute(text("DELETE FROM users WHERE id = :i"), {"i": owner.id})
        db_session.flush()
    db_session.rollback()
```

(Because of the per-test transaction, any helper that calls `db.rollback()` must be the last DB action in that test. `_refused` is always called last, or followed only by new adds after a fresh flush. Where a test needs two refusals, split it.)

- [ ] **Step 3: Run it and confirm it fails.** Expect `ModuleNotFoundError: swing_trade_ml.db.models.portfolio`.

- [ ] **Step 4: Model** `db/models/portfolio.py`. Mirror D2 exactly, so `create_all` in tests builds the same constraints the migration does:

```python
"""Portfolios: whose money a row is (spec §2.1). B1 creates the three
existing books; member portfolios arrive in release C. Constraints are
mirrored in the B1 migration — keep the two identical."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column

from swing_trade_ml.db.base import Base, TimestampMixin, utcnow

PORTFOLIO_KINDS = ("house", "tester", "real", "member")


class Portfolio(Base, TimestampMixin):
    __tablename__ = "portfolios"
    __table_args__ = (
        CheckConstraint("kind IN ('house','tester','real','member')", name="kind_known"),
        CheckConstraint("(kind = 'real' AND mode = 'live') OR (kind <> 'real' AND mode = 'paper')", name="mode_for_kind"),
        CheckConstraint("status IN ('active','paused','archived')", name="status_known"),
        CheckConstraint("(status = 'archived') = (archived_at IS NOT NULL)", name="archived_has_date"),
        CheckConstraint("generation >= 1", name="generation_positive"),
        CheckConstraint("length(trim(name)) > 0", name="name_present"),
        CheckConstraint("auto_follow = false", name="auto_follow_off"),
        CheckConstraint("kind <> 'member' OR owner_user_id IS NOT NULL", name="member_has_owner"),
        Index("uq_portfolios_one_per_book", "kind", unique=True,
              postgresql_where=text("kind IN ('house','tester','real')")),
        Index("uq_portfolios_one_live_member_run", "owner_user_id", unique=True,
              postgresql_where=text("kind = 'member' AND status <> 'archived'")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # RESTRICT: users are disabled, never deleted, so a portfolio keeps its owner.
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    generation: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    name: Mapped[str] = mapped_column(String(64))
    mode: Mapped[str] = mapped_column(String(8))
    starting_capital: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    status: Mapped[str] = mapped_column(String(12), default="active", server_default="active")
    auto_follow: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=text("now()"))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

Add the `portfolio_id` column to each of the six models, after the primary key:

```python
    # Whose money this is (db/models/portfolio.py). Stamped on insert by a
    # database trigger (B1 migration); nullable until release B2 requires it.
    portfolio_id: Mapped[int | None] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"), index=True)
```

Register the model in `db/models/__init__.py` (`from swing_trade_ml.db.models.portfolio import Portfolio`, and add `"Portfolio"` to `__all__`).

- [ ] **Step 5: Migration file.** Write the self-contained module. Its upgrade order:
  1. `SET LOCAL lock_timeout = '5s'`, `SET LOCAL statement_timeout = '120s'`.
  2. `legacy_only` census.
  3. Create `portfolios` with the D2 constraints (named exactly as the model's convention renders them: `ck_portfolios_<name>`, `uq_portfolios_one_per_book`, `uq_portfolios_one_live_member_run`, `ix_portfolios_owner_user_id`, `fk_portfolios_owner_user_id_users`).
  4. For each money table: add the column, add `fk_<t>_portfolio_id_portfolios` (ON DELETE RESTRICT), and add `ix_<t>_portfolio_id`.
  5. `seed`.
  6. `backfill`.
  7. Triggers (Task 4).
  8. After-census.
  9. `before == after`, else `RuntimeError("B1: totals moved")`.
  10. `verify`.

  The census and verify functions are below. Paste them into the migration verbatim:

```python
MONEY_TABLES = ("orders", "positions", "trades", "portfolio_snapshots", "risk_events", "brain_approvals")
BOOK_OF_STRATEGY = "CASE s.name WHEN 'real_trading' THEN 'real' WHEN 'tester_paper' THEN 'tester' ELSE 'house' END"

SEED_SQL = (
    "INSERT INTO portfolios (kind, name, mode, owner_user_id) "
    "SELECT :k, :n, :m, (SELECT id FROM users WHERE username = :o) "
    "WHERE NOT EXISTS (SELECT 1 FROM portfolios WHERE kind = :k)"
)
BOOKS = (("house", "House account", "paper", None), ("tester", "Testing book", "paper", "vijay"),
         ("real", "My Holdings", "live", "sudeeksha"))

_HOUSE = "(SELECT id FROM portfolios WHERE kind = 'house')"


def _via_strategy(t):
    return f"(SELECT p.id FROM strategies s JOIN portfolios p ON p.kind = {BOOK_OF_STRATEGY} WHERE s.id = {t}.strategy_id)"


def _via_position(t):
    return f"(SELECT pp.portfolio_id FROM positions pp WHERE pp.id = {t}.position_id)"


BACKFILL_SQL = (  # order matters: positions first
    ("positions", f"UPDATE positions SET portfolio_id = COALESCE({_via_strategy('positions')}, {_HOUSE}) WHERE portfolio_id IS NULL"),
    ("risk_events", f"UPDATE risk_events SET portfolio_id = COALESCE({_via_strategy('risk_events')}, {_HOUSE}) WHERE portfolio_id IS NULL"),
    ("orders", f"UPDATE orders SET portfolio_id = COALESCE({_via_position('orders')}, {_via_strategy('orders')}, {_HOUSE}) WHERE portfolio_id IS NULL"),
    ("trades", f"UPDATE trades SET portfolio_id = COALESCE({_via_position('trades')}, {_via_strategy('trades')}, {_HOUSE}) WHERE portfolio_id IS NULL"),
    ("brain_approvals", f"UPDATE brain_approvals SET portfolio_id = COALESCE({_via_position('brain_approvals')}, {_via_strategy('brain_approvals')}, {_HOUSE}) WHERE portfolio_id IS NULL"),
    ("portfolio_snapshots", "UPDATE portfolio_snapshots SET portfolio_id = (SELECT id FROM portfolios WHERE kind = CASE WHEN portfolio_snapshots.mode = 'live' THEN 'real' ELSE 'house' END) WHERE portfolio_id IS NULL"),
)

# table: (follows its position, mode expression, [money columns summed exactly])
CENSUS = {
    "positions": (False, "mode", ["quantity", "entry_price * quantity", "total_charges", "realized_pnl", "unrealized_pnl",
                                   "CASE WHEN status = 'OPEN' THEN entry_price * quantity + total_charges END"]),
    "trades": (True, "mode", ["quantity", "gross_pnl", "charges", "net_pnl"]),
    "orders": (True, "mode", ["quantity", "filled_quantity", "brokerage", "taxes"]),
    "risk_events": (False, "mode", ["amount_inr"]),
    "brain_approvals": (True, "'*'", ["price"]),
    "portfolio_snapshots": (None, "mode", ["cash", "holdings_value", "total_value"]),
}


def _legacy_book(t, follows):
    if follows is None:  # snapshots
        return f"CASE WHEN {t}.mode = 'live' THEN 'real' ELSE 'house' END"
    parts = []
    if follows:
        parts.append(f"(SELECT COALESCE((SELECT {BOOK_OF_STRATEGY} FROM strategies s WHERE s.id = pp.strategy_id), 'house') "
                     f"FROM positions pp WHERE pp.id = {t}.position_id)")
    parts.append(f"(SELECT {BOOK_OF_STRATEGY} FROM strategies s WHERE s.id = {t}.strategy_id)")
    return "COALESCE(" + ", ".join(parts + ["'house'"]) + ")"


def census(conn, *, legacy_only=False):
    out = []
    for t, (follows, mode, cols) in CENSUS.items():
        legacy = _legacy_book(t, follows)
        book = legacy if legacy_only else f"COALESCE((SELECT p.kind FROM portfolios p WHERE p.id = {t}.portfolio_id), {legacy})"
        sums = ", ".join(f"COALESCE(SUM(({c})::numeric), 0)" for c in cols)
        q = f"SELECT {book} AS b, {mode} AS m, COUNT(*), {sums} FROM {t} GROUP BY 1, 2 ORDER BY 1, 2"
        for row in conn.execute(sa.text(q)).all():
            out.append({"table": t, "book": row[0], "mode": row[1], "rows": row[2],
                        **{c: str(v) for c, v in zip(cols, row[3:])}})  # Decimal -> str: exact
    return out


VERIFY = (
    ("V1 rows without a portfolio", "{t}", "SELECT COUNT(*) FROM {t} WHERE portfolio_id IS NULL"),
    ("V2 child differs from its position", "orders,trades,brain_approvals",
     "SELECT COUNT(*) FROM {t} c JOIN positions p ON p.id = c.position_id WHERE c.portfolio_id <> p.portfolio_id"),
    ("V3 row mode differs from its portfolio", "orders,positions,trades,risk_events,portfolio_snapshots",
     "SELECT COUNT(*) FROM {t} r JOIN portfolios p ON p.id = r.portfolio_id WHERE r.mode <> p.mode"),
    ("V3 approval outside house", "brain_approvals",
     "SELECT COUNT(*) FROM {t} r JOIN portfolios p ON p.id = r.portfolio_id WHERE p.kind <> 'house'"),
    ("V6 snapshot outside house/real", "portfolio_snapshots",
     "SELECT COUNT(*) FROM {t} r JOIN portfolios p ON p.id = r.portfolio_id WHERE p.kind NOT IN ('house','real')"),
    ("V7 strategy in the wrong book", "orders,positions,trades,risk_events",
     f"SELECT COUNT(*) FROM {{t}} r JOIN strategies s ON s.id = r.strategy_id JOIN portfolios p ON p.id = r.portfolio_id "
     f"WHERE r.position_id IS NULL AND p.kind <> {BOOK_OF_STRATEGY}"),
)


def verify(conn):
    """Raise naming the check and table on any problem; else return rows per (table, kind)."""
    books = dict(conn.execute(sa.text("SELECT kind, COUNT(*) FROM portfolios WHERE kind IN ('house','tester','real') GROUP BY kind")).all())
    if books != {"house": 1, "tester": 1, "real": 1}:
        raise RuntimeError(f"V5 expected one house, tester and real book, found {books}")
    for check, tables, sql in VERIFY:
        for t in (MONEY_TABLES if tables == "{t}" else tables.split(",")):
            q = sql.format(t=t)
            if t in ("positions", "risk_events") and "position_id" in q:
                q = q.replace("r.position_id IS NULL AND ", "")
            n = conn.execute(sa.text(q)).scalar_one()
            if n:
                raise RuntimeError(f"{check}: {t} has {n} row(s)")
    owners = dict(conn.execute(sa.text(
        "SELECT p.kind, u.username FROM portfolios p LEFT JOIN users u ON u.id = p.owner_user_id "
        "WHERE p.kind IN ('house','tester','real')")).all())
    expected = {"house": None}
    for kind, user in (("tester", "vijay"), ("real", "sudeeksha")):
        exists = conn.execute(sa.text("SELECT 1 FROM users WHERE username = :u"), {"u": user}).scalar()
        expected[kind] = user if exists else None
    if owners != expected:
        raise RuntimeError(f"V4 owner linkage {owners} != {expected}")
    counts = {}
    for t in MONEY_TABLES:
        for kind, n in conn.execute(sa.text(
                f"SELECT p.kind, COUNT(*) FROM {t} r JOIN portfolios p ON p.id = r.portfolio_id GROUP BY 1")).all():
            counts[f"{t}.{kind}"] = n
    return counts
```

  V7 does not apply to `positions` and `risk_events` in the `position_id` form, because those tables have no `position_id`. The `replace` above handles that; write it more plainly if you prefer, but keep the behaviour.

  V8 (exact totals) is the `census before == after` comparison in `upgrade()`. V9 (triggers present) is added in Task 4.

  `downgrade()`: drop the triggers and functions (Task 4), then for each table drop the index, FK and column, then drop `portfolios`. Census `legacy_only` before and after the downgrade must be equal. Raise otherwise.

- [ ] **Step 6: `db/portfolio_records.py`**

```python
"""The B1 migration's own SQL (census, verify, seed, backfill), loaded from the
migration file so the CLI and tests run exactly what the migration ran. The
migration itself imports nothing from this package (reproducibility)."""

from __future__ import annotations

import importlib.util
from functools import cache
from types import ModuleType

from swing_trade_ml.db.session import _find_alembic_dir

_FILE = "versions/20261017_1000_b1_portfolios.py"


@cache
def load() -> ModuleType:
    path = _find_alembic_dir() / "alembic" / _FILE
    spec = importlib.util.spec_from_file_location("b1_portfolios_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
```

  Check what `_find_alembic_dir()` returns (the `backend` dir or the `alembic` dir) and adjust the join.

- [ ] **Step 7: Backfill tests** `tests/test_b1_backfill.py`:
  - Fixture `books`: the same multi-book dataset as revision 1, plus a live-mode `risk_event` under `real_trading`, a live snapshot, and a trade whose `strategy_id` is NULL on a tester position. Then NULL every `portfolio_id` (`UPDATE … SET portfolio_id = NULL`), delete the book rows, and **disable triggers** for the fixture's inserts. Do this by inserting before the conftest triggers are installed, or with `ALTER TABLE … DISABLE TRIGGER USER` inside the test transaction, restoring it afterwards.
  - Tests:
    - each row lands in the D1 book (assert by kind);
    - `census(legacy_only=True)` before == `census()` after, including exact string sums with values like `0.1`, `0.2`;
    - idempotent (a second `backfill` updates 0 rows and leaves deliberately set rows alone);
    - `verify` passes;
    - each verify failure: one test per check V1–V7 + V4 + V5 builds the bad state and asserts `RuntimeError` naming that check and table;
    - **V3 abort:** a live order under `b1_house_ml` makes `verify` raise "V3 … orders".
- [ ] **Step 8: CLI.** `portfolios-check` prints the census, then runs `verify`: ✅, or ❌ with the message and exit 1. `portfolios-backfill` runs `seed`, `backfill`, `verify` and prints rows updated. Both use `portfolio_records.load()` and `session_scope()`.
- [ ] **Step 9: Run** both test files, then the full suite. Everything must be green.
- [ ] **Step 10: Commit**: `B1: self-contained migration — books, constraints, backfill by today's rule, exact census and checks V1–V7` plus the trailer.

---

### Task 3: Golden tests: every book's figures and risk state unchanged

**Files:** Create `backend/tests/test_b1_golden.py`.

**Interfaces:** Consumes Task 2. Uses the API `client` with the API key, plus services, read-only.

- [ ] **Step 1: Write the test.**
  - Fixture `world`, a realistic dataset with the triggers **disabled** for setup and all `portfolio_id` NULL:
    - house: 2 open positions (one scaled out with a partial-exit trade), 3 closed with trades;
    - tester: 2 open, 2 closed;
    - real (`real_trading`, live): 1 open, 1 closed;
    - snapshots before and after `PAPER_TRIAL_START_DATE` (monkeypatch it to a fixed date);
    - one risk event;
    - one brain approval.

    Monkeypatch `kite_broker.get_margins` to return a fixed `available_cash` and `kite_broker.load_session` to a no-op, so the real-book views are deterministic. Never call the network.
  - `snapshot()` collects, as JSON-able values:
    - API views:
      - `GET /portfolio/summary?book=bot|tester|real`
      - `GET /portfolio/positions/detailed?book=bot|tester|real`
      - `GET /portfolio/trades?book=bot|tester|real&all_time=true&limit=1000`
      - `GET /portfolio/equity-curve`
      - `GET /risk/limits`
    - Service values:
      - `paper_broker.get_available_cash(db)`
      - `portfolio_value_and_cash(db, "paper")`
      - `tester_paper.available_cash(db)` and `tester_paper.portfolio_value(db)`
      - `risk.current_drawdown(db, "paper")`
      - `portfolio.drawdown_peak(db, "paper")`
      - `risk.open_position_count(db, "paper")`
      - `[ (h.tradingsymbol, h.value) for h in risk.open_holdings(db, "paper") ]`
      - a `risk.check_entry(...)` decision for a fixed instrument, price and stop (its `approved` flag, rule, reason and quantity)
    - Historical records: every row of trades, positions and snapshots, minus the `portfolio_id` and `updated_at` columns.

    Check each signature in the code before using it, and match the real parameter names.
  - `test_every_view_identical_after_backfill`: `before = snapshot()`, then `seed` + `backfill` + `verify`, `db.expire_all()`, then `after = snapshot()`, and `assert before == after`. Use exact equality (no tolerance).
  - `test_identical_with_triggers_stamping_new_rows`: after backfill, insert one new house trade and one tester trade through the ORM with triggers **enabled**. Then compute the same snapshot via the legacy strategy rule: the figures equal a control run in which the same rows are inserted with triggers disabled. This proves stamping changes nothing.
- [ ] **Step 2: Run** the file, then the full suite. Green.
- [ ] **Step 3: Commit**: `B1: golden tests — house, testing book and My Holdings figures and risk state byte-identical` plus the trailer.

---

### Task 4: Triggers on every insert path (replace the listener)

**Files:** Modify the migration file (fill in `TRIGGER_DDL`, `DROP_TRIGGER_DDL`, add check V9) and `backend/tests/conftest.py`. Create `backend/tests/test_b1_triggers.py`.

**Interfaces:** Produces PL/pgSQL functions `pf_stamp_via_position()`, `pf_stamp_via_strategy()` and `pf_stamp_snapshot()`, and triggers `trg_<table>_pf_stamp` (`BEFORE INSERT … FOR EACH ROW`). In conftest, `db_engine` runs `TRIGGER_DDL` and `seed` after `create_all` (both idempotent; DDL uses `CREATE OR REPLACE FUNCTION` and `DROP TRIGGER IF EXISTS` then `CREATE TRIGGER`), so the **whole suite** runs with stamping active.

- [ ] **Step 1: DDL** (in the migration):

```python
TRIGGER_DDL = [
    f"""CREATE OR REPLACE FUNCTION pf_stamp_via_strategy() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.portfolio_id IS NULL AND NEW.strategy_id IS NOT NULL THEN
        SELECT p.id INTO NEW.portfolio_id FROM strategies s JOIN portfolios p ON p.kind = {BOOK_OF_STRATEGY} WHERE s.id = NEW.strategy_id;
      END IF;
      IF NEW.portfolio_id IS NULL THEN
        SELECT id INTO NEW.portfolio_id FROM portfolios WHERE kind = 'house';
      END IF;
      RETURN NEW;
    END $$""",
    f"""CREATE OR REPLACE FUNCTION pf_stamp_via_position() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.portfolio_id IS NULL AND NEW.position_id IS NOT NULL THEN
        SELECT portfolio_id INTO NEW.portfolio_id FROM positions WHERE id = NEW.position_id;
      END IF;
      IF NEW.portfolio_id IS NULL AND NEW.strategy_id IS NOT NULL THEN
        SELECT p.id INTO NEW.portfolio_id FROM strategies s JOIN portfolios p ON p.kind = {BOOK_OF_STRATEGY} WHERE s.id = NEW.strategy_id;
      END IF;
      IF NEW.portfolio_id IS NULL THEN
        SELECT id INTO NEW.portfolio_id FROM portfolios WHERE kind = 'house';
      END IF;
      RETURN NEW;
    END $$""",
    """CREATE OR REPLACE FUNCTION pf_stamp_snapshot() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.portfolio_id IS NULL THEN
        SELECT id INTO NEW.portfolio_id FROM portfolios WHERE kind = CASE WHEN NEW.mode = 'live' THEN 'real' ELSE 'house' END;
      END IF;
      RETURN NEW;
    END $$""",
]
_TRIGGER_FN = {"orders": "pf_stamp_via_position", "trades": "pf_stamp_via_position",
               "brain_approvals": "pf_stamp_via_position", "positions": "pf_stamp_via_strategy",
               "risk_events": "pf_stamp_via_strategy", "portfolio_snapshots": "pf_stamp_snapshot"}
for _t, _fn in _TRIGGER_FN.items():
    TRIGGER_DDL.append(f"DROP TRIGGER IF EXISTS trg_{_t}_pf_stamp ON {_t}")
    TRIGGER_DDL.append(f"CREATE TRIGGER trg_{_t}_pf_stamp BEFORE INSERT ON {_t} FOR EACH ROW EXECUTE FUNCTION {_fn}()")
DROP_TRIGGER_DDL = [f"DROP TRIGGER IF EXISTS trg_{t}_pf_stamp ON {t}" for t in _TRIGGER_FN] + [
    "DROP FUNCTION IF EXISTS pf_stamp_via_strategy()", "DROP FUNCTION IF EXISTS pf_stamp_via_position()",
    "DROP FUNCTION IF EXISTS pf_stamp_snapshot()"]
```

  Add check V9 to `verify`: `SELECT COUNT(*) FROM pg_trigger WHERE tgname LIKE 'trg_%_pf_stamp' AND NOT tgisinternal` must equal 6, else `RuntimeError("V9 …")`.

  Also verify on PG16 that `SELECT … INTO NEW.portfolio_id` works. If it doesn't, use a local variable and assign it.

- [ ] **Step 2: Tests** `tests/test_b1_triggers.py`. One test per write path, each asserting the D1 book:
  - (a) ORM `session.add(Position(...))`;
  - (b) Core `db.execute(insert(Order).values(...))`;
  - (c) `executemany` (`db.execute(insert(Trade), [ {...}, {...} ])`);
  - (d) `db.bulk_save_objects([...])`;
  - (e) raw `db.execute(text("INSERT INTO risk_events (...) VALUES (...)"))`;
  - (f) an explicit `portfolio_id` (member portfolio) is kept;
  - (g) a trade on a tester position with NULL strategy → tester;
  - (h) a live snapshot → real, a paper snapshot → house;
  - (i) **no books seeded** (delete the portfolios in the test): the insert succeeds with NULL, and the trigger never raises;
  - (j) V9 passes with triggers present and fails naming V9 after `DROP TRIGGER` on one table.
- [ ] **Step 3: conftest.** In `db_engine`, after `create_all`, load the migration via `portfolio_records.load()`. Execute `TRIGGER_DDL` and `seed()` in one committed transaction. Comment that this makes the whole suite run with production-equal stamping.
- [ ] **Step 4: Run** the trigger tests, then the **full suite**. Every existing trading test (execution, exits, tester buys, brain go-live) must pass with the triggers live. Any failure is a real finding: report it, and don't skip it.
- [ ] **Step 5: Commit**: `B1: database triggers stamp every insert path (ORM, Core, bulk, raw SQL, old code); check V9` plus the trailer.

---

### Task 5: Production-copy rehearsal, old code on new schema, schema-vs-model check

**Files:** Create `backend/scripts/rehearse_b1_on_prod_copy.py` and `docs/deploy/B1-portfolios-runbook.md`.

**Interfaces:** The script takes `--dump`, `--counts`, `[--delete-dump]` and works only on DB `swing_trade_ml_b1_rehearsal` (assert the name ends with `_rehearsal`; `os.environ["DATABASE_URL"]` is overwritten before any app import).

- [ ] **Step 1: Script behaviour** (each step prints a ✅ or stops with ❌ and a reason):
  1. Drop and create the scratch DB. If the dump contains TimescaleDB objects, `CREATE EXTENSION IF NOT EXISTS timescaledb` and `SELECT timescaledb_pre_restore()` before the restore, and `timescaledb_post_restore()` after.
  2. `docker cp` the dump into the container, then `pg_restore --no-owner -d <db>`, capturing stderr. Accept exit code 0. Accept a non-zero code **only if every error line matches** an allowlist written in the script (`must be owner of extension`, `extension "timescaledb" already exists`, `schema "public" already exists`, `comment on extension`). Anything else is ❌, and the stderr is printed with row data redacted.
  3. **Counts:** compare the row count of every table with `b1_counts.json`. Excluded-data tables must be 0. Any other mismatch is ❌.
  4. **Sanitize** (immediately after the restore): `UPDATE users SET hashed_password = 'x', email = NULL, google_id = NULL`; `TRUNCATE broker_sessions, login_codes, audit_log` (if present). Assert the excluded tables are empty.
  5. **Revision:** read `alembic_version`. Upgrade to `e1p0s2e3c4u5` first if P0 isn't there yet (and say so). Take the `before` census (`legacy_only=True`).
  6. `alembic upgrade f2b1p0r7f0l1`. Then `verify` (V1–V9), and print the census by book with exact sums plus the owner linkage. **Require** `tester → vijay` and `real → sudeeksha`, else ❌.
  7. **Inserts after upgrade:** in a transaction that is rolled back, insert one order per book through raw SQL with `portfolio_id` NULL and assert the trigger stamped it.
  8. **Schema vs model:** use `alembic.autogenerate.compare_metadata` against the app metadata, filtered to `portfolios` and every `portfolio_id` column, index, FK and check. Expect no differences. Print any found and ❌.
  9. `alembic downgrade e1p0s2e3c4u5`. Assert there is no `portfolios` table, no `portfolio_id` columns, no `pf_stamp` functions or triggers, and `census(legacy_only=True) == before`.
  10. Re-upgrade, and `verify` again.
  11. `finally:` always drop the scratch DB and remove the temp file in the container. With `--delete-dump`, delete the local dump and counts. Otherwise print the exact delete command.
- [ ] **Step 2: Old code on the new schema.** Upgrade a second scratch DB built from the prod copy. Start the **pre-B1** `develop` build from a `git worktree add --detach` temp dir on port 8077 with `ENVIRONMENT=local ENABLE_SCHEDULER=false DB_AUTO_MIGRATE=true`. Check:
  - `/health` is ok;
  - login works (create a user with the old CLI);
  - open one paper position through the old code path (old `swingtrade` CLI manual entry, or a short script against that DB);
  - assert the new row was **stamped by the trigger**;
  - the old startup survived the newer revision (the `create_all` fallback, as in P0).

  Clean up the worktree, the server and the DB.
- [ ] **Step 3: Run** the script against the owner's copy. Paste the evidence (✅ lines, census sums by book, owner linkage; no names, symbols or emails) into the runbook. **Without the owner's copy, stop and report DONE_WITH_CONCERNS. This is a merge gate.**
- [ ] **Step 4: Runbook** `docs/deploy/B1-portfolios-runbook.md` contains the Rollout gates below, verbatim, plus the rollback section and the evidence.
- [ ] **Step 5: Commit** the script and runbook with the message `B1: production-copy rehearsal (strict restore, counts, sanitize, cleanup, down/up, schema check) and runbook` plus the trailer. **Never commit the dump or counts.**

---

### Task 6: Guarantees: nothing exposed, decided or traded differently

**Files:** Create `backend/tests/test_b1_guarantees.py`.

- [ ] **Step 1: Tests:**
  - (a) No API response anywhere contains a `portfolio_id` or `portfolios` key. Walk every GET route as the owner with `_routes()`/`_url()` from `test_permissions_review` (sibling import), recursively scanning JSON bodies for the key. Responses that aren't JSON are skipped.
  - (b) The OpenAPI schema contains no `portfolio_id` property.
  - (c) The live-trading gate is unchanged: `settings.is_live_trading` is False under the test env, and `get_broker().mode == "paper"`.
  - (d) A signal scan over a fixed fixture produces the same signals (type, confidence, rejection reason) with the triggers on and off. Reuse an existing engine test fixture, and find one with `grep -l run_strategy backend/tests`.
  - (e) Brain tables have no new columns: compare `brain_*` table column sets with a list frozen in the test from the current models (except `brain_approvals`, which may add only `portfolio_id`).
- [ ] **Step 2: Diff guard.** `git diff --stat develop..HEAD -- backend/src/swing_trade_ml/services backend/src/swing_trade_ml/brokers backend/src/swing_trade_ml/brain backend/src/swing_trade_ml/strategies backend/src/swing_trade_ml/api frontend backend/src/swing_trade_ml/schemas` must print nothing. Record the output in the report.
- [ ] **Step 3: Full suite** green, then commit: `B1: guarantees — no exposure, unchanged decisions, live gate untouched, brain trial untouched` plus the trailer.

---

## Acceptance criteria (B1 is done only when every line holds)

1. Prod-copy census (Task 1) reviewed by the owner. No live-mode row maps to house, unless the owner made a recorded override.
2. Every row in the six money tables has a portfolio (V1). Child rows agree with their position (V2). Row mode equals portfolio mode (V3). Owners are linked (`tester→vijay`, `real→sudeeksha`) (V4). There is exactly one of each book (V5). Snapshots are only house or real (V6). Strategy and book agree (V7). Totals are exactly equal before and after (V8). The six triggers are present (V9).
3. The golden test is byte-identical for house, testing book and My Holdings, covering cash, holdings, P&L, drawdown, peak, slot count, holdings, a sample risk decision, and every historical row.
4. Every insert path is stamped by the trigger, the trigger never raises, and the whole existing suite passes with triggers live.
5. The rehearsal on the sanitized prod copy passes every step, including downgrade → schema gone → re-upgrade, and the schema-vs-model check.
6. Old code on the new schema boots, logs in, and its inserts are stamped.
7. No API or screen exposes portfolios. Signals, risk and trading are unchanged. The live gate and the brain trial are untouched. The diff guard is empty.
8. The full backend suite and frontend tsc are green (frontend unchanged).

## Regression tests added

`test_b1_portfolio_model.py` (constraints, RESTRICT, uniqueness) · `test_b1_backfill.py` (rule, exact census, idempotency, every V-check failure, V3 abort) · `test_b1_golden.py` (all books' views and risk state) · `test_b1_triggers.py` (ORM, Core, executemany, bulk, raw SQL, explicit, no-books, V9) · `test_b1_guarantees.py` (no exposure, same decisions, live gate, brain columns). The whole existing suite also runs with triggers on (conftest).

## Unresolved risks

| Risk | Mitigation / owner decision |
|---|---|
| Prod rows outside the API's view (live orders, risk events, snapshots) may not fit the rule | Task 1 census gate; V3 aborts; owner overrides recorded per row |
| Logic in triggers is less visible than Python for a single developer | Three short functions, documented in the code map. B2 can move stamping into the executor and drop the triggers once every write goes through it |
| `SELECT … INTO NEW.col` behaviour or Timescale restore quirks on the prod image | Verified on the same Postgres image in Task 4/5 before anything ships |
| Deploy window: the worker writes while the migration holds locks | Worker stopped; off-hours window; `lock_timeout` 5 s fails fast and the deploy is retried |
| Prod copy holds personal data on a laptop | Secrets and finance data excluded at export; hashes and emails scrubbed on restore; deleted after |
| Old code after rollback writes rows the new code later needs to read by portfolio | The trigger stamps them; `portfolios-backfill` covers a downgraded window |

## Rollout gates (🔒 = owner)

1. 🔒 Plan approved (this document).
2. 🔒 P0 deployed and stable for at least one trading day.
3. 🔒 Prod-copy census and rehearsal pass (Tasks 1, 5). Evidence is in the runbook.
4. Full suite + tsc green on the merged tree, and the diff guard is empty.
5. 🔒 Full `pg_dump` backup taken on the droplet and named in the runbook.
6. 🔒 Deploy window between 22:30 and 06:00 IST: `docker compose stop worker` → merge to `main` (deploy) → API log shows `db.migrate.done` → `docker compose exec api swingtrade portfolios-check` ✅ → `docker compose start worker`.
7. House, testing book and My Holdings figures on screen equal the values written down before the deploy. `/status` is unchanged.
8. Next morning after the 09:15 and 15:45 jobs, `portfolios-check` ✅ again (new rows stamped).
9. 🔒 One clean day → B2 may begin (it starts by making `portfolio_id` required).

**Rollback:**
- **Code:** revert the merge. The old code ignores the column and table, and the triggers keep stamping its inserts (rehearsed).
- **Schema** (only if needed): stop the worker, then `alembic downgrade e1p0s2e3c4u5`. This drops the triggers, columns and table, with no other data change (rehearsed). Re-upgrading backfills anything written meanwhile.
