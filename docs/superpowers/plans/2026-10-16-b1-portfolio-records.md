# Release B1: Portfolio Records and Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every money row an owner portfolio (house, tester, real) without changing a single number the app shows or a single trading decision.

**Architecture:** A new `portfolios` table holds one row each for the house account, Vijay's testing book and My Holdings. A nullable `portfolio_id` column is added to orders, positions, trades, portfolio_snapshots, risk_events and brain_approvals, and existing rows are backfilled. The rule is today's strategy-name rule: `real_trading` → real, `tester_paper` → tester, everything else → house. New rows are stamped automatically by an ORM `before_insert` listener, so `services/execution.py` and every trading path stay untouched. Reads don't change yet; scoping reads by portfolio is release B2.

**Tech Stack:** SQLAlchemy 2 (Mapped, ORM events), Alembic, Postgres (TimescaleDB image), pytest with the shared `db_session` fixture.

**Spec:** `docs/superpowers/specs/2026-10-16-multi-user-portfolios-design.md` (rev 2): §1.2 idea 1, §2.1 `portfolios`, §2.2 changed tables, §2.4 backfill mapping, §8 migration principles, §9 house golden test + migration rows, §10 release B.

## Global Constraints

- Work on a new local branch `feature/b1-portfolios` cut from `develop` (which contains P0 at `7562526`). **No push, merge, deploy or prod change** without the owner's separate approval.
- **No behaviour change.** No read query changes in this release. `services/execution.py`, `services/risk.py`, `brokers/paper.py`, `services/portfolio.py` and `services/tester_paper.py` are NOT modified. The house trial's cash, value, drawdown and P&L must come out identical. That is the golden test.
- `portfolio_id` stays **nullable** in B1. Making it `NOT NULL` is release B2's first migration, after one clean prod day.
- The stamping listener must **never raise** into a trading flush. On any unexpected Python-level problem it leaves `portfolio_id` NULL and logs `portfolio.stamp_failed`. NULLs are found by `swingtrade portfolios-check` and fixed by `swingtrade portfolios-backfill`.
- Backfill rule (exact): position's portfolio if the row has a `position_id` whose position has one; else by strategy name `real_trading` → `real`, `tester_paper` → `tester`; else (any other strategy, or no strategy) → `house`. `portfolio_snapshots` → always `house`.
- Portfolio rows created by the migration (exact): `house` "House account", mode `paper`, owner NULL; `tester` "Testing book", mode `paper`, owner = user `vijay` if present else NULL; `real` "My Holdings", mode `live`, owner = user `sudeeksha` if present else NULL. All with `status='active'`, `generation=1`, `auto_follow=false`, `starting_capital=NULL` (the house and tester books keep reading their settings until B2).
- New alembic revision `f2b1p0r7f0l1`, down_revision `e1p0s2e3c4u5`. Confirm the single head first.
- Python `D:/machine learning/swing-trade-bot/backend/.venv/Scripts/python.exe`. Tests: `cd backend && env -u API_KEY -u DATABASE_URL -u JWT_SECRET_KEY -u TRADING_MODE <python> -m pytest … -q`. Docker Postgres `stml-postgres` on 5433 must be up.
- `ruff format` only files you touched. Never read or print `.env`. Never use bare `git stash`.
- The production database copy (Task 4) is owner-provided. It must exclude secret tables, live only in a scratch DB, and be deleted after the rehearsal.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **An order with no strategy and no position** (manual or legacy rows) must land in `house`, never NULL. Pinned in Task 2 and Task 3 tests.
2. **A Trade or Order whose position is in the tester book but whose `strategy_id` is NULL or different** must follow the position. Pinned in Task 2 and Task 3.
3. **Rows inserted by old code after a rollback** (`portfolio_id` NULL) must be fixable by re-running `portfolios-backfill` without changing already-set rows. Pinned in Task 2 (idempotency test).
4. **The listener on a database where the `portfolios` rows don't exist** (create_all fallback, fresh DB) must leave NULL and not break the insert. Pinned in Task 3.
5. **Live-mode rows under strategies other than `real_trading`** (e.g. advisory long-term tracking) go to `house`, matching today's `exclude_real_trading` rule, and the census in Task 4 must show them explicitly so the owner can see where they went. Pinned in Task 2 and Task 4.

---

## File map

| File | Responsibility | Task |
|---|---|---|
| `backend/src/swing_trade_ml/db/models/portfolio.py` (new) | `Portfolio` model, `PORTFOLIO_KINDS` | 1 |
| `backend/src/swing_trade_ml/db/models/trading.py`, `safety.py`, `brain_golive.py` | `portfolio_id` column on 6 models | 1 |
| `backend/src/swing_trade_ml/db/models/__init__.py` | register `Portfolio` | 1 |
| `backend/alembic/versions/20261017_1000_b1_portfolios.py` (new) | schema, seed rows, backfill, post-checks, downgrade | 1, 2 |
| `backend/src/swing_trade_ml/db/portfolio_backfill.py` (new) | backfill SQL, `backfill(conn)`, `census(conn)`, `verify(conn)` | 2 |
| `backend/src/swing_trade_ml/db/portfolio_stamp.py` (new) | `before_insert` listeners | 3 |
| `backend/src/swing_trade_ml/cli.py` | `portfolios-check`, `portfolios-backfill` | 2 |
| `backend/tests/test_b1_portfolio_model.py`, `test_b1_backfill.py`, `test_b1_stamp.py` (new) | tests | 1–3 |
| `backend/scripts/rehearse_b1_on_prod_copy.py` (new), `docs/deploy/B1-portfolios-runbook.md` (new) | prod-copy rehearsal, deploy/rollback | 4 |

---

### Task 0: Branch and test-DB reset

- [ ] **Step 1:** `cd "D:/machine learning/swing-trade-bot" && git switch develop && git switch -c feature/b1-portfolios` (or a worktree under `.claude/worktrees/b1-portfolios`).
- [ ] **Step 2:** `cd backend && <python> -m alembic heads`. Expected: exactly `e1p0s2e3c4u5`. If not, use the printed head as `down_revision` and say so.
- [ ] **Step 3:** `docker exec stml-postgres pg_isready`. Expected: `accepting connections`.

---

### Task 1: `Portfolio` model, `portfolio_id` columns, schema migration

**Files:**
- Create: `backend/src/swing_trade_ml/db/models/portfolio.py`
- Modify: `backend/src/swing_trade_ml/db/models/trading.py` (`Order`, `Position`, `Trade`, `PortfolioSnapshot`), `safety.py` (`RiskEvent`), `brain_golive.py` (`BrainApproval`), `db/models/__init__.py`
- Create: `backend/alembic/versions/20261017_1000_b1_portfolios.py` (schema part)
- Test: `backend/tests/test_b1_portfolio_model.py`

**Interfaces:**
- Produces: `Portfolio` (table `portfolios`) with `id, owner_user_id, kind, generation, name, mode, starting_capital, status, auto_follow, started_at, archived_at, created_at, updated_at`. `PORTFOLIO_KINDS = ("house", "tester", "real", "member")`. `portfolio_id: int | None` on the six models (FK `portfolios.id`, `ondelete="RESTRICT"`, indexed).

- [ ] **Step 1: Reset the test DB schema** (create_all cannot add columns to existing tables)

```bash
cd backend && "D:/machine learning/swing-trade-bot/backend/.venv/Scripts/python.exe" - <<'EOF'
from sqlalchemy import create_engine, text
url = "postgresql+psycopg://swingtrade:swingtrade_local_pw@localhost:5433/swing_trade_ml_test"
assert url.endswith("_test")
with create_engine(url).begin() as c:
    c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
print("test schema reset")
EOF
```

- [ ] **Step 2: Write the failing tests**

```python
# backend/tests/test_b1_portfolio_model.py
"""B1: portfolios exist as rows; money tables can point at one."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from swing_trade_ml.db.models.brain_golive import BrainApproval
from swing_trade_ml.db.models.portfolio import PORTFOLIO_KINDS, Portfolio
from swing_trade_ml.db.models.safety import RiskEvent
from swing_trade_ml.db.models.trading import Order, PortfolioSnapshot, Position, Trade


def test_kinds():
    assert PORTFOLIO_KINDS == ("house", "tester", "real", "member")


def test_every_money_model_has_a_nullable_portfolio_id():
    for model in (Order, Position, Trade, PortfolioSnapshot, RiskEvent, BrainApproval):
        col = model.__table__.c.portfolio_id
        assert col.nullable is True, model.__name__
        assert {fk.column.table.name for fk in col.foreign_keys} == {"portfolios"}, model.__name__


def test_defaults(db_session):
    pf = Portfolio(kind="member", name="Practice", mode="paper")
    db_session.add(pf)
    db_session.flush()
    assert (pf.generation, pf.status, pf.auto_follow, pf.starting_capital) == (1, "active", False, None)


def test_member_portfolio_must_be_paper(db_session):
    db_session.add(Portfolio(kind="member", name="Bad", mode="live"))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_auto_follow_stays_off_until_release_d(db_session):
    db_session.add(Portfolio(kind="member", name="Auto", mode="paper", auto_follow=True))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_only_one_house_tester_and_real(db_session):
    db_session.add(Portfolio(kind="house", name="H1", mode="paper"))
    db_session.flush()
    db_session.add(Portfolio(kind="house", name="H2", mode="paper"))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()
```

- [ ] **Step 3: Run to verify failure.** `… -m pytest tests/test_b1_portfolio_model.py -v` → FAIL `ModuleNotFoundError: swing_trade_ml.db.models.portfolio`.

- [ ] **Step 4: Create `db/models/portfolio.py`**

```python
"""Portfolios: whose money a row is (spec §2.1). Release B1 creates the three
existing books — the house account, the testing book and My Holdings — and
points every money row at one. Member portfolios arrive in release C."""

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
        CheckConstraint("kind = 'real' OR mode = 'paper'", name="paper_unless_real"),
        # Automatic following is release D; until then nobody can switch it on.
        CheckConstraint("auto_follow = false", name="auto_follow_off"),
        Index(
            "uq_portfolios_one_per_book",
            "kind",
            unique=True,
            postgresql_where=text("kind IN ('house','tester','real')"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    # +1 each time a member restarts their practice run (release C); history is kept.
    generation: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    name: Mapped[str] = mapped_column(String(64))
    mode: Mapped[str] = mapped_column(String(8))
    # Members: their practice money at creation (release C). NULL for the
    # house and testing books, which still read their settings until B2.
    starting_capital: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    status: Mapped[str] = mapped_column(String(12), default="active", server_default="active")
    auto_follow: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

- [ ] **Step 5: Add `portfolio_id` to the six models.** In each of `Order`, `Position`, `Trade`, `PortfolioSnapshot` (`trading.py`), `RiskEvent` (`safety.py`), `BrainApproval` (`brain_golive.py`), add after the primary key:

```python
    # Whose money this is (db/models/portfolio.py). Stamped on insert by
    # db/portfolio_stamp.py; nullable until release B2 makes it required.
    portfolio_id: Mapped[int | None] = mapped_column(
        ForeignKey("portfolios.id", ondelete="RESTRICT"), index=True
    )
```

(`ForeignKey` is already imported in all three files; add it where missing.) Register in `db/models/__init__.py`: `from swing_trade_ml.db.models.portfolio import Portfolio` and add `"Portfolio",` to `__all__`.

- [ ] **Step 6: Migration (schema part)** `backend/alembic/versions/20261017_1000_b1_portfolios.py`

```python
"""B1: portfolios table; portfolio_id on every money table; backfill

Additive only. Reads do not change in this release; release B2 makes
portfolio_id required and scopes every query by it.

Revision ID: f2b1p0r7f0l1
Revises: e1p0s2e3c4u5
Create Date: 2026-10-17 10:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2b1p0r7f0l1"
down_revision: str | None = "e1p0s2e3c4u5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MONEY_TABLES = ("orders", "positions", "trades", "portfolio_snapshots", "risk_events", "brain_approvals")


def upgrade() -> None:
    op.create_table(
        "portfolios",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("mode", sa.String(8), nullable=False),
        sa.Column("starting_capital", sa.Numeric(14, 2), nullable=True),
        sa.Column("status", sa.String(12), nullable=False, server_default="active"),
        sa.Column("auto_follow", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('house','tester','real','member')", name="ck_portfolios_kind_known"),
        sa.CheckConstraint("kind = 'real' OR mode = 'paper'", name="ck_portfolios_paper_unless_real"),
        sa.CheckConstraint("auto_follow = false", name="ck_portfolios_auto_follow_off"),
    )
    op.create_index("ix_portfolios_owner_user_id", "portfolios", ["owner_user_id"])
    op.create_index(
        "uq_portfolios_one_per_book", "portfolios", ["kind"], unique=True,
        postgresql_where=sa.text("kind IN ('house','tester','real')"),
    )
    for table in MONEY_TABLES:
        op.add_column(table, sa.Column("portfolio_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_portfolio_id_portfolios", table, "portfolios", ["portfolio_id"], ["id"], ondelete="RESTRICT"
        )
        op.create_index(f"ix_{table}_portfolio_id", table, ["portfolio_id"])
    # Task 2 adds the seed rows + backfill + post-checks here.


def downgrade() -> None:
    for table in MONEY_TABLES:
        op.drop_index(f"ix_{table}_portfolio_id", table_name=table)
        op.drop_constraint(f"fk_{table}_portfolio_id_portfolios", table, type_="foreignkey")
        op.drop_column(table, "portfolio_id")
    op.drop_index("uq_portfolios_one_per_book", table_name="portfolios")
    op.drop_index("ix_portfolios_owner_user_id", table_name="portfolios")
    op.drop_table("portfolios")
```

Check that the model's index and constraint names match the migration's. With the repo's naming convention, `index=True` gives `ix_<table>_portfolio_id`, the FK gives `fk_<table>_portfolio_id_portfolios`, and `CheckConstraint(name="kind_known")` gives `ck_portfolios_kind_known`. If any convention-generated name differs, change the **migration** to match the model, and say so in the report.

- [ ] **Step 7: Run tests.** `… -m pytest tests/test_b1_portfolio_model.py -v` → 6 passed. Then `… -m pytest -q` (full suite) → all green. This proves that adding nullable columns changed nothing.

- [ ] **Step 8: Format and commit**

```bash
cd backend && <python> -m ruff format src/swing_trade_ml/db/models/portfolio.py alembic/versions/20261017_1000_b1_portfolios.py tests/test_b1_portfolio_model.py
cd .. && git add backend/src/swing_trade_ml/db/models/ backend/alembic/versions/20261017_1000_b1_portfolios.py backend/tests/test_b1_portfolio_model.py
git commit -m "B1: portfolios table and a nullable portfolio_id on every money table

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

(Use ruff only on the new file and the test; for `trading.py`/`safety.py`/`brain_golive.py` revert any unrelated ruff hunks.)

---

### Task 2: Seed rows, backfill, census, post-checks, CLI

**Files:**
- Create: `backend/src/swing_trade_ml/db/portfolio_backfill.py`
- Modify: `backend/alembic/versions/20261017_1000_b1_portfolios.py` (call seed + backfill + verify at the end of `upgrade()`)
- Modify: `backend/src/swing_trade_ml/cli.py` (`portfolios-check`, `portfolios-backfill`)
- Test: `backend/tests/test_b1_backfill.py`

**Interfaces:**
- Consumes: Task 1 schema.
- Produces, all taking a SQLAlchemy `Connection` and executing plain SQL (no ORM, so the migration stays stable as models evolve):
  - `seed(conn) -> dict[str, int]`: creates the house/tester/real rows if missing and returns `{kind: id}`. Idempotent.
  - `backfill(conn) -> dict[str, int]`: fills `portfolio_id` **only where NULL** using the Global Constraints rule, and returns rows updated per table.
  - `census(conn, *, legacy_only=False) -> list[dict]`: one row per (table, book, mode) with `rows`, `sum_net_pnl` (trades) and `open_locked` (open positions: `Σ entry_price*quantity + total_charges`). A row's book is its portfolio kind when it has one, else the legacy rule. `legacy_only=True` never reads `portfolio_id`. `brain_approvals` has no `mode`, so its mode is `'*'`.
  - `verify(conn) -> dict[str, int]`: raises `RuntimeError` naming the table if any row of a money table still has NULL `portfolio_id`; otherwise returns counts per (table, kind).
- **This module is frozen once released.** Later releases add new modules and never edit this one, because the B1 migration imports it.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_b1_backfill.py
"""B1 backfill: every existing row lands in the book today's code already treats it as,
and no figure the app shows moves (the house golden test)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from swing_trade_ml.brokers.paper import paper_broker
from swing_trade_ml.db import portfolio_backfill as pb
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Order, PortfolioSnapshot, Position, Strategy, Trade
from swing_trade_ml.services import tester_paper
from swing_trade_ml.services.portfolio import portfolio_value_and_cash

NOW = datetime(2026, 10, 1, 9, 30, tzinfo=UTC)


def _inst(db, sym):
    inst = Instrument(instrument_token=abs(hash(sym)) % 10_000_000, tradingsymbol=sym, exchange="NSE")
    db.add(inst)
    db.flush()
    return inst


def _strategy(db, name, mode="paper", stype="ml_swing"):
    s = Strategy(name=name, strategy_type=stype, mode=mode, is_active=False)
    db.add(s)
    db.flush()
    return s


@pytest.fixture()
def books(db_session):
    """Rows as they look before B1: house (incl. no-strategy rows), tester, real, and a live advisory row."""
    db = db_session
    house = _strategy(db, "b1_house_ml")
    tester = tester_paper.get_or_create_strategy(db)
    real = _strategy(db, "real_trading", mode="live", stype="real_trading")
    advisory_live = _strategy(db, "b1_long_term_live", mode="live", stype="long_term_value")
    rows = {}
    for key, strat, mode, sym in (
        ("house_open", house, "paper", "B1H1"), ("tester_open", tester, "paper", "B1T1"),
        ("real_open", real, "live", "B1R1"), ("adv_open", advisory_live, "live", "B1A1"),
    ):
        inst = _inst(db, sym)
        rows[key] = Position(strategy_id=strat.id, instrument_id=inst.id, mode=mode, status="OPEN",
                             quantity=10, initial_quantity=10, entry_price=100.0, entry_at=NOW, total_charges=5.0)
        db.add(rows[key])
    db.flush()
    nostrat = _inst(db, "B1N1")
    rows["order_nostrat"] = Order(instrument_id=nostrat.id, mode="paper", transaction_type="BUY", quantity=1, placed_at=NOW)
    # tester position but an order with NO strategy: must follow the position
    rows["order_on_tester_pos"] = Order(instrument_id=rows["tester_open"].instrument_id, mode="paper",
                                        transaction_type="SELL", quantity=1, placed_at=NOW,
                                        position_id=rows["tester_open"].id)
    rows["house_trade"] = Trade(position_id=rows["house_open"].id, strategy_id=house.id,
                                instrument_id=rows["house_open"].instrument_id, mode="paper", symbol="B1H1",
                                quantity=5, entry_price=100, exit_price=110, entry_at=NOW, exit_at=NOW,
                                gross_pnl=50, charges=2, net_pnl=48, return_pct=0.1, is_win=True)
    rows["snap"] = PortfolioSnapshot(mode="paper", ts=NOW, cash=1.0, holdings_value=1.0, total_value=2.0)
    db.add_all([rows["order_nostrat"], rows["order_on_tester_pos"], rows["house_trade"], rows["snap"]])
    db.flush()
    # Simulate pre-B1 rows: nothing stamped yet (the Task 3 listener may stamp on insert).
    for table in pb.MONEY_TABLES:
        db.execute(text(f"UPDATE {table} SET portfolio_id = NULL"))
    db.execute(text("DELETE FROM portfolios"))
    db.flush()
    return rows


def _kind_of(db, table, row_id):
    return db.execute(text(
        f"SELECT p.kind FROM {table} t JOIN portfolios p ON p.id = t.portfolio_id WHERE t.id = :i"
    ), {"i": row_id}).scalar_one()


def test_backfill_maps_each_row_to_todays_book(db_session, books):
    conn = db_session.connection()
    pb.seed(conn)
    pb.backfill(conn)
    assert _kind_of(db_session, "positions", books["house_open"].id) == "house"
    assert _kind_of(db_session, "positions", books["tester_open"].id) == "tester"
    assert _kind_of(db_session, "positions", books["real_open"].id) == "real"
    assert _kind_of(db_session, "positions", books["adv_open"].id) == "house"  # matches exclude_real_trading today
    assert _kind_of(db_session, "orders", books["order_nostrat"].id) == "house"
    assert _kind_of(db_session, "orders", books["order_on_tester_pos"].id) == "tester"  # follows its position
    assert _kind_of(db_session, "trades", books["house_trade"].id) == "house"
    assert _kind_of(db_session, "portfolio_snapshots", books["snap"].id) == "house"
    pb.verify(conn)  # no NULLs left


def test_house_golden_figures_do_not_move(db_session, books):
    before = (paper_broker.get_available_cash(db_session), portfolio_value_and_cash(db_session, "paper"),
              tester_paper.available_cash(db_session))
    conn = db_session.connection()
    pb.seed(conn)
    pb.backfill(conn)
    db_session.expire_all()
    after = (paper_broker.get_available_cash(db_session), portfolio_value_and_cash(db_session, "paper"),
             tester_paper.available_cash(db_session))
    assert before == after


def test_census_totals_match_before_and_after(db_session, books):
    conn = db_session.connection()
    legacy = {(r["table"], r["book"]): (r["rows"], r["sum_net_pnl"], r["open_locked"]) for r in pb.census(conn)}
    pb.seed(conn)
    pb.backfill(conn)
    now = {(r["table"], r["book"]): (r["rows"], r["sum_net_pnl"], r["open_locked"]) for r in pb.census(conn)}
    assert legacy == now


def test_backfill_is_idempotent_and_never_overwrites(db_session, books):
    conn = db_session.connection()
    ids = pb.seed(conn)
    pb.backfill(conn)
    db_session.execute(text("UPDATE positions SET portfolio_id = :t WHERE id = :p"),
                       {"t": ids["tester"], "p": books["house_open"].id})  # a row someone set deliberately
    db_session.execute(text("UPDATE orders SET portfolio_id = NULL WHERE id = :o"), {"o": books["order_nostrat"].id})
    assert pb.seed(conn) == ids
    updated = pb.backfill(conn)
    assert updated["orders"] == 1 and updated["positions"] == 0
    assert _kind_of(db_session, "positions", books["house_open"].id) == "tester"  # untouched


def test_verify_names_the_table_with_nulls(db_session, books):
    conn = db_session.connection()
    pb.seed(conn)
    with pytest.raises(RuntimeError, match="positions"):
        pb.verify(conn)


def test_seed_links_owner_accounts_when_present(db_session, books):
    from swing_trade_ml.db.models.session import User
    db_session.add_all([User(username="vijay", hashed_password="x", role="tester"),
                        User(username="sudeeksha", hashed_password="x", role="owner")])
    db_session.flush()
    ids = pb.seed(db_session.connection())
    owners = dict(db_session.execute(text(
        "SELECT p.kind, u.username FROM portfolios p LEFT JOIN users u ON u.id = p.owner_user_id"
    )).all())
    assert owners == {"house": None, "tester": "vijay", "real": "sudeeksha"} and set(ids) == {"house", "tester", "real"}
```

The fixture creates `vijay`/`sudeeksha` only in the last test. If the test DB already has users with those names from other fixtures in the same transaction, adjust by checking for existence first.

- [ ] **Step 2: Run to verify failure.** → FAIL `ImportError: cannot import name 'portfolio_backfill'`.

- [ ] **Step 3: Implement `db/portfolio_backfill.py`**

```python
"""B1 backfill: point every existing money row at its portfolio.

Plain SQL on a Connection so the B1 migration keeps working however the ORM
models change later. FROZEN once released: the migration imports this file;
later releases add their own modules instead of editing this one.

The rule is today's (services/portfolio.py exclude_real_trading /
core/strategy_policy.outside_tester_book): real_trading -> My Holdings,
tester_paper -> testing book, everything else -> house. A row tied to a
position follows that position.
"""

from __future__ import annotations

from sqlalchemy import Connection, text

MONEY_TABLES = ("orders", "positions", "trades", "portfolio_snapshots", "risk_events", "brain_approvals")
_BOOK_FOR_STRATEGY = (
    "CASE s.name WHEN 'real_trading' THEN 'real' WHEN 'tester_paper' THEN 'tester' ELSE 'house' END"
)


def seed(conn: Connection) -> dict[str, int]:
    rows = (
        ("house", "House account", "paper", None),
        ("tester", "Testing book", "paper", "vijay"),
        ("real", "My Holdings", "live", "sudeeksha"),
    )
    for kind, name, mode, owner in rows:
        conn.execute(
            text(
                "INSERT INTO portfolios (kind, name, mode, owner_user_id) "
                "SELECT :k, :n, :m, (SELECT id FROM users WHERE username = :o) "
                "WHERE NOT EXISTS (SELECT 1 FROM portfolios WHERE kind = :k)"
            ),
            {"k": kind, "n": name, "m": mode, "o": owner},
        )
    return dict(conn.execute(text("SELECT kind, id FROM portfolios WHERE kind IN ('house','tester','real')")).all())


def _by_strategy(table: str) -> str:
    return (
        f"(SELECT p.id FROM strategies s JOIN portfolios p ON p.kind = {_BOOK_FOR_STRATEGY} "
        f"WHERE s.id = {table}.strategy_id)"
    )


_HOUSE = "(SELECT id FROM portfolios WHERE kind = 'house')"


def backfill(conn: Connection) -> dict[str, int]:
    statements = {
        "positions": f"UPDATE positions SET portfolio_id = COALESCE({_by_strategy('positions')}, {_HOUSE}) "
        "WHERE portfolio_id IS NULL",
        "orders": "UPDATE orders SET portfolio_id = COALESCE("
        "(SELECT pp.portfolio_id FROM positions pp WHERE pp.id = orders.position_id), "
        f"{_by_strategy('orders')}, {_HOUSE}) WHERE portfolio_id IS NULL",
        "trades": "UPDATE trades SET portfolio_id = COALESCE("
        "(SELECT pp.portfolio_id FROM positions pp WHERE pp.id = trades.position_id), "
        f"{_by_strategy('trades')}, {_HOUSE}) WHERE portfolio_id IS NULL",
        "risk_events": f"UPDATE risk_events SET portfolio_id = COALESCE({_by_strategy('risk_events')}, {_HOUSE}) "
        "WHERE portfolio_id IS NULL",
        "brain_approvals": "UPDATE brain_approvals SET portfolio_id = COALESCE("
        "(SELECT pp.portfolio_id FROM positions pp WHERE pp.id = brain_approvals.position_id), "
        f"{_by_strategy('brain_approvals')}, {_HOUSE}) WHERE portfolio_id IS NULL",
        "portfolio_snapshots": f"UPDATE portfolio_snapshots SET portfolio_id = {_HOUSE} WHERE portfolio_id IS NULL",
    }
    # positions first: orders/trades/approvals follow their position.
    return {table: conn.execute(text(sql)).rowcount for table, sql in statements.items()}


_LEGACY_POSITION_BOOK = (
    "(SELECT COALESCE((SELECT " + _BOOK_FOR_STRATEGY + " FROM strategies s WHERE s.id = pp.strategy_id), 'house') "
    "FROM positions pp WHERE pp.id = {table}.position_id)"
)


def _legacy_book(table: str, follows_position: bool) -> str:
    """The book today's code puts a row in, ignoring portfolio_id: its position's
    book first (orders, trades, approvals), then its strategy, then house — the
    exact rule backfill() applies, so before == after is a real check."""
    parts = []
    if follows_position:
        parts.append(_LEGACY_POSITION_BOOK.format(table=table))
    parts.append(f"(SELECT {_BOOK_FOR_STRATEGY} FROM strategies s WHERE s.id = {table}.strategy_id)")
    parts.append("'house'")
    return "COALESCE(" + ", ".join(parts) + ")"


_CENSUS_TABLES = {
    # table: (follows its position, has a mode column, money expression)
    "orders": (True, True, "0"),
    "positions": (False, True, "COALESCE(SUM(CASE WHEN status = 'OPEN' THEN entry_price * quantity + total_charges END), 0)"),
    "trades": (True, True, "COALESCE(SUM(net_pnl), 0)"),
    "risk_events": (False, True, "0"),
    "brain_approvals": (True, False, "0"),
}


def census(conn: Connection, *, legacy_only: bool = False) -> list[dict]:
    """Per table and book: row count, Σ trade net P&L, Σ open locked capital.
    A row's book is its portfolio's kind when it has one, else the legacy rule.
    `legacy_only=True` never touches portfolio_id, for a database that has no
    such column yet (the production copy before the migration)."""
    out: list[dict] = []
    for table, (follows_position, has_mode, money) in _CENSUS_TABLES.items():
        legacy = _legacy_book(table, follows_position)
        book = legacy if legacy_only else (
            f"COALESCE((SELECT p.kind FROM portfolios p WHERE p.id = {table}.portfolio_id), {legacy})"
        )
        mode = "mode" if has_mode else "'*'"
        is_trades, is_positions = table == "trades", table == "positions"
        q = (
            f"SELECT {book} AS b, {mode} AS m, COUNT(*), "
            f"{money if is_trades else '0'}, {money if is_positions else '0'} "
            f"FROM {table} GROUP BY b, m"
        )
        for b, m, rows, pnl, locked in conn.execute(text(q)).all():
            out.append({"table": table, "book": b, "mode": m, "rows": rows,
                        "sum_net_pnl": round(float(pnl), 2), "open_locked": round(float(locked), 2)})
    snaps = conn.execute(text("SELECT COUNT(*) FROM portfolio_snapshots")).scalar_one()
    out.append({"table": "portfolio_snapshots", "book": "house", "mode": "*", "rows": snaps,
                "sum_net_pnl": 0.0, "open_locked": 0.0})
    return sorted(out, key=lambda r: (r["table"], r["book"], r["mode"]))


def verify(conn: Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in MONEY_TABLES:
        nulls = conn.execute(text(f"SELECT COUNT(*) FROM {table} WHERE portfolio_id IS NULL")).scalar_one()
        if nulls:
            raise RuntimeError(f"{table}: {nulls} row(s) still have no portfolio")
        for kind, n in conn.execute(text(
            f"SELECT p.kind, COUNT(*) FROM {table} t JOIN portfolios p ON p.id = t.portfolio_id GROUP BY p.kind"
        )).all():
            counts[f"{table}.{kind}"] = n
    return counts
```

**Why the census follows the position:** the legacy view applies the exact `backfill` rule (position first, then strategy, then house). A row tied to a tester position with no strategy is therefore `tester` in both views, so `before == after` proves no money moved between books. Also add this test:

```python
def test_legacy_only_census_equals_census_on_unstamped_rows(db_session, books):
    conn = db_session.connection()
    assert pb.census(conn, legacy_only=True) == pb.census(conn)
```

- [ ] **Step 4: Call it from the migration.** At the end of `upgrade()`, replace the `# Task 2 …` comment with:

```python
    from swing_trade_ml.db import portfolio_backfill

    bind = op.get_bind()
    before = portfolio_backfill.census(bind, legacy_only=True)
    portfolio_backfill.seed(bind)
    portfolio_backfill.backfill(bind)
    after = portfolio_backfill.census(bind)
    if before != after:  # the same rows, the same money, now with an owner
        raise RuntimeError("B1 backfill changed the books' totals; aborting the migration")
    portfolio_backfill.verify(bind)
```

- [ ] **Step 5: CLI** (`cli.py`, next to `audit-roles`)

```python
def cmd_portfolios_check(args: argparse.Namespace) -> int:
    from swing_trade_ml.db import portfolio_backfill
    from swing_trade_ml.db.session import session_scope

    with session_scope() as db:
        conn = db.connection()
        for r in portfolio_backfill.census(conn):
            print(f"{r['table']:<20} {r['book']:<7} {r['mode']:<6} rows={r['rows']:<7} "
                  f"net_pnl={r['sum_net_pnl']:<14} open_locked={r['open_locked']}")
        try:
            portfolio_backfill.verify(conn)
            print("✅ Every money row has a portfolio.")
            return 0
        except RuntimeError as exc:
            print(f"❌ {exc}. Run: swingtrade portfolios-backfill")
            return 1


def cmd_portfolios_backfill(args: argparse.Namespace) -> int:
    from swing_trade_ml.db import portfolio_backfill
    from swing_trade_ml.db.session import session_scope

    with session_scope() as db:
        conn = db.connection()
        portfolio_backfill.seed(conn)
        updated = portfolio_backfill.backfill(conn)
        portfolio_backfill.verify(conn)
    print(f"✅ Filled rows with no portfolio: {updated}")
    return 0
```

```python
    sub.add_parser("portfolios-check", help="Show each book's rows and money; flag rows with no portfolio").set_defaults(func=cmd_portfolios_check)
    sub.add_parser("portfolios-backfill", help="Give rows with no portfolio one (only where empty)").set_defaults(func=cmd_portfolios_backfill)
```

- [ ] **Step 6: Run tests.** `… -m pytest tests/test_b1_backfill.py tests/test_b1_portfolio_model.py -v` → all pass. Then the full suite → green.

- [ ] **Step 7: Format and commit**

```bash
cd backend && <python> -m ruff format src/swing_trade_ml/db/portfolio_backfill.py tests/test_b1_backfill.py
cd .. && git add backend/src/swing_trade_ml/db/portfolio_backfill.py backend/alembic/versions/20261017_1000_b1_portfolios.py backend/src/swing_trade_ml/cli.py backend/tests/test_b1_backfill.py
git commit -m "B1: seed the three books and backfill every money row by today's rule; totals checked before and after

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Stamp new rows on insert (no trading code touched)

**Files:**
- Create: `backend/src/swing_trade_ml/db/portfolio_stamp.py`
- Modify: `backend/src/swing_trade_ml/db/models/__init__.py` (import `portfolio_stamp` so the listeners register whenever models load)
- Test: `backend/tests/test_b1_stamp.py`

**Interfaces:**
- Consumes: Task 1 models and the Task 2 rule.
- Produces: `before_insert` listeners on `Order`, `Position`, `Trade`, `PortfolioSnapshot`, `RiskEvent` and `BrainApproval`. When `portfolio_id` is None they set it with the same rule as `backfill`, querying through the flush's `connection`. An explicit `portfolio_id` is never changed. They never raise.
- Release C's member portfolios set `portfolio_id` explicitly, so this listener never routes a member row.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_b1_stamp.py
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from swing_trade_ml.db import portfolio_backfill as pb
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.portfolio import Portfolio
from swing_trade_ml.db.models.safety import RiskEvent
from swing_trade_ml.db.models.trading import Order, PortfolioSnapshot, Position, Strategy, Trade
from swing_trade_ml.services import tester_paper

NOW = datetime(2026, 10, 2, 10, 0, tzinfo=UTC)


@pytest.fixture()
def ids(db_session):
    db_session.execute(text("DELETE FROM portfolios WHERE kind IN ('house','tester','real')"))
    return pb.seed(db_session.connection())


def _pos(db, strategy_id, sym, mode="paper"):
    inst = Instrument(instrument_token=abs(hash(sym)) % 10_000_000, tradingsymbol=sym, exchange="NSE")
    db.add(inst)
    db.flush()
    p = Position(strategy_id=strategy_id, instrument_id=inst.id, mode=mode, status="OPEN",
                 quantity=1, initial_quantity=1, entry_price=10.0, entry_at=NOW)
    db.add(p)
    db.flush()
    return p


def test_position_by_strategy(db_session, ids):
    tester = tester_paper.get_or_create_strategy(db_session)
    real = Strategy(name="real_trading", strategy_type="real_trading", mode="live")
    house = Strategy(name="b1s_house", strategy_type="ml_swing", mode="paper")
    db_session.add_all([real, house])
    db_session.flush()
    assert _pos(db_session, tester.id, "S1").portfolio_id == ids["tester"]
    assert _pos(db_session, real.id, "S2", "live").portfolio_id == ids["real"]
    assert _pos(db_session, house.id, "S3").portfolio_id == ids["house"]
    assert _pos(db_session, None, "S4").portfolio_id == ids["house"]


def test_trade_and_order_follow_their_position(db_session, ids):
    tester = tester_paper.get_or_create_strategy(db_session)
    pos = _pos(db_session, tester.id, "S5")
    order = Order(instrument_id=pos.instrument_id, mode="paper", transaction_type="SELL", quantity=1,
                  placed_at=NOW, position_id=pos.id)  # no strategy
    trade = Trade(position_id=pos.id, instrument_id=pos.instrument_id, mode="paper", symbol="S5", quantity=1,
                  entry_price=10, exit_price=11, entry_at=NOW, exit_at=NOW, gross_pnl=1, charges=0,
                  net_pnl=1, return_pct=0.1, is_win=True)
    db_session.add_all([order, trade])
    db_session.flush()
    assert order.portfolio_id == ids["tester"] and trade.portfolio_id == ids["tester"]


def test_snapshot_and_risk_event(db_session, ids):
    snap = PortfolioSnapshot(mode="paper", ts=NOW, cash=1, holdings_value=1, total_value=2)
    ev = RiskEvent(mode="paper", rule="HALTED", reason="x")
    db_session.add_all([snap, ev])
    db_session.flush()
    assert snap.portfolio_id == ids["house"] and ev.portfolio_id == ids["house"]


def test_explicit_portfolio_is_kept(db_session, ids):
    member = Portfolio(kind="member", name="M", mode="paper")
    db_session.add(member)
    db_session.flush()
    order = Order(instrument_id=_pos(db_session, None, "S6").instrument_id, mode="paper",
                  transaction_type="BUY", quantity=1, placed_at=NOW, portfolio_id=member.id)
    db_session.add(order)
    db_session.flush()
    assert order.portfolio_id == member.id


def test_no_portfolios_yet_leaves_null_and_never_breaks_the_insert(db_session):
    db_session.execute(text("DELETE FROM portfolios"))
    pos = _pos(db_session, None, "S7")
    assert pos.id is not None and pos.portfolio_id is None
```

- [ ] **Step 2: Run to verify failure.** → FAIL (`portfolio_id` is None in the first tests).

- [ ] **Step 3: Implement `db/portfolio_stamp.py`**

```python
"""Give every new money row its portfolio as it is saved, with the same rule
as the B1 backfill — so no trading code had to change. A row that already
names a portfolio (release C members) is left alone. Never raises: a trade
must not fail because a label could not be worked out; such rows stay NULL
and `swingtrade portfolios-check` / `portfolios-backfill` find and fix them."""

from __future__ import annotations

from sqlalchemy import event, text

from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.brain_golive import BrainApproval
from swing_trade_ml.db.models.safety import RiskEvent
from swing_trade_ml.db.models.trading import Order, PortfolioSnapshot, Position, Trade

log = get_logger(__name__)

_BOOK_SQL = text(
    "SELECT p.id FROM strategies s JOIN portfolios p ON p.kind = "
    "CASE s.name WHEN 'real_trading' THEN 'real' WHEN 'tester_paper' THEN 'tester' ELSE 'house' END "
    "WHERE s.id = :s"
)
_HOUSE_SQL = text("SELECT id FROM portfolios WHERE kind = 'house'")
_POSITION_SQL = text("SELECT portfolio_id FROM positions WHERE id = :p")


def _resolve(conn, target) -> int | None:
    position_id = getattr(target, "position_id", None)
    if position_id is not None:
        found = conn.execute(_POSITION_SQL, {"p": position_id}).scalar()
        if found is not None:
            return found
    strategy_id = getattr(target, "strategy_id", None)
    if strategy_id is not None:
        found = conn.execute(_BOOK_SQL, {"s": strategy_id}).scalar()
        if found is not None:
            return found
    return conn.execute(_HOUSE_SQL).scalar()


def _stamp(_mapper, conn, target) -> None:
    if target.portfolio_id is not None:
        return
    try:
        target.portfolio_id = _resolve(conn, target)
    except Exception as exc:  # noqa: BLE001 — never break a trade over a label
        log.warning("portfolio.stamp_failed", table=type(target).__tablename__, error=str(exc))


for _model in (Order, Position, Trade, PortfolioSnapshot, RiskEvent, BrainApproval):
    event.listen(_model, "before_insert", _stamp)
```

**Database errors:** a failed `SELECT` inside a Postgres transaction aborts that transaction, so `try/except` cannot make a DB error harmless. The queries are simple reads on tables that exist after the migration, so this is acceptable. Say it in the report. Add `from swing_trade_ml.db import portfolio_stamp  # noqa: F401 — registers listeners` at the end of `db/models/__init__.py`, and check for import cycles (portfolio_stamp imports models; models/__init__ imports it last).

- [ ] **Step 4: Run tests.** `… -m pytest tests/test_b1_stamp.py tests/test_b1_backfill.py -v` → pass. Then the full suite → green. The full run proves that every existing trading test, including execution, exits and tester buys, still passes with the listeners active.

- [ ] **Step 5: Format and commit**

```bash
cd backend && <python> -m ruff format src/swing_trade_ml/db/portfolio_stamp.py tests/test_b1_stamp.py
cd .. && git add backend/src/swing_trade_ml/db/portfolio_stamp.py backend/src/swing_trade_ml/db/models/__init__.py backend/tests/test_b1_stamp.py
git commit -m "B1: new money rows are stamped with their portfolio on save; trading code untouched

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Rehearse on a copy of production; runbook

**Files:**
- Create: `backend/scripts/rehearse_b1_on_prod_copy.py`
- Create: `docs/deploy/B1-portfolios-runbook.md`

**Interfaces:** operational only.

- [ ] **Step 1: The owner makes the copy** (🔒 owner-run on the droplet; Claude cannot SSH). Put these instructions in the runbook first:

```bash
# on the droplet, in the app directory
docker compose exec -T postgres pg_dump -U swingtrade -Fc \
  --exclude-table-data=broker_sessions --exclude-table-data=login_codes \
  --exclude-table-data=audit_log swing_trade_ml > b1_rehearsal.dump
# copy b1_rehearsal.dump to D:\machine learning\swing-trade-bot\.local\b1_rehearsal.dump (git-ignored), then delete it from the droplet
```

(Kite tokens, one-time codes and the audit trail are left out. Users' bcrypt hashes are included because the owner-linking step needs user ids. The file stays on the owner's machine and is deleted after the rehearsal.) Check that `.local/` is git-ignored, and add it to `.gitignore` if not.

- [ ] **Step 2: Write the rehearsal script**

```python
# backend/scripts/rehearse_b1_on_prod_copy.py
"""Restore the owner's production copy into a scratch DB and run the B1 migration on it.

Usage: .venv/Scripts/python.exe scripts/rehearse_b1_on_prod_copy.py --dump ../.local/b1_rehearsal.dump
Creates and drops swing_trade_ml_b1_rehearsal on localhost:5433. Never touches any other database.
"""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

NAME = "swing_trade_ml_b1_rehearsal"
assert NAME.endswith("_rehearsal")
SERVER = "postgresql+psycopg://swingtrade:swingtrade_local_pw@localhost:5433"
URL = f"{SERVER}/{NAME}"
os.environ["DATABASE_URL"] = URL  # before any app import; overrides the shell on purpose

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402


def _cfg() -> Config:
    backend = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "alembic"))
    cfg.set_main_option("sqlalchemy.url", URL)
    return cfg


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", required=True)
    dump = Path(ap.parse_args().dump).resolve()
    admin = create_engine(f"{SERVER}/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f"DROP DATABASE IF EXISTS {NAME}"))
        c.execute(text(f"CREATE DATABASE {NAME}"))
    subprocess.run(["docker", "cp", str(dump), "stml-postgres:/tmp/b1.dump"], check=True)
    subprocess.run(["docker", "exec", "stml-postgres", "pg_restore", "-U", "swingtrade", "-d", NAME,
                    "--no-owner", "/tmp/b1.dump"], check=False)  # extension notices are expected
    subprocess.run(["docker", "exec", "stml-postgres", "rm", "-f", "/tmp/b1.dump"], check=True)

    eng = create_engine(URL)
    from swing_trade_ml.db import portfolio_backfill as pb

    with eng.connect() as c:
        head = c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        print("prod copy at revision", head)
        before = pb.census(c, legacy_only=True)  # no portfolio_id column yet
    command.upgrade(_cfg(), "f2b1p0r7f0l1")  # P0 (if not yet applied) then B1
    with eng.connect() as c:
        after = pb.census(c)
        counts = pb.verify(c)
        owners = c.execute(text(
            "SELECT p.kind, u.username FROM portfolios p LEFT JOIN users u ON u.id = p.owner_user_id ORDER BY p.kind"
        )).all()
    print("\nCENSUS (book = legacy rule before, portfolio after):")
    for r in after:
        print(f"  {r['table']:<20} {r['book']:<7} {r['mode']:<6} rows={r['rows']:<7} "
              f"net_pnl={r['sum_net_pnl']:<14} open_locked={r['open_locked']}")
    assert before == after, "totals moved — STOP"
    print("\nportfolio owners:", owners)
    print("rows per portfolio:", counts)
    command.downgrade(_cfg(), "e1p0s2e3c4u5")
    with eng.connect() as c:
        assert pb.census(c, legacy_only=True) == before, "downgrade changed the books — STOP"
    command.upgrade(_cfg(), "f2b1p0r7f0l1")
    print("\n✅ B1 on the production copy: totals identical, no rows without a portfolio, downgrade and re-upgrade clean")
    eng.dispose()
    with admin.connect() as c:
        c.execute(text(f"DROP DATABASE {NAME}"))
    print(f"Scratch DB {NAME} dropped. Now delete {dump}.")


if __name__ == "__main__":
    main()
```

The prod copy may be at P0 (`e1p0s2e3c4u5`) or still at `d8a1y2c3h4k5` if P0 is not deployed yet. `upgrade` runs whatever is missing. The "before" census uses `legacy_only=True`, because the copy has no `portfolio_id` column yet.

- [ ] **Step 3: Run it** once the owner has provided the dump: `cd backend && <python> scripts/rehearse_b1_on_prod_copy.py --dump ../.local/b1_rehearsal.dump`. Expected: the ✅ line. Paste the census table (counts and totals only, no names or symbols) into the runbook evidence section. **If no dump has been provided yet, stop here and report DONE_WITH_CONCERNS. This rehearsal is a merge gate.**

- [ ] **Step 4: Old code on the new schema.** As in P0 Task 11 Step 3: start `develop` from before B1, in a temporary `git worktree add --detach`, against a scratch DB upgraded to `f2b1p0r7f0l1` (re-run the script without its final drop, or use a second scratch DB). Check that `/health` is ok, a login works, and a paper position can be opened through the old code path (`swingtrade` CLI or a pytest against that DB). Then confirm `portfolios-check` on the new code reports the old code's new row as NULL and `portfolios-backfill` fixes it. Record the evidence, remove the worktree, stop the server and drop the DB.

- [ ] **Step 5: Write `docs/deploy/B1-portfolios-runbook.md`** with these sections:
  - **Before deploy:**
    - P0 is live and stable.
    - The prod-copy rehearsal printed ✅ (evidence pasted).
    - Full suite green.
    - 🔒 Database backup (`pg_dump`, full) taken and named.
  - **Deploy:**
    - 🔒 The owner merges to `main`.
    - Watch the startup log for the migration.
    - `docker compose exec api swingtrade portfolios-check` → ✅, with census totals matching the rehearsal's shape.
    - `/api/v1/status` unchanged.
    - The house account's figures on the TradeMind Home and Portfolio screens are identical to just before the deploy (write them down first).
  - **One clean day later:**
    - `portfolios-check` → ✅ again (new rows were stamped).
    - Only then does B2 make `portfolio_id` required.
  - **Rollback:**
    - Code: revert the merge. The old code ignores the new column and table (rehearsed in Step 4).
    - Rows it creates meanwhile have NULL `portfolio_id`; after rolling forward, run `portfolios-backfill`.
    - Schema (only if needed): `alembic downgrade e1p0s2e3c4u5`. It drops the column and table and changes no other data (rehearsed).
  - **Acceptance:**
    - Every money row has a portfolio.
    - The census totals are identical before and after.
    - Trading behaviour and every screen are unchanged.
    - Vijay's testing book and My Holdings each sit in their own portfolio, with owners `vijay` and `sudeeksha`.

- [ ] **Step 6: Commit** `backend/scripts/rehearse_b1_on_prod_copy.py`, `docs/deploy/B1-portfolios-runbook.md` (and `.gitignore` if changed) with message `B1: production-copy rehearsal and deploy runbook` plus the trailer. **Never commit the dump.**

---

## What B2 covers (separate plan, written after B1 is reviewed)

B2 changes behaviour and is trading-sensitive, so it gets its own plan, tests and owner approval:
- Migration: `portfolio_id NOT NULL`. Add `cash_ledger_entries`, `portfolio_decisions`, and `orders.client_order_id` with a unique key per portfolio.
- `services/scope.py` `PortfolioScope`. `scope_for(principal, portfolio_id)` fails closed: a member never falls back to the house.
- Thread the scope through `brokers/paper.py`, `services/risk.py`, `services/execution.py` and `services/portfolio.py`, replacing the strategy-name filters (`outside_tester_book`, `exclude_real_trading`, `only_tester`) with portfolio filters. The house path gives identical numbers (golden test). This fixes F-T1: the tester buy checks the tester's own cash.
- `services/portfolio_executor.py`: lock → check → reserve → fill → ledger → commit, idempotent by `client_order_id`. Used by member orders (release C) and tested for concurrency now.
- API scoping of every money route, plus an isolation walk over every route, report and export.
- `ledger_check` nightly job, and per-portfolio snapshots.
