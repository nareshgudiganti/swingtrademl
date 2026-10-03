# M18 Shadow Run and Go-Live Switch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect the brain to version 1 in three owner-controlled stages: (1) shadow, where the brain runs as an advisory strategy next to v1, both are scored the same way and compared on the same days; (2) approval, where each brain BUY waits for the owner's Approve before v1 execution places it; (3) automatic, which is only an owner switch with a one-step rollback.

**Architecture:** A `BrainStrategy` (`strategies/brain.py`, `strategy_type="brain"`) reads today's stored live nightly brain decisions and returns ordinary `SignalDecision`s. The `"brain"` type is a *staged* type in `core/strategy_policy.py`: the scan path always treats it as advisory, so it records and scores signals and never orders. A small package `services/brain_golive/` (outside the `brain` package, constitution C10) runs the strategy right after the nightly brain run (`shadow.py`), builds the brain-vs-v1 comparison from Signal outcomes (`compare.py`), holds the owner's stage switch with an audit row per change (`stage.py`), and owns the approvals (`approvals.py`), which is the ONLY place an order is ever placed for the brain, through `services.execution.open_position`. A new router `api/v1/endpoints/brain_golive.py` and a console component `frontend/src/components/BrainGoLive.tsx` expose it.

**Tech Stack:** Python 3.12, SQLAlchemy 2, Alembic, FastAPI, pytest; React + TanStack Query (TypeScript).

**Spec:** `docs/superpowers/specs/2026-09-29-trademind-brain-build-book.html` (in the main checkout `D:/machine learning/swing-trade-bot/docs/superpowers/specs/`), module sheet "M18 Shadow run and go-live switch", plus principles P6/P7 and constitution rule C10. Research on the v1 execution path: `.superpowers/sdd/2026-10-03-trademind-live-data/m18-research.md`. Running notes: `docs/brain/BUILD_NOTES.md`.

## Global Constraints

- Work ONLY in the worktree `D:/machine learning/swing-trade-bot/.claude/worktrees/brain-m00`. Before Task 1, create the branch from the integration branch: `git switch -c brain/m18-golive brain/integration` (the worktree is clean; the backend on `brain/integration` is identical to `brain/trademind-live`). Never push. Never touch `main`. Never use `git stash` (the stash stack is shared with other sessions).
- **Stage 1 shadow** = the brain strategy row runs with `execution_mode="advisory"` (the never-orders path: `services/execution.py` `if is_advisory(strategy)` before `open_position`, around line 933). `core/strategy_policy.py` makes `"brain"` always advisory in the scan path (`requires_advisory("brain") is True`), so nobody can PATCH it to `"auto"` by accident.
- `BrainStrategy.evaluate()` reads ONLY today's (IST date) latest **live nightly** brain run (`kind=="nightly"`, `live`, `status=="done"`, `book == strategy.mode`). Stale or missing run → HOLD "No brain run today…". Effective word = `overruled_word or word`. Only `kind=="idea"` with effective word `TRADE` → BUY with `stop_loss=stop`, `take_profit=target`, `horizon_days=horizon_days`; everything else → HOLD with the brain's first reason (the owner's overrule reason when overruled). Brain `qty` is informational only (stored in `features`); v1 risk sizes. `min_bars_required()` returns 1.
- Brain signals are scored by the existing `ml/predict.py::evaluate_pending_signals` (needs `stop_loss`, `take_profit`, `horizon_days` set). No new scorer.
- **Comparison:** `GET /brain/compare` — brain strategy vs the v1 strategies on the same days (IST days on which the brain strategy produced any signal), from Signal outcomes: ideas, finished, reached-target share (hit rate), hit-the-stop share, average outcome %, by strategy and by ISO week. Long-term-value signals are excluded (different horizon). One idea per (strategy, stock, IST day): the latest signal wins.
- **Stage 2 approval:** one pending approval record per brain BUY signal that passed v1's safety check (`advisory_only` and no `rejection_reason`), at most one per stock per IST day. Console Approve / Reject. Telegram gets a plain message with a link to `{FRONTEND_URL}/brain#approvals` — NO Telegram webhook or inline buttons. Approve re-checks freshness — same IST day as the idea, the brain still says TRADE for that stock today, no open brain position in that stock, the strategy is active and its mode equals the broker's mode, `risk.check_entry` passes NOW — and only then calls `services.execution.open_position` for that signal with v1's quantity. Reject records who and why (a reason is required).
- Leaving shadow (to `approval` or `auto`) is refused until at least **30** brain ideas have a resolved Signal outcome (one per stock per day); show "N of 30" everywhere it matters.
- **Stage 3 auto** = only an owner switch (allowed only from `approval`, same 30 gate) under which the system presses Approve through the exact same `approve()` checks. Rollback = one switch back to `shadow` (always allowed; pending approvals expire). Nothing in code may change the stage except `services/brain_golive/stage.py::set_stage`, reached only through the owner endpoint `PUT /brain/stage`. Every change writes an audit row (stage, previous stage, by, why, when). Default with no rows = `shadow`.
- M18 is the only module allowed to touch the execution path, and only through the strategy interface, `services.execution.open_position` and the v1 exit loop. Never call a broker directly. The `swing_trade_ml.brain` package must still never import `swing_trade_ml.brokers` or `swing_trade_ml.services.execution` (`tests/test_brain_service.py::test_brain_package_never_imports_order_placement`) — that is why all M18 code lives in `strategies/brain.py` and `services/brain_golive/`.
- Positions opened through an approval are protected by v1's own exits (stop, target, time stop, half out at +5%): `exits_are_advisory()` is False for the staged type. Rollback to shadow does NOT sell them.
- Version 1 must behave exactly as before while the brain row is active: the 15:45 scan (`engine.run_all_active`) skips staged strategies, `risk.active_strategy_count` does not count them (v1's slot share unchanged, P6), and the brain's practice ideas are never sent as "RECOMMENDATION" Telegram messages.
- **Tests never place a real or paper broker order.** DB tests that reach `services.execution` call `no_broker(monkeypatch)` (fake broker whose `place_order` raises), and approval tests replace `approvals.open_position` with a recorder. Required tests: a shadow BrainStrategy signal never creates an `Order` row; Stage 2 never orders without an approval.
- Migrations continue the brain chain: current head is `b4e7a1c9d352` (`20261003_1200_brain_learning_runs.py`). Confirm with `"D:/machine learning/swing-trade-bot/backend/.venv/Scripts/python.exe" -m alembic heads` (from `backend/`) before Task 6; if the head differs, chain onto the real head.
- IST: a signal's or run's day is always `ts.astimezone(ZoneInfo("Asia/Kolkata")).date()`; daily candles are stamped IST midnight (18:30 UTC the day before). Day bounds come from `strategies/brain.py::ist_day_bounds`.
- Plain English in every user-facing string (the owner has no finance background). No promise words.
- Tests: run with `cd backend && env -u API_KEY -u DATABASE_URL -u JWT_SECRET_KEY -u TRADING_MODE "D:/machine learning/swing-trade-bot/backend/.venv/Scripts/python.exe" -m pytest -q <files>`. DB tests need Docker Postgres on :5433 (a port check is not a liveness check: if a DB test hangs ~4 minutes, Postgres is down). New tables are created automatically by the test setup (`create_all`); new columns on existing tables are not (none in this plan).
- Lint/format ONLY files you create: `"D:/machine learning/swing-trade-bot/backend/.venv/Scripts/python.exe" -m ruff format <paths>` and `ruff check <paths>`. NEVER run `ruff format` on `src/swing_trade_ml` as a whole (it rewrites 50+ unrelated v1 files), and never `ruff format` a v1 file you only edited (`execution.py`, `engine.py`, `risk.py`, `strategy_policy.py`, `jobs.py`, `cli.py`, `router.py`, `db/models/__init__.py`, `strategies/__init__.py`) — run `ruff check` on it before your edit and after; no new findings. Never run prettier on existing frontend files (no repo config); match file style by hand (single quotes, no semicolons, 2-space indent); check with `npx tsc --noEmit -p .` in `frontend/`.
- Shared test helpers live in `backend/tests/brain_m18_fixtures.py` (imported as `from brain_m18_fixtures import ...`, like `brain_fakes`). Test files are named `test_brain_m18_*.py` so the autouse fixture turns `BRAIN_ENABLED` on.
- Commit after each green task with a message ending `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. The owner overrules a TRADE to WATCH after the evening scan and then presses Approve on that idea → nothing is bought and the approval is marked expired with the brain's new word — Task 7 `test_an_idea_the_owner_overruled_after_the_scan_cannot_be_approved`.
2. Approve is tapped twice (double click, two tabs) → exactly one order — Task 7 `test_approving_twice_orders_once`.
3. Turning the brain strategy on must not change version 1: the 15:45 scan skips it and v1's slot share is unchanged — Task 2 `test_the_daily_scan_never_runs_the_brain_strategy`, `test_an_active_brain_strategy_does_not_shrink_version_1s_slot_share`.
4. The shadow scan is run twice in one day (CLI after the job) → one idea per stock per day in the comparison, and only one approval per stock per day — Task 4 `test_one_idea_per_stock_per_day`, Task 7 `test_a_rerun_scan_does_not_create_a_second_approval_for_the_same_stock`.
5. The safety switch is on (or cash ran out) when the owner presses Approve → nothing is bought, the idea stays pending and the reason is shown — Task 7 `test_when_the_safety_check_says_no_nothing_is_bought_and_it_stays_pending`.

## File Structure

| File | Responsibility |
|---|---|
| `backend/src/swing_trade_ml/strategies/brain.py` (new) | `BrainStrategy`; reading today's run/decisions; mapping a decision to a `SignalDecision`; IST helpers |
| `backend/src/swing_trade_ml/core/strategy_policy.py` | staged type `"brain"`: always advisory in the scan path, orderable by approvals, real exits |
| `backend/src/swing_trade_ml/services/engine.py`, `services/risk.py`, `services/execution.py` | three one-line guards (skip in 15:45 scan, not counted for slot share, no recommendation message, real exits) |
| `backend/src/swing_trade_ml/services/brain_golive/shadow.py` (new) | create the brain strategy row; run it after the nightly brain run |
| `backend/src/swing_trade_ml/services/brain_golive/compare.py` (new) | brain vs v1 comparison (pure + loader); finished-idea count for the gate |
| `backend/src/swing_trade_ml/services/brain_golive/stage.py` (new) | owner stage switch + audit + gate |
| `backend/src/swing_trade_ml/services/brain_golive/approvals.py` (new) | pending approvals, Approve/Reject, auto stage, Telegram link |
| `backend/src/swing_trade_ml/db/models/brain_golive.py` (new) | `BrainStageChange`, `BrainApproval` |
| `backend/src/swing_trade_ml/api/v1/endpoints/brain_golive.py` (new) | `/brain/compare`, `/brain/stage`, `/brain/approvals…` |
| `backend/src/swing_trade_ml/workers/jobs.py`, `cli.py` | run after nightly; `brain strategy-create`, `brain shadow-scan` |
| `frontend/src/components/BrainGoLive.tsx` (new) | console cards: comparison, stage, approvals |
| `docs/brain/GO_LIVE.md` (new) | stages, switching, rollback |

---

### Task 1: BrainStrategy reads today's stored decision

**Files:**
- Create: `backend/src/swing_trade_ml/strategies/brain.py`
- Modify: `backend/src/swing_trade_ml/strategies/__init__.py` (import `BrainStrategy`, add to `__all__`)
- Create: `backend/tests/brain_m18_fixtures.py`
- Test: `backend/tests/test_brain_m18_strategy.py`

**Interfaces:**
- Consumes: `BrainRun`, `BrainDecision` (`db/models/brain.py`), `BaseStrategy`, `SignalDecision`, `register_strategy` (`strategies/base.py`).
- Produces (later tasks rely on these exact names):
```python
IST: ZoneInfo                       # Asia/Kolkata
NO_RUN_TODAY: str                   # "No brain run today — the brain has not looked at the market yet today."
NOT_LOOKED_AT: str                  # "The brain did not look at this stock today."
NO_LEVELS: str
def today_ist() -> date
def ist_day_bounds(day: date) -> tuple[datetime, datetime]          # [IST midnight, next IST midnight)
def todays_run(db: Session, today: date, book: str) -> BrainRun | None
def todays_decisions(db: Session, today: date, book: str) -> tuple[BrainRun | None, dict[str, BrainDecision]]
    # symbol -> decision; an "idea" row wins over a "holding" row for the same symbol
def effective_word(d: BrainDecision) -> str                         # overruled_word or word
def why(d: BrainDecision) -> str                                    # plain reason line
def to_signal(d: BrainDecision | None, run: BrainRun | None, price: float) -> SignalDecision
class BrainStrategy(BaseStrategy): strategy_type = "brain"
```

- [ ] **Step 1: Create the shared fixtures file** `backend/tests/brain_m18_fixtures.py`:

```python
"""Shared rows for the M18 go-live tests. Nothing here can reach a broker:
`no_broker` makes any order attempt fail the test loudly."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from swing_trade_ml.core.enums import SignalType
from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.trading import Signal, Strategy

IST = ZoneInfo("Asia/Kolkata")
DAY = date(2031, 1, 6)  # a Monday far from any real stored run


def at(day: date, hh: int = 15, mm: int = 55) -> datetime:
    return datetime.combine(day, time(hh, mm), tzinfo=IST).astimezone(UTC)


def instrument(db, symbol: str, token: int) -> Instrument:
    inst = Instrument(
        instrument_token=token, tradingsymbol=symbol, exchange="NSE", is_watchlisted=True, is_active=True
    )
    db.add(inst)
    db.flush()
    return inst


def candle(db, inst: Instrument, day: date, close: float, high: float | None = None, low: float | None = None) -> None:
    db.add(
        Candle(
            instrument_id=inst.id,
            interval="day",
            ts=datetime.combine(day, time(0, 0), tzinfo=IST).astimezone(UTC),
            open=close,
            high=high if high is not None else close * 1.01,
            low=low if low is not None else close * 0.99,
            close=close,
            volume=100_000,
        )
    )
    db.flush()


def brain_strategy(db, name: str = "m18-brain", symbols: list[str] | None = None) -> Strategy:
    s = Strategy(
        name=name, strategy_type="brain", execution_mode="advisory", mode="paper",
        is_active=True, symbols=symbols or [], params={},
    )
    db.add(s)
    db.flush()
    return s


def v1_strategy(db, name: str = "m18-v1", strategy_type: str = "ml_swing", execution_mode: str = "auto") -> Strategy:
    s = Strategy(
        name=name, strategy_type=strategy_type, execution_mode=execution_mode, mode="paper",
        is_active=True, symbols=[], params={},
    )
    db.add(s)
    db.flush()
    return s


def run(db, run_id: str, day: date = DAY, *, kind: str = "nightly", live: bool = True,
        status: str = "done", book: str = "paper", hh: int = 15, mm: int = 50) -> BrainRun:
    r = BrainRun(id=run_id, kind=kind, as_of=at(day, hh, mm), book=book, live=live,
                 started_at=at(day, hh, mm), status=status)
    db.add(r)
    db.flush()
    return r


def decision(db, run_id: str, symbol: str, word: str = "TRADE", *, kind: str = "idea",
             stop: float | None = 96.0, target: float | None = 108.0, qty: int = 7,
             confidence: float | None = 0.62, reasons=("Strong trend with room to the target.",),
             overruled_word: str | None = None, overrule_reason: str | None = None) -> BrainDecision:
    d = BrainDecision(
        run_id=run_id, symbol=symbol, kind=kind, word=word, stop=stop, target=target, qty=qty,
        horizon_days=15, confidence=confidence, reasons=list(reasons),
        overruled_word=overruled_word, overrule_reason=overrule_reason,
    )
    db.add(d)
    db.flush()
    return d


def signal(db, strategy: Strategy, inst: Instrument, day: date = DAY, *, signal_type: str = SignalType.BUY,
           outcome: str | None = None, outcome_pct: float | None = None, advisory_only: bool = True,
           rejection_reason: str | None = None, hh: int = 15, mm: int = 55, price: float = 100.0) -> Signal:
    s = Signal(
        strategy_id=strategy.id, instrument_id=inst.id, signal_type=signal_type, mode="paper", price=price,
        confidence=0.6, suggested_quantity=12, stop_loss=96.0, take_profit=108.0, horizon_days=15, reason="r",
        features={}, advisory_only=advisory_only, rejection_reason=rejection_reason, outcome=outcome,
        outcome_pct=outcome_pct, generated_at=at(day, hh, mm),
    )
    db.add(s)
    db.flush()
    return s


def no_broker(monkeypatch) -> SimpleNamespace:
    """Any attempt to place an order through services.execution fails the test."""
    from swing_trade_ml.services import execution

    def boom(*args, **kwargs):
        raise AssertionError("a broker order was attempted")

    fake = SimpleNamespace(mode="paper", place_order=boom, get_ltp=lambda keys, db: {})
    monkeypatch.setattr(execution, "get_broker", lambda: fake)
    return fake
```

- [ ] **Step 2: Write the failing tests** `backend/tests/test_brain_m18_strategy.py`:

```python
"""M18 task 1: the brain as a version-1 strategy reads today's stored decision."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import pytest
from brain_m18_fixtures import DAY, brain_strategy, decision, instrument, run

from swing_trade_ml.core.enums import SignalType
from swing_trade_ml.strategies import STRATEGY_REGISTRY, get_strategy
from swing_trade_ml.strategies import brain as brain_mod

DF = pd.DataFrame({"ts": [pd.Timestamp("2031-01-06")], "close": [101.0]})


@pytest.fixture()
def today(monkeypatch):
    monkeypatch.setattr(brain_mod, "today_ist", lambda: DAY)
    return DAY


def _evaluate(db, inst):
    return get_strategy(brain_strategy(db)).evaluate(DF, inst, db)


def test_brain_is_a_registered_strategy_that_needs_almost_no_history(db_session):
    assert STRATEGY_REGISTRY["brain"] is brain_mod.BrainStrategy
    assert get_strategy(brain_strategy(db_session)).min_bars_required() <= 5


def test_a_trade_idea_becomes_a_buy_with_the_brains_levels(db_session, today):
    inst = instrument(db_session, "M18AAA", 918001)
    run(db_session, "m18-r1")
    decision(db_session, "m18-r1", "M18AAA", "TRADE")
    d = _evaluate(db_session, inst)
    assert d.signal == SignalType.BUY
    assert (d.price, d.stop_loss, d.take_profit, d.horizon_days) == (101.0, 96.0, 108.0, 15)
    assert d.confidence == 0.62
    assert d.reason == "Strong trend with room to the target."
    assert d.features["brain_qty"] == 7  # informational only: v1 risk sizes the order


@pytest.mark.parametrize("word", ["TRADE", "WATCH", "WAIT", "AVOID"])
def test_the_strategy_returns_the_same_word_as_the_stored_decision(db_session, today, word):
    inst = instrument(db_session, "M18AAB", 918002)
    run(db_session, "m18-r2")
    decision(db_session, "m18-r2", "M18AAB", word, reasons=(f"Because {word}.",))
    d = _evaluate(db_session, inst)
    assert d.features["brain_word"] == word
    assert d.signal == (SignalType.BUY if word == "TRADE" else SignalType.HOLD)
    if word != "TRADE":
        assert d.reason == f"Because {word}."
        assert d.stop_loss is None and d.take_profit is None


def test_the_owners_overrule_wins(db_session, today):
    inst = instrument(db_session, "M18AAC", 918003)
    run(db_session, "m18-r3")
    decision(db_session, "m18-r3", "M18AAC", "TRADE", overruled_word="WATCH", overrule_reason="Results next week")
    d = _evaluate(db_session, inst)
    assert d.signal == SignalType.HOLD
    assert d.features["brain_word"] == "WATCH"
    assert "Results next week" in d.reason


def test_an_idea_row_wins_over_a_holding_row_for_the_same_stock(db_session, today):
    inst = instrument(db_session, "M18AAD", 918004)
    run(db_session, "m18-r4")
    decision(db_session, "m18-r4", "M18AAD", "HOLD", kind="holding")
    decision(db_session, "m18-r4", "M18AAD", "TRADE")
    assert _evaluate(db_session, inst).signal == SignalType.BUY


def test_yesterdays_run_is_stale(db_session, today):
    inst = instrument(db_session, "M18AAE", 918005)
    run(db_session, "m18-r5", DAY - timedelta(days=1))
    decision(db_session, "m18-r5", "M18AAE", "TRADE")
    d = _evaluate(db_session, inst)
    assert (d.signal, d.reason) == (SignalType.HOLD, brain_mod.NO_RUN_TODAY)


@pytest.mark.parametrize(
    "kind,live,status,book",
    [
        ("nightly", False, "done", "paper"),   # a replay
        ("intraday", True, "done", "paper"),
        ("why", True, "done", "paper"),
        ("nightly", True, "failed", "paper"),
        ("nightly", True, "done", "live"),     # another book
    ],
)
def test_only_a_finished_live_nightly_run_of_the_same_book_counts(db_session, today, kind, live, status, book):
    inst = instrument(db_session, "M18AAF", 918006)
    run_id = f"m18-r6-{kind}-{live}-{status}-{book}"
    run(db_session, run_id, kind=kind, live=live, status=status, book=book)
    decision(db_session, run_id, "M18AAF", "TRADE")
    assert _evaluate(db_session, inst).reason == brain_mod.NO_RUN_TODAY


def test_the_latest_nightly_run_of_the_day_wins(db_session, today):
    inst = instrument(db_session, "M18AAG", 918007)
    run(db_session, "m18-r7a", hh=15, mm=50)
    decision(db_session, "m18-r7a", "M18AAG", "TRADE")
    run(db_session, "m18-r7b", hh=18, mm=0)
    decision(db_session, "m18-r7b", "M18AAG", "WAIT", reasons=("Market turned careful.",))
    d = _evaluate(db_session, inst)
    assert d.signal == SignalType.HOLD and d.features["brain_run_id"] == "m18-r7b"


def test_a_stock_the_brain_did_not_look_at_is_held(db_session, today):
    inst = instrument(db_session, "M18AAH", 918008)
    run(db_session, "m18-r8")
    assert _evaluate(db_session, inst).reason == brain_mod.NOT_LOOKED_AT


def test_a_trade_without_stop_or_target_is_held(db_session, today):
    inst = instrument(db_session, "M18AAI", 918009)
    run(db_session, "m18-r9")
    decision(db_session, "m18-r9", "M18AAI", "TRADE", stop=None)
    d = _evaluate(db_session, inst)
    assert (d.signal, d.reason) == (SignalType.HOLD, brain_mod.NO_LEVELS)


def test_decisions_are_read_once_per_scan(db_session, today, monkeypatch):
    calls = []
    real = brain_mod.todays_decisions
    monkeypatch.setattr(brain_mod, "todays_decisions", lambda *a: calls.append(a) or real(*a))
    impl = get_strategy(brain_strategy(db_session))
    a = instrument(db_session, "M18AAJ", 918010)
    b = instrument(db_session, "M18AAK", 918011)
    run(db_session, "m18-r10")
    impl.evaluate(DF, a, db_session)
    impl.evaluate(DF, b, db_session)
    assert len(calls) == 1
```

- [ ] **Step 3: Run to verify failure**

Run: `cd backend && env -u API_KEY -u DATABASE_URL -u JWT_SECRET_KEY -u TRADING_MODE "D:/machine learning/swing-trade-bot/backend/.venv/Scripts/python.exe" -m pytest -q tests/test_brain_m18_strategy.py`
Expected: FAIL — `ImportError: cannot import name 'brain' from 'swing_trade_ml.strategies'`.

- [ ] **Step 4: Implement** `backend/src/swing_trade_ml/strategies/brain.py`:

```python
"""The TradeMind brain as a version-1 strategy (build book M18).

It does no thinking of its own: for each stock it reads what today's live
nightly brain run already decided and hands that to version 1 as a signal.
"brain" is a staged type (core/strategy_policy.py): the scan path always
treats it as advisory, so it records and scores its ideas and never places
an order. Orders happen only in services/brain_golive/approvals.py after the
owner's OK. Brain tables are read through the models only — this module never
imports the brain package (that package must stay free of execution, C10).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.core.enums import SignalType
from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.strategies.base import BaseStrategy, SignalDecision, register_strategy

IST = ZoneInfo("Asia/Kolkata")
NO_RUN_TODAY = "No brain run today — the brain has not looked at the market yet today."
NOT_LOOKED_AT = "The brain did not look at this stock today."
NO_LEVELS = "The brain's idea has no stop or target, so it cannot be tracked."


def today_ist() -> date:
    return datetime.now(UTC).astimezone(IST).date()


def ist_day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time(0, 0), tzinfo=IST)
    return start, start + timedelta(days=1)


def todays_run(db: Session, today: date, book: str) -> BrainRun | None:
    """The latest finished live nightly run made on `today` (IST) for `book`.
    Replays, why-runs, intraday runs and failed runs never count."""
    start, end = ist_day_bounds(today)
    return db.execute(
        select(BrainRun)
        .where(
            BrainRun.kind == "nightly",
            BrainRun.live.is_(True),
            BrainRun.status == "done",
            BrainRun.book == book,
            BrainRun.as_of >= start,
            BrainRun.as_of < end,
        )
        .order_by(BrainRun.started_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def todays_decisions(db: Session, today: date, book: str) -> tuple[BrainRun | None, dict[str, BrainDecision]]:
    run = todays_run(db, today, book)
    if run is None:
        return None, {}
    by_symbol: dict[str, BrainDecision] = {}
    for d in db.execute(select(BrainDecision).where(BrainDecision.run_id == run.id)).scalars():
        current = by_symbol.get(d.symbol)
        if current is None or (d.kind == "idea" and current.kind != "idea"):
            by_symbol[d.symbol] = d
    return run, by_symbol


def effective_word(d: BrainDecision) -> str:
    """The owner's overrule (always more careful) wins over the brain's own word."""
    return d.overruled_word or d.word


def why(d: BrainDecision) -> str:
    if d.overruled_word:
        return f"You overruled the brain to {d.overruled_word}: {d.overrule_reason or 'no reason given'}"
    if d.reasons:
        return str(d.reasons[0])
    return d.evidence_text or f"The brain says {d.word}."


def to_signal(d: BrainDecision | None, run: BrainRun | None, price: float) -> SignalDecision:
    if run is None:
        return SignalDecision(SignalType.HOLD, price, reason=NO_RUN_TODAY)
    if d is None:
        return SignalDecision(SignalType.HOLD, price, reason=NOT_LOOKED_AT, features={"brain_run_id": run.id})
    word = effective_word(d)
    features: dict[str, Any] = {
        "brain_run_id": run.id,
        "brain_decision_id": d.id,
        "brain_word": word,
        "brain_qty": d.qty,  # informational only: version 1's risk service sizes the order
        "brain_entry_low": d.entry_low,
        "brain_entry_high": d.entry_high,
    }
    if d.kind == "idea" and word == "TRADE":
        if d.stop is None or d.target is None:
            return SignalDecision(SignalType.HOLD, price, reason=NO_LEVELS, features=features)
        return SignalDecision(
            SignalType.BUY,
            price,
            d.confidence,
            why(d),
            stop_loss=float(d.stop),
            take_profit=float(d.target),
            horizon_days=int(d.horizon_days),
            features=features,
        )
    # No confidence on a HOLD: the brain's number is not always a probability
    # (BrainDecision.score_source), and v1's decay alert must not read it as one.
    return SignalDecision(SignalType.HOLD, price, reason=why(d), features=features)


@register_strategy
class BrainStrategy(BaseStrategy):
    strategy_type: ClassVar[str] = "brain"
    display_name: ClassVar[str] = "TradeMind brain"
    description: ClassVar[str] = (
        "The TradeMind brain's ideas, recorded and scored next to version 1. "
        "It never buys on its own: the owner chooses the stage on the Brain page."
    )
    default_params: ClassVar[dict[str, Any]] = {}

    def __init__(self, config) -> None:
        super().__init__(config)
        self._loaded_for: date | None = None
        self._run: BrainRun | None = None
        self._decisions: dict[str, BrainDecision] = {}

    def min_bars_required(self) -> int:
        return 1  # it reads stored decisions; one bar gives today's price

    def evaluate(self, df: pd.DataFrame, instrument: Instrument, db: Session) -> SignalDecision | None:
        if df.empty:
            return None
        today = today_ist()
        if self._loaded_for != today:
            self._run, self._decisions = todays_decisions(db, today, self.config.mode)
            self._loaded_for = today
        price = float(df["close"].iloc[-1])
        return to_signal(self._decisions.get(instrument.tradingsymbol), self._run, price)
```

In `backend/src/swing_trade_ml/strategies/__init__.py` add `from swing_trade_ml.strategies.brain import BrainStrategy` (after the `base` import) and `"BrainStrategy"` to `__all__` (alphabetical).

- [ ] **Step 5: Run to verify pass**

Run: same command as Step 3. Expected: all pass. Also run `tests/test_brain_service.py::test_brain_package_never_imports_order_placement` (still passes).

- [ ] **Step 6: Lint and commit**

```bash
cd backend && "D:/machine learning/swing-trade-bot/backend/.venv/Scripts/python.exe" -m ruff format src/swing_trade_ml/strategies/brain.py tests/brain_m18_fixtures.py tests/test_brain_m18_strategy.py
"D:/machine learning/swing-trade-bot/backend/.venv/Scripts/python.exe" -m ruff check src/swing_trade_ml/strategies/brain.py src/swing_trade_ml/strategies/__init__.py tests/brain_m18_fixtures.py tests/test_brain_m18_strategy.py
git add src/swing_trade_ml/strategies/brain.py src/swing_trade_ml/strategies/__init__.py tests/brain_m18_fixtures.py tests/test_brain_m18_strategy.py
git commit -m "M18: BrainStrategy reads today's stored brain decision"
```

---

### Task 2: Execution-path guards — always advisory, v1 untouched, real exits for approved positions

**Files:**
- Modify: `backend/src/swing_trade_ml/core/strategy_policy.py` (whole file, 24 lines)
- Modify: `backend/src/swing_trade_ml/services/execution.py` — the advisory BUY branch (~line 933) and `check_exits` (~line 1145, `position_is_advisory = is_advisory(position.strategy)`), plus the import on line 18
- Modify: `backend/src/swing_trade_ml/services/engine.py` — `run_all_active` select (~lines 197-208), import on line 12
- Modify: `backend/src/swing_trade_ml/services/risk.py` — `active_strategy_count` (lines 87-96)
- Test: `backend/tests/test_brain_m18_guard.py`

**Interfaces:**
- Consumes: Task 1 (`"brain"` registered); fixtures `brain_strategy`, `v1_strategy`, `instrument`, `no_broker`.
- Produces:
```python
# core/strategy_policy.py
MANUAL_ONLY_TYPES: frozenset[str]   # {"long_term_value"} — the app never orders these
STAGED_TYPES: frozenset[str]        # {"brain"} — ordered only through services/brain_golive/approvals.py
def requires_advisory(strategy_type: str) -> bool          # True for both sets
def is_staged(strategy) -> bool
def is_advisory(strategy) -> bool                          # unchanged formula
def exits_are_advisory(strategy) -> bool                   # is_advisory and not is_staged
def validate_execution_mode(strategy_type: str, execution_mode: str) -> None
def require_broker_execution(strategy) -> None             # raises only for MANUAL_ONLY_TYPES
```

- [ ] **Step 1: Write the failing tests** `backend/tests/test_brain_m18_guard.py`:

```python
"""M18 task 2: the brain is always advisory in the scan path; version 1 is
unchanged when it is switched on; positions the owner approved get v1's real
exits. No test here can reach a broker."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from brain_m18_fixtures import brain_strategy, instrument, no_broker, v1_strategy

from swing_trade_ml.core import strategy_policy as policy
from swing_trade_ml.core.enums import ExitReason, PositionStatus, SignalType
from swing_trade_ml.db.models.trading import Order, Position
from swing_trade_ml.services import engine, execution, risk
from swing_trade_ml.services.risk import RiskDecision
from swing_trade_ml.strategies.base import SignalDecision

HEADERS = {"X-API-Key": "test-api-key"}
BUY = SignalDecision(SignalType.BUY, 100.0, 0.6, "r", stop_loss=96.0, take_profit=108.0, horizon_days=15)


def _row(strategy_type: str, execution_mode: str = "advisory"):
    return SimpleNamespace(strategy_type=strategy_type, execution_mode=execution_mode)


def test_the_brain_is_advisory_in_the_scan_path_even_if_its_row_says_auto():
    assert policy.requires_advisory("brain") is True
    assert policy.is_advisory(_row("brain", "auto")) is True


def test_only_long_term_value_is_refused_by_the_order_path():
    policy.require_broker_execution(_row("brain"))  # approvals may order for it
    with pytest.raises(ValueError, match="Long-term"):
        policy.require_broker_execution(_row("long_term_value"))


def test_exits_of_an_approved_brain_position_are_real_sells():
    assert policy.exits_are_advisory(_row("brain")) is False
    assert policy.exits_are_advisory(_row("long_term_value")) is True
    assert policy.exits_are_advisory(_row("ml_swing", "advisory")) is True
    assert policy.exits_are_advisory(_row("ml_swing", "auto")) is False


def test_the_brain_strategy_cannot_be_switched_to_auto_through_the_strategies_api(client):
    r = client.post("/api/v1/strategies", json={"name": "m18-api-brain", "strategy_type": "brain"}, headers=HEADERS)
    assert r.status_code == 201 and r.json()["execution_mode"] == "advisory"
    r2 = client.patch(f"/api/v1/strategies/{r.json()['id']}", json={"execution_mode": "auto"}, headers=HEADERS)
    assert r2.status_code == 422 and "Brain page" in r2.json()["detail"]
    r3 = client.post(
        "/api/v1/strategies",
        json={"name": "m18-api-brain2", "strategy_type": "brain", "execution_mode": "auto"},
        headers=HEADERS,
    )
    assert r3.status_code == 422


def _allow_everything(monkeypatch) -> list[str]:
    no_broker(monkeypatch)
    sent: list[str] = []
    monkeypatch.setattr(execution.notifier, "send_sync", lambda text, event="system": sent.append(text) or True)
    monkeypatch.setattr(execution, "portfolio_value_and_cash", lambda db, mode: (1_000_000.0, 1_000_000.0))
    monkeypatch.setattr(execution.risk, "check_entry", lambda **kw: RiskDecision(True, 10))
    return sent


def test_a_shadow_brain_buy_never_creates_an_order(db_session, monkeypatch):
    sent = _allow_everything(monkeypatch)
    strategy = brain_strategy(db_session)
    inst = instrument(db_session, "M18GRD", 918101)
    sig = execution.process_decision(db_session, strategy, inst, BUY)
    assert sig.advisory_only is True and sig.rejection_reason is None and sig.was_executed is False
    assert db_session.query(Order).filter_by(strategy_id=strategy.id).count() == 0
    assert db_session.query(Position).filter_by(strategy_id=strategy.id).count() == 0
    assert sent == []  # practice ideas are never announced as recommendations


def test_an_advisory_v1_buy_is_still_announced(db_session, monkeypatch):
    sent = _allow_everything(monkeypatch)
    strategy = v1_strategy(db_session, name="m18-adv-v1", execution_mode="advisory")
    inst = instrument(db_session, "M18GRE", 918102)
    execution.process_decision(db_session, strategy, inst, BUY)
    assert len(sent) == 1


def test_the_daily_scan_never_runs_the_brain_strategy(db_session, monkeypatch):
    brain_strategy(db_session, name="m18-scan-brain")
    v1_strategy(db_session, name="m18-scan-v1")
    ran: list[str] = []
    monkeypatch.setattr(
        engine, "run_strategy",
        lambda db, s, interval="day": ran.append(s.strategy_type) or engine.ScanResult(strategies_run=1),
    )
    engine.run_all_active(db_session)
    assert "brain" not in ran and "ml_swing" in ran


def test_an_active_brain_strategy_does_not_shrink_version_1s_slot_share(db_session):
    v1_strategy(db_session, name="m18-share-v1")
    before = risk.active_strategy_count(db_session, "paper")
    brain_strategy(db_session, name="m18-share-brain")
    assert risk.active_strategy_count(db_session, "paper") == before


def test_an_approved_brain_position_at_its_stop_is_sold_by_version_1(db_session, monkeypatch):
    strategy = brain_strategy(db_session, name="m18-exit-brain")
    inst = instrument(db_session, "M18GRF", 918103)
    pos = Position(
        strategy_id=strategy.id, instrument_id=inst.id, mode="paper", status=PositionStatus.OPEN,
        quantity=10, initial_quantity=10, entry_price=100.0, entry_at=datetime.now(UTC),
        stop_loss=96.0, initial_stop_loss=96.0, take_profit=108.0, highest_price=100.0,
        current_price=100.0, total_charges=0.0,
    )
    db_session.add(pos)
    db_session.flush()
    fake = no_broker(monkeypatch)
    fake.get_ltp = lambda keys, db: {inst.symbol_key: 95.0}
    closed = []
    monkeypatch.setattr(
        execution, "close_position",
        lambda db, p, price, reason, note=None, quantity=None: closed.append((p.id, reason)),
    )
    monkeypatch.setattr(execution, "_claim_exit", lambda db, p: True)
    monkeypatch.setattr(execution, "_release_exit", lambda db, p: None)
    execution.check_exits(db_session)
    assert closed == [(pos.id, ExitReason.STOP_LOSS_HIT)]
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && env -u API_KEY -u DATABASE_URL -u JWT_SECRET_KEY -u TRADING_MODE "D:/machine learning/swing-trade-bot/backend/.venv/Scripts/python.exe" -m pytest -q tests/test_brain_m18_guard.py`
Expected: FAIL — `requires_advisory("brain")` is False; `exits_are_advisory` missing; scan runs the brain; slot share shrinks; message sent.

- [ ] **Step 3: Implement**

Replace `backend/src/swing_trade_ml/core/strategy_policy.py` with:

```python
"""Strategy execution capabilities shared by validation and order paths."""

# The app never places orders for these: the owner records their trades by hand.
MANUAL_ONLY_TYPES = frozenset({"long_term_value"})
# Ordered ONLY through the owner's go-live stages (brain M18,
# services/brain_golive/approvals.py) — never by the scan itself.
STAGED_TYPES = frozenset({"brain"})


def requires_advisory(strategy_type: str) -> bool:
    return strategy_type in MANUAL_ONLY_TYPES or strategy_type in STAGED_TYPES


def is_staged(strategy) -> bool:
    return strategy is not None and strategy.strategy_type in STAGED_TYPES


def is_advisory(strategy) -> bool:
    return strategy is not None and (
        requires_advisory(strategy.strategy_type) or strategy.execution_mode == "advisory"
    )


def exits_are_advisory(strategy) -> bool:
    """Whether exits only alert (the owner sells by hand). A staged strategy's
    positions exist only because the owner approved an order, so version 1's
    own stops, targets and time stop must protect them."""
    return is_advisory(strategy) and not is_staged(strategy)


def validate_execution_mode(strategy_type: str, execution_mode: str) -> None:
    if strategy_type in STAGED_TYPES and execution_mode != "advisory":
        raise ValueError(
            "The brain strategy only records ideas here. Its trading stage is changed "
            "by the owner on the Brain page."
        )
    if requires_advisory(strategy_type) and execution_mode != "advisory":
        raise ValueError("Long-term strategies support advisory execution only")


def require_broker_execution(strategy) -> None:
    if strategy is not None and strategy.strategy_type in MANUAL_ONLY_TYPES:
        raise ValueError("Long-term strategies are advisory only; record the trade manually")
```

`services/execution.py`:
- line 18: `from swing_trade_ml.core.strategy_policy import exits_are_advisory, is_advisory, is_staged, require_broker_execution`
- the advisory BUY branch (just before `notifier.send_sync(_signal_message(...))`):

```python
    if is_advisory(strategy):
        signal.advisory_only = True
        db.commit()
        # A staged (brain) strategy's ideas are announced by its approvals
        # service instead; in practice mode they are not announced at all, so
        # the owner is never nudged to act on a practice idea.
        if not is_staged(strategy):
            notifier.send_sync(
                _advisory_entry_message(instrument, decision, strategy, verdict.quantity, mode),
                "signal",
            )
        return signal
```
- in `check_exits`: `position_is_advisory = exits_are_advisory(position.strategy)` and extend the comment above it with one line: "A brain position (staged type) is the exception: the owner approved its order, so v1 protects it with real exits."

`services/engine.py`: import `from swing_trade_ml.core.strategy_policy import STAGED_TYPES, is_advisory`; in `run_all_active` add to the `.where(...)`:

```python
                Strategy.is_active.is_(True),
                # Staged strategies (the brain, M18) run right after the brain's
                # own nightly run instead (services/brain_golive/shadow.py): at
                # 15:45 the brain has not run yet.
                Strategy.strategy_type.not_in(sorted(STAGED_TYPES)),
```

`services/risk.py`: import `from swing_trade_ml.core.strategy_policy import STAGED_TYPES`; in `active_strategy_count` add `Strategy.strategy_type.not_in(sorted(STAGED_TYPES))` to the `.where(...)` and to the docstring: "A staged strategy (the brain, M18) is left out so switching it on never shrinks version 1's own share (P6); its positions still count account-wide."

- [ ] **Step 4: Run to verify pass, plus the v1 suites this touches**

Run: `... -m pytest -q tests/test_brain_m18_guard.py tests/test_correctness_release.py tests/test_buy_slot_allocation.py tests/test_advisory_exit_alert_visibility.py tests/test_exit_switch.py tests/test_portfolio_risk_layer.py tests/test_partial_profit_booking.py tests/test_trailing_stop.py`
Expected: all pass.

- [ ] **Step 5: Lint and commit** (`ruff format` only the new test file; `ruff check` the four edited v1 files — no new findings)

```bash
git add src/swing_trade_ml/core/strategy_policy.py src/swing_trade_ml/services/execution.py src/swing_trade_ml/services/engine.py src/swing_trade_ml/services/risk.py tests/test_brain_m18_guard.py
git commit -m "M18: brain is always advisory in the scan, v1 untouched, approved positions get real exits"
```

---

### Task 3: Shadow run after the nightly brain run — strategy row, job hook, CLI

**Files:**
- Create: `backend/src/swing_trade_ml/services/brain_golive/__init__.py` (docstring only: `"""M18 · Shadow run and go-live switch. Lives outside the brain package (constitution C10)."""`)
- Create: `backend/src/swing_trade_ml/services/brain_golive/shadow.py`
- Modify: `backend/src/swing_trade_ml/workers/jobs.py` — `_run_brain_job` (~line 588) + new `job_brain_strategy`
- Modify: `backend/src/swing_trade_ml/cli.py` — `cmd_brain` + parser (~line 540), and the usage line 11
- Test: `backend/tests/test_brain_m18_shadow.py`

**Interfaces:**
- Consumes: Task 1 `today_ist`, `todays_run`; Task 2 guards; `engine.run_strategy`, `engine.ScanResult`.
- Produces:
```python
# services/brain_golive/shadow.py
BRAIN_STRATEGY_NAME = "TradeMind brain"
def ensure_brain_strategy(db: Session) -> Strategy      # idempotent; advisory, active, broker's mode, whole watchlist
def active_brain_strategies(db: Session) -> list[Strategy]
def run_brain_strategy(db: Session, interval: str = "day") -> ScanResult
    # skips (with an error line) a strategy whose book has no brain run today
# workers/jobs.py
def job_brain_strategy() -> None                        # never raises; called after a nightly brain run
```

- [ ] **Step 1: Write the failing tests** `backend/tests/test_brain_m18_shadow.py`:

```python
"""M18 task 3: the brain strategy runs right after the nightly brain run,
records its ideas through the normal strategy path and orders nothing; v1's
signal evaluator scores them."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from brain_m18_fixtures import DAY, at, brain_strategy, candle, decision, instrument, no_broker, run, signal

from swing_trade_ml.cli import build_parser
from swing_trade_ml.core.enums import SignalType
from swing_trade_ml.db.models.trading import Order, Signal
from swing_trade_ml.services import engine, execution
from swing_trade_ml.services.brain_golive import shadow
from swing_trade_ml.services.risk import RiskDecision
from swing_trade_ml.strategies import brain as brain_mod


@pytest.fixture()
def safe_scan(monkeypatch):
    no_broker(monkeypatch)
    monkeypatch.setattr(brain_mod, "today_ist", lambda: DAY)
    monkeypatch.setattr(engine, "_buy_slot_budget", lambda db, strategy, mode: 5)
    monkeypatch.setattr(execution, "portfolio_value_and_cash", lambda db, mode: (1_000_000.0, 1_000_000.0))
    monkeypatch.setattr(execution.risk, "check_entry", lambda **kw: RiskDecision(True, 10))


def test_ensure_brain_strategy_is_idempotent_and_advisory(db_session, monkeypatch):
    monkeypatch.setattr(shadow, "current_mode", lambda: "paper")
    a = shadow.ensure_brain_strategy(db_session)
    b = shadow.ensure_brain_strategy(db_session)
    assert a.id == b.id
    assert (a.strategy_type, a.execution_mode, a.is_active, a.mode) == ("brain", "advisory", True, "paper")


def test_the_shadow_scan_records_the_idea_and_orders_nothing(db_session, safe_scan):
    inst = instrument(db_session, "M18SHD", 918202)
    candle(db_session, inst, DAY, 101.0)
    strategy = brain_strategy(db_session, symbols=["M18SHD"])
    run(db_session, "m18-shd")
    decision(db_session, "m18-shd", "M18SHD", "TRADE")
    result = shadow.run_brain_strategy(db_session)
    assert result.errors == [] and result.buys == 1
    sig = db_session.query(Signal).filter_by(strategy_id=strategy.id).one()
    assert (sig.signal_type, sig.advisory_only, sig.stop_loss, sig.take_profit, sig.horizon_days) == (
        SignalType.BUY, True, 96.0, 108.0, 15,
    )
    assert db_session.query(Order).filter_by(strategy_id=strategy.id).count() == 0


def test_no_brain_run_today_skips_the_scan(db_session, safe_scan):
    inst = instrument(db_session, "M18SHE", 918203)
    candle(db_session, inst, DAY, 101.0)
    strategy = brain_strategy(db_session, symbols=["M18SHE"])
    result = shadow.run_brain_strategy(db_session)
    assert "no brain run today" in result.errors[0]
    assert db_session.query(Signal).filter_by(strategy_id=strategy.id).count() == 0


def test_brain_buy_signals_are_scored_by_version_1s_signal_evaluator(db_session):
    from swing_trade_ml.ml.predict import evaluate_pending_signals

    strategy = brain_strategy(db_session)
    inst = instrument(db_session, "M18SCR", 918201)
    sig = signal(db_session, strategy, inst, DAY)
    candle(db_session, inst, DAY + timedelta(days=1), 105.0, high=109.0, low=101.0)
    evaluate_pending_signals(db_session, now=at(DAY + timedelta(days=3)))
    db_session.refresh(sig)
    assert sig.outcome == "TARGET_HIT" and sig.outcome_pct == pytest.approx(0.08)


@contextmanager
def _fake_scope():
    yield MagicMock()


def test_the_brain_strategy_runs_after_a_nightly_run_only(monkeypatch):
    from swing_trade_ml.brain import service as brain_service
    from swing_trade_ml.workers import jobs

    monkeypatch.setattr(jobs, "session_scope", _fake_scope)
    monkeypatch.setattr(brain_service, "run_brain", lambda db, kind, book: (None, f"rid-{kind}"))
    calls: list[str] = []
    monkeypatch.setattr(jobs, "job_brain_strategy", lambda: calls.append("ran"))
    jobs._run_brain_job("intraday")
    assert calls == []
    jobs._run_brain_job("nightly")
    assert calls == ["ran"]


def test_a_failed_nightly_run_does_not_run_the_brain_strategy(monkeypatch):
    from swing_trade_ml.brain import service as brain_service
    from swing_trade_ml.workers import jobs

    def boom(db, kind, book):
        raise RuntimeError("no data")

    monkeypatch.setattr(jobs, "session_scope", _fake_scope)
    monkeypatch.setattr(brain_service, "run_brain", boom)
    monkeypatch.setattr(jobs, "_report_error", lambda *a, **k: None)
    calls: list[str] = []
    monkeypatch.setattr(jobs, "job_brain_strategy", lambda: calls.append("ran"))
    jobs._run_brain_job("nightly")
    assert calls == []


def test_a_failing_brain_strategy_job_is_reported_not_raised(monkeypatch):
    from swing_trade_ml.workers import jobs

    reported = []
    monkeypatch.setattr(jobs, "session_scope", _fake_scope)
    monkeypatch.setattr(shadow, "run_brain_strategy", MagicMock(side_effect=RuntimeError("x")))
    monkeypatch.setattr(jobs, "_report_error", lambda what, exc: reported.append(what))
    jobs.job_brain_strategy()
    assert reported == ["brain strategy scan"]


def test_brain_strategy_commands_parse():
    assert build_parser().parse_args(["brain", "strategy-create"]).brain_command == "strategy-create"
    assert build_parser().parse_args(["brain", "shadow-scan"]).brain_command == "shadow-scan"
```

- [ ] **Step 2: Run to verify failure**

Run: `... -m pytest -q tests/test_brain_m18_shadow.py`
Expected: FAIL — `ModuleNotFoundError: swing_trade_ml.services.brain_golive`.

- [ ] **Step 3: Implement** `backend/src/swing_trade_ml/services/brain_golive/shadow.py`:

```python
"""M18 stage 1: run the brain strategy right after the brain's nightly run.

Version 1's 15:45 scan leaves the brain strategy out (services/engine.py):
at 15:45 the brain has not run yet, so every stock would read "No brain run
today". This runs it once the nightly run is stored. Its signals go through
the normal strategy path; "brain" is always advisory in that path
(core/strategy_policy.py), so nothing is ever bought here.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.brokers import current_mode
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.trading import Strategy
from swing_trade_ml.services import engine
from swing_trade_ml.services.engine import ScanResult
from swing_trade_ml.strategies import brain as brain_strategy

log = get_logger(__name__)

BRAIN_STRATEGY_NAME = "TradeMind brain"
BRAIN_STRATEGY_DESCRIPTION = (
    "The TradeMind brain's ideas, recorded and scored next to version 1. It never buys on its own: "
    "in practice mode nothing is bought; later each idea waits for your OK on the Brain page."
)


def ensure_brain_strategy(db: Session) -> Strategy:
    existing = db.execute(
        select(Strategy).where(Strategy.strategy_type == "brain").order_by(Strategy.id).limit(1)
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    row = Strategy(
        name=BRAIN_STRATEGY_NAME,
        description=BRAIN_STRATEGY_DESCRIPTION,
        strategy_type="brain",
        params={},
        symbols=[],  # the whole watchlist, like the brain itself
        is_active=True,
        mode=current_mode(),
        execution_mode="advisory",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def active_brain_strategies(db: Session) -> list[Strategy]:
    return list(
        db.execute(
            select(Strategy)
            .where(Strategy.strategy_type == "brain", Strategy.is_active.is_(True))
            .order_by(Strategy.id)
        ).scalars()
    )


def _merge(into: ScanResult, r: ScanResult) -> None:
    into.strategies_run += r.strategies_run
    into.instruments_evaluated += r.instruments_evaluated
    into.signals_generated += r.signals_generated
    into.buys += r.buys
    into.exits += r.exits
    into.executed += r.executed
    into.errors.extend(r.errors)


def run_brain_strategy(db: Session, interval: str = "day") -> ScanResult:
    combined = ScanResult()
    today = brain_strategy.today_ist()
    for strategy in active_brain_strategies(db):
        if brain_strategy.todays_run(db, today, strategy.mode) is None:
            combined.errors.append(
                f"{strategy.name}: no brain run today for the {strategy.mode} book — skipped"
            )
            continue
        _merge(combined, engine.run_strategy(db, strategy, interval))
    log.info("brain_golive.shadow.done", signals=combined.signals_generated, buys=combined.buys)
    return combined
```

`workers/jobs.py` — change `_run_brain_job` so a successful nightly run is followed by the brain strategy, and add the job:

```python
def _run_brain_job(kind: str) -> None:
    """A failed brain run is logged and reported, never raised: the brain is
    advisory and must not disturb version 1's jobs. After a nightly run the
    brain strategy (M18) turns its ideas into version 1 signals."""
    from swing_trade_ml.brain import service as brain_service

    try:
        with session_scope() as db:
            _, run_id = brain_service.run_brain(db, kind=kind, book=settings.TRADING_MODE)
            log.info("job.brain.done", kind=kind, run_id=run_id)
            if settings.BRAIN_ALERTS_ENABLED:
                from swing_trade_ml.brain.alerts import service as brain_alerts

                brain_alerts.send(db, run_id)
    except Exception as exc:  # noqa: BLE001
        _report_error(f"brain {kind} run", exc)
        return
    if kind == "nightly":
        job_brain_strategy()


def job_brain_strategy() -> None:
    """M18: record today's brain ideas as the brain strategy's signals, scored
    like version 1's. The scan path never orders for it. Never raised."""
    from swing_trade_ml.services.brain_golive import shadow

    try:
        with session_scope() as db:
            result = shadow.run_brain_strategy(db)
            log.info("job.brain.strategy.done", signals=result.signals_generated, buys=result.buys,
                     errors=len(result.errors))
    except Exception as exc:  # noqa: BLE001
        _report_error("brain strategy scan", exc)
```

`cli.py` — in `cmd_brain`, before the `why` branch:

```python
        if args.brain_command == "strategy-create":
            from swing_trade_ml.services.brain_golive.shadow import ensure_brain_strategy

            s = ensure_brain_strategy(db)
            print(f"✅ Brain strategy '{s.name}' (id {s.id}) is active in practice mode: "
                  "its ideas are recorded and scored, nothing is bought.")
            return 0
        if args.brain_command == "shadow-scan":
            from swing_trade_ml.services.brain_golive.shadow import run_brain_strategy

            result = run_brain_strategy(db)
            print(f"✅ Brain strategy scan: {result.signals_generated} signals "
                  f"({result.buys} ideas to buy, nothing bought)")
            for err in result.errors[:10]:
                print(f"   • {err}")
            return 0
```
Parser (after `learn`): `brain_sub.add_parser("strategy-create", help="Create the brain strategy in practice mode (M18)")` and `brain_sub.add_parser("shadow-scan", help="Record today's brain ideas as strategy signals (M18)")`. Add `| strategy-create | shadow-scan` to the usage line 11.

- [ ] **Step 4: Run to verify pass** — `tests/test_brain_m18_shadow.py tests/test_brain_cli_and_jobs.py`. Expected: pass.

- [ ] **Step 5: Lint and commit** (`ruff format` the new package and test; `ruff check` jobs.py, cli.py)

```bash
git add src/swing_trade_ml/services/brain_golive src/swing_trade_ml/workers/jobs.py src/swing_trade_ml/cli.py tests/test_brain_m18_shadow.py
git commit -m "M18: run the brain strategy after the nightly brain run (shadow)"
```

---

### Task 4: Brain vs version 1 comparison — `GET /brain/compare`

**Files:**
- Create: `backend/src/swing_trade_ml/services/brain_golive/compare.py`
- Create: `backend/src/swing_trade_ml/api/v1/endpoints/brain_golive.py`
- Modify: `backend/src/swing_trade_ml/api/v1/router.py` (import `brain_golive`; `api_router.include_router(brain_golive.router, dependencies=protected)` right after the brain router)
- Test: `backend/tests/test_brain_m18_compare.py`

**Interfaces:**
- Consumes: Task 1 `IST`, `ist_day_bounds`; `STAGED_TYPES`.
- Produces:
```python
# compare.py
TARGET = "TARGET_HIT"; STOP = "STOP_LOSS_HIT"
NEEDED_FINISHED = 30                 # finished brain ideas before leaving shadow (stage.py imports it)
MIN_FINISHED_TO_COMPARE = 10
@dataclass(frozen=True, slots=True)
class Row: strategy: str; is_brain: bool; symbol: str; day: date; generated_at: datetime; outcome: str | None; outcome_pct: float | None
def one_per_day(rows: list[Row]) -> list[Row]
def summarise(rows: list[Row]) -> dict     # {"ideas","finished","hit_rate","stopped","avg_outcome_pct"} (None when nothing finished)
def compare(rows: list[Row], brain_days: set[date], min_finished: int = MIN_FINISHED_TO_COMPARE) -> dict
    # {"days","first_day","last_day","strategies":[{"name","is_brain",**summary}],"brain","version1",
    #  "by_week":[{"week","brain","version1"}],"note"}
def load(db, since: date | None = None) -> tuple[list[Row], set[date]]
def finished_brain_ideas(db) -> int
def report(db, since: date | None = None) -> dict    # compare(...) + {"brain_finished", "needed"}
# endpoints/brain_golive.py
router = APIRouter(prefix="/brain", tags=["brain"], dependencies=[Depends(_brain_switched_on)])
GET /brain/compare?since=YYYY-MM-DD -> report(...)
```

- [ ] **Step 1: Write the failing tests** `backend/tests/test_brain_m18_compare.py`:

```python
"""M18 task 4: brain vs version 1 on the same days, from Signal outcomes."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from brain_m18_fixtures import DAY, brain_strategy, instrument, signal, v1_strategy

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import SignalType
from swing_trade_ml.services.brain_golive import compare as cmp

HEADERS = {"X-API-Key": "test-api-key"}
D1, D2, D3 = date(2031, 1, 6), date(2031, 1, 7), date(2031, 1, 14)


def _row(strategy, day, outcome=None, pct=None, symbol="A", is_brain=None, hour=10):
    return cmp.Row(
        strategy=strategy, is_brain=(strategy == "brain") if is_brain is None else is_brain, symbol=symbol,
        day=day, generated_at=datetime(day.year, day.month, day.day, hour, tzinfo=UTC), outcome=outcome,
        outcome_pct=pct,
    )


def test_only_days_the_brain_ran_count():
    rows = [_row("brain", D1, "TARGET_HIT", 0.08), _row("v1", D1, "STOP_LOSS_HIT", -0.04), _row("v1", D2, "TARGET_HIT", 0.08)]
    out = cmp.compare(rows, {D1})
    assert out["version1"]["ideas"] == 1 and out["days"] == 1


def test_hit_rate_and_average_use_finished_ideas_only():
    rows = [
        _row("brain", D1, "TARGET_HIT", 0.08, symbol="A"),
        _row("brain", D1, "STOP_LOSS_HIT", -0.04, symbol="B"),
        _row("brain", D1, None, None, symbol="C"),
    ]
    s = cmp.compare(rows, {D1})["brain"]
    assert (s["ideas"], s["finished"]) == (3, 2)
    assert s["hit_rate"] == pytest.approx(0.5) and s["stopped"] == pytest.approx(0.5)
    assert s["avg_outcome_pct"] == pytest.approx(0.02)


def test_nothing_finished_gives_no_rates():
    s = cmp.summarise([_row("brain", D1)])
    assert s == {"ideas": 1, "finished": 0, "hit_rate": None, "stopped": None, "avg_outcome_pct": None}


def test_one_idea_per_stock_per_day():
    rows = [_row("brain", D1, "STOP_LOSS_HIT", -0.04, hour=10), _row("brain", D1, "TARGET_HIT", 0.08, hour=12)]
    s = cmp.compare(rows, {D1})["brain"]
    assert s["ideas"] == 1 and s["hit_rate"] == 1.0  # the later scan of the day wins


def test_brain_first_then_version_1_strategies_and_weeks_ascending():
    rows = [_row("ml", D3), _row("brain", D3), _row("brain", D1), _row("sma", D1)]
    out = cmp.compare(rows, {D1, D3})
    assert [s["name"] for s in out["strategies"]] == ["brain", "ml", "sma"]
    assert [w["week"] for w in out["by_week"]] == ["2031-W02", "2031-W03"]


def test_notes_in_plain_words():
    assert cmp.compare([], set())["note"].startswith("The brain strategy has not run yet")
    few = cmp.compare([_row("brain", D1, "TARGET_HIT", 0.08)], {D1})["note"]
    assert "too few to compare yet" in few
    many = [_row("brain", D1, "TARGET_HIT", 0.08, symbol=f"B{i}") for i in range(10)]
    many += [_row("v1", D1, "STOP_LOSS_HIT", -0.04, symbol=f"V{i}") for i in range(10)]
    note = cmp.compare(many, {D1})["note"]
    assert note == (
        "On the same 1 day, the brain's ideas reached their target 100% of the time (average result +8.0%); "
        "version 1's reached it 0% of the time (average -4.0%)."
    )


def test_the_loader_reads_buy_signals_and_skips_long_term_ideas(db_session):
    brain = brain_strategy(db_session)
    ml = v1_strategy(db_session, name="m18-cmp-ml")
    ltv = v1_strategy(db_session, name="m18-cmp-ltv", strategy_type="long_term_value", execution_mode="advisory")
    inst = instrument(db_session, "M18CMP", 918401)
    signal(db_session, brain, inst, D1, outcome="TARGET_HIT", outcome_pct=0.08)
    signal(db_session, brain, inst, D2, signal_type=SignalType.HOLD)  # the brain ran on D2 too
    signal(db_session, ml, inst, D2, outcome="STOP_LOSS_HIT", outcome_pct=-0.04)
    signal(db_session, ml, inst, D3)  # the brain did not run that day
    signal(db_session, ltv, inst, D1)
    rows, days = cmp.load(db_session)
    assert days == {D1, D2}
    assert {r.strategy for r in rows} == {brain.name, ml.name}  # HOLD and long-term rows left out
    out = cmp.compare(rows, days)
    assert out["version1"]["ideas"] == 1 and out["brain"]["finished"] == 1
    assert cmp.finished_brain_ideas(db_session) == 1


def test_compare_endpoint_on_an_empty_book(client):
    r = client.get("/api/v1/brain/compare", headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["strategies"] == [] and body["needed"] == 30 and body["brain_finished"] == 0
    assert body["note"].startswith("The brain strategy has not run yet")


def test_compare_is_hidden_while_the_brain_is_off(client, monkeypatch):
    monkeypatch.setattr(settings, "BRAIN_ENABLED", False)
    assert client.get("/api/v1/brain/compare", headers=HEADERS).status_code == 404
```

- [ ] **Step 2: Run to verify failure** — `... -m pytest -q tests/test_brain_m18_compare.py`. Expected: FAIL (module missing).

- [ ] **Step 3: Implement** `services/brain_golive/compare.py`:

```python
"""M18: the brain strategy vs version 1 on the same days, from Signal outcomes
(scored by ml/predict.py::evaluate_pending_signals — the same scorer for both).
Pure functions on `Row`s plus one loader."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from swing_trade_ml.core.enums import SignalType
from swing_trade_ml.core.strategy_policy import STAGED_TYPES
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Signal, Strategy
from swing_trade_ml.strategies.brain import IST, ist_day_bounds

TARGET = "TARGET_HIT"
STOP = "STOP_LOSS_HIT"
NEEDED_FINISHED = 30
MIN_FINISHED_TO_COMPARE = 10
EXCLUDED_TYPES = ("long_term_value",)  # a one-year horizon is not comparable


@dataclass(frozen=True, slots=True)
class Row:
    strategy: str
    is_brain: bool
    symbol: str
    day: date
    generated_at: datetime
    outcome: str | None
    outcome_pct: float | None


def one_per_day(rows: list[Row]) -> list[Row]:
    latest: dict[tuple[str, str, date], Row] = {}
    for r in rows:
        key = (r.strategy, r.symbol, r.day)
        if key not in latest or r.generated_at > latest[key].generated_at:
            latest[key] = r
    return sorted(latest.values(), key=lambda r: (r.day, r.strategy, r.symbol))


def summarise(rows: list[Row]) -> dict:
    finished = [r for r in rows if r.outcome is not None]
    n = len(finished)
    pcts = [r.outcome_pct for r in finished if r.outcome_pct is not None]
    return {
        "ideas": len(rows),
        "finished": n,
        "hit_rate": sum(r.outcome == TARGET for r in finished) / n if n else None,
        "stopped": sum(r.outcome == STOP for r in finished) / n if n else None,
        "avg_outcome_pct": sum(pcts) / len(pcts) if pcts else None,
    }


def _week(day: date) -> str:
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def _note(n_days: int, brain: dict, v1: dict, min_finished: int) -> str:
    if n_days == 0:
        return (
            "The brain strategy has not run yet. Once it runs after the nightly brain run, "
            "its ideas appear here and are scored as they finish."
        )
    if brain["finished"] < min_finished or v1["finished"] < min_finished:
        return (
            f"Only {brain['finished']} of the brain's ideas and {v1['finished']} of version 1's have "
            "finished on the same days — too few to compare yet."
        )
    days = f"{n_days} day" + ("s" if n_days != 1 else "")
    return (
        f"On the same {days}, the brain's ideas reached their target {brain['hit_rate']:.0%} of the time "
        f"(average result {brain['avg_outcome_pct'] or 0.0:+.1%}); version 1's reached it {v1['hit_rate']:.0%} "
        f"of the time (average {v1['avg_outcome_pct'] or 0.0:+.1%})."
    )


def compare(rows: list[Row], brain_days: set[date], min_finished: int = MIN_FINISHED_TO_COMPARE) -> dict:
    rows = [r for r in one_per_day(rows) if r.day in brain_days]
    brain = [r for r in rows if r.is_brain]
    v1 = [r for r in rows if not r.is_brain]
    names = sorted({r.strategy for r in brain}) + sorted({r.strategy for r in v1})
    brain_names = {r.strategy for r in brain}
    days = sorted(brain_days)
    b, v = summarise(brain), summarise(v1)
    return {
        "days": len(days),
        "first_day": days[0].isoformat() if days else None,
        "last_day": days[-1].isoformat() if days else None,
        "strategies": [
            {"name": n, "is_brain": n in brain_names, **summarise([r for r in rows if r.strategy == n])}
            for n in names
        ],
        "brain": b,
        "version1": v,
        "by_week": [
            {
                "week": w,
                "brain": summarise([r for r in brain if _week(r.day) == w]),
                "version1": summarise([r for r in v1 if _week(r.day) == w]),
            }
            for w in sorted({_week(r.day) for r in rows})
        ],
        "note": _note(len(days), b, v, min_finished),
    }


def load(db: Session, since: date | None = None) -> tuple[list[Row], set[date]]:
    staged = sorted(STAGED_TYPES)
    stmt = (
        select(Signal.generated_at, Signal.outcome, Signal.outcome_pct, Strategy.name,
               Strategy.strategy_type, Instrument.tradingsymbol)
        .join(Strategy, Strategy.id == Signal.strategy_id)
        .join(Instrument, Instrument.id == Signal.instrument_id)
        .where(
            Signal.signal_type == SignalType.BUY,
            Signal.stop_loss.isnot(None),
            Signal.take_profit.isnot(None),
            Strategy.strategy_type.not_in(EXCLUDED_TYPES),
        )
    )
    ist_date = func.date(func.timezone("Asia/Kolkata", Signal.generated_at))
    days_stmt = (
        select(distinct(ist_date))
        .join(Strategy, Strategy.id == Signal.strategy_id)
        .where(Strategy.strategy_type.in_(staged))
    )
    if since is not None:
        start = ist_day_bounds(since)[0]
        stmt = stmt.where(Signal.generated_at >= start)
        days_stmt = days_stmt.where(Signal.generated_at >= start)
    rows = [
        Row(strategy=name, is_brain=stype in STAGED_TYPES, symbol=symbol,
            day=generated.astimezone(IST).date(), generated_at=generated, outcome=outcome, outcome_pct=pct)
        for generated, outcome, pct, name, stype, symbol in db.execute(stmt)
    ]
    return rows, {d for (d,) in db.execute(days_stmt)}


def finished_brain_ideas(db: Session) -> int:
    rows, _ = load(db)
    return sum(1 for r in one_per_day(rows) if r.is_brain and r.outcome is not None)


def report(db: Session, since: date | None = None) -> dict:
    rows, days = load(db, since)
    return {**compare(rows, days), "brain_finished": finished_brain_ideas(db), "needed": NEEDED_FINISHED}
```

`api/v1/endpoints/brain_golive.py`:

```python
"""M18: the brain beside version 1, the owner's trading stage, and approvals.

Separate from endpoints/brain.py on purpose: nothing on that router can place
an order, while the approvals here can (only through v1 execution, after the
owner's OK). Same gate: hidden while BRAIN_ENABLED is false."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query

from swing_trade_ml.api.deps import DbSession
from swing_trade_ml.api.v1.endpoints.brain import _brain_switched_on
from swing_trade_ml.services.brain_golive import compare

router = APIRouter(prefix="/brain", tags=["brain"], dependencies=[Depends(_brain_switched_on)])


@router.get("/compare")
def compare_report(db: DbSession, since: date | None = Query(None)) -> dict:
    return compare.report(db, since)
```

- [ ] **Step 4: Run to verify pass** — `tests/test_brain_m18_compare.py tests/test_brain_api.py`. Expected: pass.

- [ ] **Step 5: Lint and commit**

```bash
git add src/swing_trade_ml/services/brain_golive/compare.py src/swing_trade_ml/api/v1/endpoints/brain_golive.py src/swing_trade_ml/api/v1/router.py tests/test_brain_m18_compare.py
git commit -m "M18: compare the brain with version 1 on the same days"
```

---

### Task 5: Console "Brain vs version 1" card (Stage 1 complete)

**Files:**
- Modify: `frontend/src/api/types.ts` (append types), `frontend/src/api/client.ts` (append to the brain block, after `brainRevertBuyLevel`)
- Create: `frontend/src/components/BrainGoLive.tsx`
- Modify: `frontend/src/pages/Brain.tsx` (import + render after the "Learning from results" card)

**Interfaces:**
- Consumes: `GET /brain/compare` (Task 4 shape).
- Produces: `BrainCompareSummary`, `BrainCompareStrategy`, `BrainCompareWeek`, `BrainCompare` types; `api.brainCompare()`; `export function BrainCompareCard()`.

- [ ] **Step 1: Types** (append to `frontend/src/api/types.ts`):

```ts
// M18 go-live: the brain beside version 1, scored the same way.
export interface BrainCompareSummary {
  ideas: number
  finished: number
  hit_rate: number | null
  stopped: number | null
  avg_outcome_pct: number | null
}

export interface BrainCompareStrategy extends BrainCompareSummary {
  name: string
  is_brain: boolean
}

export interface BrainCompareWeek {
  week: string
  brain: BrainCompareSummary
  version1: BrainCompareSummary
}

export interface BrainCompare {
  days: number
  first_day: string | null
  last_day: string | null
  strategies: BrainCompareStrategy[]
  brain: BrainCompareSummary
  version1: BrainCompareSummary
  by_week: BrainCompareWeek[]
  note: string
  brain_finished: number
  needed: number
}
```

Client (inside the `api` object after `brainRevertBuyLevel`, and add `BrainCompare` to the type import list at the top of `client.ts`):

```ts
  // M18 go-live: comparison, the owner's stage, approvals.
  brainCompare: () => get<BrainCompare>('/brain/compare'),
```

- [ ] **Step 2: Component** `frontend/src/components/BrainGoLive.tsx`:

```tsx
import { useQuery } from '@tanstack/react-query'

import { api } from '../api/client'
import type { BrainCompareSummary } from '../api/types'
import { formatSignedPercent } from '../lib/format'
import { ErrorBox, Loading } from './Loading'

/* Brain go-live (build book M18): the brain as a practice strategy next to
 * version 1, scored the same way. Plain words only. */

function pct(value: number | null): string {
  return value === null ? '—' : `${(value * 100).toFixed(0)}%`
}

function avg(value: number | null): string {
  return value === null ? '—' : formatSignedPercent(value, 1)
}

function SummaryCells({ s }: { s: BrainCompareSummary }) {
  return (
    <>
      <td>{s.ideas}</td>
      <td>{s.finished}</td>
      <td>{pct(s.hit_rate)}</td>
      <td>{pct(s.stopped)}</td>
      <td>{avg(s.avg_outcome_pct)}</td>
    </>
  )
}

export function BrainCompareCard() {
  const compare = useQuery({ queryKey: ['brainCompare'], queryFn: api.brainCompare })
  const data = compare.data
  return (
    <div className="card" style={{ marginBottom: '1.25rem' }}>
      <h2>Brain vs version 1</h2>
      <p className="stat-sub">
        The brain runs as a practice strategy next to version 1. Both are scored the same way: did the price reach
        the target before the stop? Only days when the brain ran are compared.
      </p>
      {compare.isLoading && <Loading />}
      {compare.isError && <ErrorBox error={compare.error} />}
      {data && (
        <>
          <div className="banner banner-info" style={{ margin: '0.6rem 0' }}>
            {data.note}
          </div>
          <p className="stat-sub">
            {Math.min(data.brain_finished, data.needed)} of {data.needed} brain ideas have finished. {data.needed} are
            needed before its ideas can be bought, and even then only with your OK.
          </p>
          {data.strategies.length > 0 && (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Strategy</th>
                    <th>Ideas</th>
                    <th>Finished</th>
                    <th>Reached the target</th>
                    <th>Hit the stop</th>
                    <th>Average result</th>
                  </tr>
                </thead>
                <tbody>
                  {data.strategies.map((s) => (
                    <tr key={s.name}>
                      <td>{s.is_brain ? <strong>{s.name} (brain)</strong> : s.name}</td>
                      <SummaryCells s={s} />
                    </tr>
                  ))}
                  <tr>
                    <td>
                      <em>All of version 1</em>
                    </td>
                    <SummaryCells s={data.version1} />
                  </tr>
                </tbody>
              </table>
            </div>
          )}
          {data.by_week.length > 0 && (
            <>
              <h3>By week</h3>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Week</th>
                      <th>Brain: finished</th>
                      <th>Brain: reached the target</th>
                      <th>Brain: average</th>
                      <th>Version 1: finished</th>
                      <th>Version 1: reached the target</th>
                      <th>Version 1: average</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.by_week.map((w) => (
                      <tr key={w.week}>
                        <td>{w.week}</td>
                        <td>{w.brain.finished}</td>
                        <td>{pct(w.brain.hit_rate)}</td>
                        <td>{avg(w.brain.avg_outcome_pct)}</td>
                        <td>{w.version1.finished}</td>
                        <td>{pct(w.version1.hit_rate)}</td>
                        <td>{avg(w.version1.avg_outcome_pct)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}
    </div>
  )
}
```

- [ ] **Step 3: Render it** — in `frontend/src/pages/Brain.tsx` add `import { BrainCompareCard } from '../components/BrainGoLive'` after the `HoldingTracker` import, and insert `<BrainCompareCard />` on its own line directly after the closing `</div>` of the "Learning from results" card (the `</div>` that follows `{decideProposal.isError && <ErrorBox error={decideProposal.error} />}`), before `{modules.data && (`.

- [ ] **Step 4: Type-check** — `cd frontend && npx tsc --noEmit -p .` Expected: no errors.

- [ ] **Step 5: Stage-1 smoke check (local, check DB)** — with the local API on the check DB: `swingtrade brain strategy-create`, `swingtrade brain run`, `swingtrade brain shadow-scan`; open `http://localhost:5173/brain` → "Brain vs version 1" shows the note and "0 of 30"; open Strategies → "TradeMind brain" is listed, advisory. `GET /api/v1/orders` shows no order for it.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/client.ts frontend/src/components/BrainGoLive.tsx frontend/src/pages/Brain.tsx
git commit -m "M18: console card comparing the brain with version 1"
```

---

### Task 6: The owner's stage switch with an audit row and the 30-idea gate

**Files:**
- Create: `backend/alembic/versions/20261004_0900_brain_golive_stage.py` — revision `d2a7c4e9f150`, down_revision `b4e7a1c9d352` (or the real head). Creates `brain_stage_changes`: `id` BigInteger PK; `stage` String(12) not null; `previous_stage` String(12) not null; `changed_by` String(128) not null; `reason` Text not null; `changed_at` DateTime(tz) not null server_default now(); index `ix_brain_stage_changes_changed_at` on `changed_at`. Downgrade drops it.
- Create: `backend/src/swing_trade_ml/db/models/brain_golive.py` (with `BrainStageChange`)
- Modify: `backend/src/swing_trade_ml/db/models/__init__.py` — `from swing_trade_ml.db.models.brain_golive import BrainStageChange` (+ `__all__` if the file has one)
- Create: `backend/src/swing_trade_ml/services/brain_golive/stage.py`
- Modify: `backend/src/swing_trade_ml/api/v1/endpoints/brain_golive.py` — `GET /brain/stage`, `PUT /brain/stage`
- Test: `backend/tests/test_brain_m18_stage.py`

**Interfaces:**
- Consumes: Task 4 `compare.finished_brain_ideas`, `compare.NEEDED_FINISHED`.
- Produces:
```python
# db/models/brain_golive.py
class BrainStageChange(Base):  # __tablename__ = "brain_stage_changes"
    id: int; stage: str; previous_stage: str; changed_by: str; reason: str; changed_at: datetime
# stage.py
STAGES = ("shadow", "approval", "auto")
class StageRefusedError(ValueError)
def current_stage(db: Session) -> str                      # "shadow" when no row
def set_stage(db: Session, stage: str, by: str, reason: str) -> BrainStageChange
def stage_overview(db: Session) -> dict
    # {"stage","plain","finished","needed","ready","history":[{"stage","previous_stage","changed_by","reason","changed_at"}]}
```

- [ ] **Step 1: Write the failing tests** `backend/tests/test_brain_m18_stage.py`:

```python
"""M18 task 6: the owner's stage switch — default shadow, 30 finished ideas
before leaving it, auto only after approval, every change audited, and no code
but the stage service can change it."""

from __future__ import annotations

import ast
from datetime import timedelta
from pathlib import Path

import pytest
from brain_m18_fixtures import DAY, brain_strategy, instrument, signal

from swing_trade_ml.db.models.brain_golive import BrainStageChange
from swing_trade_ml.services.brain_golive import stage

HEADERS = {"X-API-Key": "test-api-key"}


def finished_ideas(db, n: int) -> None:
    s = brain_strategy(db, name="m18-history")
    inst = instrument(db, "M18HIS", 918900)
    for i in range(n):
        signal(db, s, inst, DAY - timedelta(days=60 - i), outcome="TARGET_HIT", outcome_pct=0.08)


def test_the_stage_starts_in_shadow(db_session):
    assert stage.current_stage(db_session) == "shadow"


def test_leaving_shadow_needs_30_finished_ideas(db_session):
    finished_ideas(db_session, 29)
    with pytest.raises(stage.StageRefusedError, match="Only 29 of 30"):
        stage.set_stage(db_session, "approval", by="owner", reason="Looks good")
    assert stage.current_stage(db_session) == "shadow"


def test_auto_only_after_the_approval_stage(db_session):
    finished_ideas(db_session, 30)
    with pytest.raises(stage.StageRefusedError, match="approval stage"):
        stage.set_stage(db_session, "auto", by="owner", reason="Skip ahead")
    stage.set_stage(db_session, "approval", by="owner", reason="Enough evidence")
    stage.set_stage(db_session, "auto", by="owner", reason="Approvals went well")
    assert stage.current_stage(db_session) == "auto"


def test_every_change_is_recorded_with_who_when_and_why(db_session):
    finished_ideas(db_session, 30)
    stage.set_stage(db_session, "approval", by="owner", reason="Enough evidence")
    stage.set_stage(db_session, "shadow", by="owner", reason="Market looks rough")
    history = stage.stage_overview(db_session)["history"]
    assert [(h["previous_stage"], h["stage"], h["changed_by"], h["reason"]) for h in history] == [
        ("approval", "shadow", "owner", "Market looks rough"),
        ("shadow", "approval", "owner", "Enough evidence"),
    ]
    assert all(h["changed_at"] for h in history)


def test_a_reason_is_required_and_the_same_stage_is_refused(db_session):
    with pytest.raises(stage.StageRefusedError, match="Say why"):
        stage.set_stage(db_session, "shadow", by="owner", reason="  ")
    with pytest.raises(stage.StageRefusedError, match="already"):
        stage.set_stage(db_session, "shadow", by="owner", reason="again")


def test_nothing_but_the_stage_service_writes_a_stage_change():
    """No job, scan or endpoint may switch the brain on by itself."""
    src = Path(__file__).parents[1] / "src" / "swing_trade_ml"
    writers = set()
    for path in src.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "BrainStageChange":
                writers.add(path.relative_to(src).as_posix())
    assert writers == {"services/brain_golive/stage.py"}


def test_stage_endpoints(client):
    r = client.get("/api/v1/brain/stage", headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert (body["stage"], body["finished"], body["needed"], body["ready"]) == ("shadow", 0, 30, False)
    r = client.put("/api/v1/brain/stage", json={"stage": "approval", "reason": "try"}, headers=HEADERS)
    assert r.status_code == 409 and "Only 0 of 30" in r.json()["detail"]
    assert client.put("/api/v1/brain/stage", json={"stage": "approval", "reason": " "}, headers=HEADERS).status_code == 422
    assert client.put("/api/v1/brain/stage", json={"stage": "live", "reason": "x"}, headers=HEADERS).status_code == 422
```

- [ ] **Step 2: Run to verify failure** — `... -m pytest -q tests/test_brain_m18_stage.py`. Expected: FAIL (module missing).

- [ ] **Step 3: Implement**

`db/models/brain_golive.py`:

```python
"""M18 go-live records: the owner's stage changes and (Task 7) approvals.
Kept apart from db/models/brain.py: these rows sit next to version 1's
signals and orders, which the brain's own tables never do."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from swing_trade_ml.db.base import Base, utcnow


class BrainStageChange(Base):
    """One owner switch of the brain's trading stage. The newest row is the
    stage in force; no row means "shadow". Rows are never edited."""

    __tablename__ = "brain_stage_changes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    stage: Mapped[str] = mapped_column(String(12))  # shadow | approval | auto
    previous_stage: Mapped[str] = mapped_column(String(12))
    changed_by: Mapped[str] = mapped_column(String(128))
    reason: Mapped[str] = mapped_column(Text)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
```

Migration `20261004_0900_brain_golive_stage.py` in the style of `20261003_1200_brain_learning_runs.py` (docstring "M18 go-live: the owner's stage switch, one audited row per change", `revision = "d2a7c4e9f150"`, `down_revision = "b4e7a1c9d352"`), `op.create_table("brain_stage_changes", ...)` with the columns above (`changed_at` `server_default=sa.func.now()`), `op.create_index("ix_brain_stage_changes_changed_at", "brain_stage_changes", ["changed_at"])`; downgrade drops index and table.

`services/brain_golive/stage.py`:

```python
"""M18: the owner's switch between practice (shadow), approval and automatic.

Only `set_stage` writes a change, and only the owner endpoint calls it
(PUT /brain/stage). Nothing switches the brain on by itself
(test_nothing_but_the_stage_service_writes_a_stage_change)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.db.models.brain_golive import BrainStageChange
from swing_trade_ml.services.brain_golive.compare import NEEDED_FINISHED, finished_brain_ideas

STAGES = ("shadow", "approval", "auto")
NAMES = {"shadow": "practice (shadow)", "approval": "approval", "auto": "automatic"}
PLAIN = {
    "shadow": "Practice: the brain's ideas are recorded and scored next to version 1. Nothing is bought.",
    "approval": "Your OK needed: each brain idea waits on the Brain page. Nothing is bought until you press Approve.",
    "auto": (
        "Automatic: the brain's ideas are bought without asking, through version 1's normal safety checks. "
        "You can switch back to practice at any time."
    ),
}


class StageRefusedError(ValueError):
    """The message is shown to the owner as-is."""


def _latest(db: Session) -> BrainStageChange | None:
    return db.execute(
        select(BrainStageChange).order_by(BrainStageChange.changed_at.desc(), BrainStageChange.id.desc()).limit(1)
    ).scalar_one_or_none()


def current_stage(db: Session) -> str:
    row = _latest(db)
    return row.stage if row is not None else "shadow"


def set_stage(db: Session, stage: str, by: str, reason: str) -> BrainStageChange:
    if stage not in STAGES:
        raise StageRefusedError(f"{stage} is not a stage. Choose shadow, approval or auto.")
    reason = reason.strip()
    if not reason:
        raise StageRefusedError("Say why you are changing the stage.")
    now = current_stage(db)
    if stage == now:
        raise StageRefusedError(f"The brain is already in {NAMES[now]} mode.")
    if stage != "shadow":
        finished = finished_brain_ideas(db)
        if finished < NEEDED_FINISHED:
            raise StageRefusedError(
                f"Only {finished} of {NEEDED_FINISHED} brain ideas have finished so far. The brain stays in "
                f"practice until {NEEDED_FINISHED} have, so there is enough evidence to judge it."
            )
    if stage == "auto" and now != "approval":
        raise StageRefusedError(
            "Automatic trading can only follow the approval stage: approve the brain's ideas by hand first."
        )
    row = BrainStageChange(stage=stage, previous_stage=now, changed_by=by, reason=reason)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def stage_overview(db: Session, history_limit: int = 20) -> dict:
    stage = current_stage(db)
    finished = finished_brain_ideas(db)
    history = db.execute(
        select(BrainStageChange)
        .order_by(BrainStageChange.changed_at.desc(), BrainStageChange.id.desc())
        .limit(history_limit)
    ).scalars()
    return {
        "stage": stage,
        "plain": PLAIN[stage],
        "finished": finished,
        "needed": NEEDED_FINISHED,
        "ready": finished >= NEEDED_FINISHED,
        "history": [
            {
                "stage": h.stage,
                "previous_stage": h.previous_stage,
                "changed_by": h.changed_by,
                "reason": h.reason,
                "changed_at": h.changed_at.isoformat() if h.changed_at else None,
            }
            for h in history
        ],
    }
```

Endpoints (append to `endpoints/brain_golive.py`; add imports `HTTPException`, `BaseModel`, `Field`, `field_validator`, `stage`):

```python
class StageChange(BaseModel):
    stage: str = Field(pattern="^(shadow|approval|auto)$")
    reason: str
    by: str = "owner"

    @field_validator("reason")
    @classmethod
    def _reason_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Say why you are changing the stage.")
        return value


@router.get("/stage")
def get_stage(db: DbSession) -> dict:
    return stage.stage_overview(db)


@router.put("/stage")
def change_stage(payload: StageChange, db: DbSession) -> dict:
    """The owner's switch. Going back to practice (shadow) is always allowed."""
    try:
        stage.set_stage(db, payload.stage, by=payload.by, reason=payload.reason)
    except stage.StageRefusedError as exc:
        raise HTTPException(409, str(exc)) from exc
    return stage.stage_overview(db)
```

- [ ] **Step 4: Run to verify pass** — `tests/test_brain_m18_stage.py tests/test_brain_m18_compare.py`. Expected: pass. Also `"D:/machine learning/swing-trade-bot/backend/.venv/Scripts/python.exe" -m alembic heads` (from `backend/`) prints one head, `d2a7c4e9f150`.

- [ ] **Step 5: Lint and commit**

```bash
git add alembic/versions/20261004_0900_brain_golive_stage.py src/swing_trade_ml/db/models/brain_golive.py src/swing_trade_ml/db/models/__init__.py src/swing_trade_ml/services/brain_golive/stage.py src/swing_trade_ml/api/v1/endpoints/brain_golive.py tests/test_brain_m18_stage.py
git commit -m "M18: owner stage switch with audit rows and the 30-idea gate"
```

---

### Task 7: Approvals — pending ideas, Approve/Reject with fresh checks, automatic stage

**Files:**
- Create: `backend/alembic/versions/20261004_1000_brain_approvals.py` — revision `e8b3f1a6c247`, down_revision `d2a7c4e9f150`. Creates `brain_approvals`: `id` BigInteger PK; `signal_id` BigInteger FK `signals.id` ON DELETE CASCADE, unique; `strategy_id` Integer FK `strategies.id` ON DELETE CASCADE; `instrument_id` Integer FK `instruments.id` ON DELETE CASCADE; `symbol` String(64) not null; `decision_day` Date not null; `price` Float not null; `stop_loss` Float null; `take_profit` Float null; `suggested_qty` Integer null; `reason` Text not null default `''`; `status` String(12) not null default `pending`; `decided_by` String(128) null; `decided_at` DateTime(tz) null; `decided_note` Text null; `position_id` BigInteger FK `positions.id` ON DELETE SET NULL null; `result_note` Text null; `created_at`/`updated_at` DateTime(tz) server_default now(). Indexes on `status` and `decision_day`. Downgrade drops it.
- Modify: `backend/src/swing_trade_ml/db/models/brain_golive.py` (add `BrainApproval(Base, TimestampMixin)` mirroring the table), `db/models/__init__.py` (import it)
- Create: `backend/src/swing_trade_ml/services/brain_golive/approvals.py`
- Modify: `services/brain_golive/shadow.py` (call `approvals.after_scan` after the scan), `services/brain_golive/stage.py` (`set_stage` to shadow expires pending approvals)
- Modify: `api/v1/endpoints/brain_golive.py` (`GET /brain/approvals`, `POST /brain/approvals/{id}/approve`, `POST /brain/approvals/{id}/reject`)
- Test: `backend/tests/test_brain_m18_approvals.py`

**Interfaces:**
- Consumes: Task 1 `today_ist`, `ist_day_bounds`, `todays_decisions`, `effective_word`, `why`, `IST`; Task 6 `current_stage`; `services.execution.open_position(db, strategy, instrument, signal, quantity) -> Position | None`; `risk.check_entry(...) -> RiskDecision`; `risk.has_open_position(db, mode, instrument_id, strategy_id=None) -> bool`; `portfolio_value_and_cash(db, mode)`.
- Produces:
```python
AUTO_BY = "automatic stage"
class ApprovalError(Exception)           # message shown as-is
class ApprovalNotFound(ApprovalError)    # -> 404
class ApprovalRefused(ApprovalError)     # -> 409; nothing changed, idea stays as it was
class ApprovalExpired(ApprovalError)     # -> 409; idea is now marked expired
def expire_stale(db, today: date) -> int
def create_pending(db, today: date) -> list[BrainApproval]          # [] in shadow
def announce(created: list[BrainApproval]) -> bool                  # one Telegram message with the console link
def approve(db, approval_id: int, by: str, note: str = "", today: date | None = None) -> BrainApproval
def reject(db, approval_id: int, by: str, reason: str) -> BrainApproval
def list_approvals(db, status: str | None = None, limit: int = 50) -> list[BrainApproval]   # newest first
def auto_approve(db, today: date) -> list[BrainApproval]            # only in "auto"
def after_scan(db, today: date) -> dict                             # {"created": n, "approved": m}
def approval_out(a: BrainApproval) -> dict
```

- [ ] **Step 1: Write the failing tests** `backend/tests/test_brain_m18_approvals.py`:

```python
"""M18 task 7: in the approval stage an idea is bought only after the owner's
OK, and only if it is still fresh; the automatic stage uses the very same
checks. No broker is ever reached: open_position is replaced by a recorder."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from brain_m18_fixtures import DAY, brain_strategy, decision, instrument, no_broker, run, signal

from swing_trade_ml.core.enums import PositionStatus, SignalType
from swing_trade_ml.db.models.brain_golive import BrainApproval, BrainStageChange
from swing_trade_ml.db.models.trading import Order, Position
from swing_trade_ml.services.brain_golive import approvals, stage
from swing_trade_ml.services.risk import RiskDecision
from swing_trade_ml.strategies import brain as brain_mod

HEADERS = {"X-API-Key": "test-api-key"}


def _stage(db, name: str) -> None:
    db.add(BrainStageChange(stage=name, previous_stage="shadow", changed_by="test", reason="test"))
    db.flush()


@pytest.fixture()
def fx(db_session, monkeypatch):
    no_broker(monkeypatch)
    monkeypatch.setattr(brain_mod, "today_ist", lambda: DAY)
    monkeypatch.setattr(approvals, "current_mode", lambda: "paper")
    monkeypatch.setattr(approvals, "portfolio_value_and_cash", lambda db, mode: (1_000_000.0, 1_000_000.0))
    verdict = {"v": RiskDecision(True, 12)}
    monkeypatch.setattr(approvals.risk, "check_entry", lambda **kw: verdict["v"])
    opened: list[tuple[int, int]] = []

    def fake_open(db, strategy, instrument, sig, quantity):
        opened.append((sig.id, quantity))
        return SimpleNamespace(id=None, quantity=quantity, entry_price=sig.price)

    monkeypatch.setattr(approvals, "open_position", fake_open)
    sent: list[str] = []
    monkeypatch.setattr(approvals.notifier, "send_sync", lambda text, event="system": sent.append(text) or True)
    strategy = brain_strategy(db_session)
    inst = instrument(db_session, "M18APR", 918301)
    run(db_session, "m18-apr")
    dec = decision(db_session, "m18-apr", "M18APR", "TRADE")
    sig = signal(db_session, strategy, inst, DAY)
    return SimpleNamespace(db=db_session, strategy=strategy, inst=inst, decision=dec, signal=sig,
                           opened=opened, sent=sent, verdict=verdict)


def _pending(fx) -> BrainApproval:
    _stage(fx.db, "approval")
    (a,) = approvals.create_pending(fx.db, DAY)
    return a


def test_shadow_creates_no_approvals_and_sends_nothing(fx):
    assert approvals.after_scan(fx.db, DAY) == {"created": 0, "approved": 0}
    assert fx.sent == [] and fx.opened == []


def test_one_pending_approval_per_safe_brain_buy_of_the_day(fx):
    other = instrument(fx.db, "M18APS", 918302)
    signal(fx.db, fx.strategy, other, DAY, rejection_reason="Sector limit reached")
    signal(fx.db, fx.strategy, other, DAY, signal_type=SignalType.HOLD)
    signal(fx.db, fx.strategy, other, DAY - timedelta(days=1))
    _stage(fx.db, "approval")
    created = approvals.create_pending(fx.db, DAY)
    assert [(a.signal_id, a.symbol, a.status, a.suggested_qty) for a in created] == [
        (fx.signal.id, "M18APR", "pending", 12)
    ]
    assert approvals.create_pending(fx.db, DAY) == []


def test_a_rerun_scan_does_not_create_a_second_approval_for_the_same_stock(fx):
    signal(fx.db, fx.strategy, fx.inst, DAY, hh=17, mm=0)
    _stage(fx.db, "approval")
    assert len(approvals.create_pending(fx.db, DAY)) == 1
    assert fx.db.query(BrainApproval).filter_by(symbol="M18APR").count() == 1


def test_after_scan_announces_with_a_link_to_the_console(fx):
    _stage(fx.db, "approval")
    assert approvals.after_scan(fx.db, DAY) == {"created": 1, "approved": 0}
    (text,) = fx.sent
    assert "M18APR" in text and "/brain#approvals" in text and "Nothing is bought until you press Approve" in text


def test_stage_two_never_orders_without_an_approval(fx):
    _stage(fx.db, "approval")
    approvals.after_scan(fx.db, DAY)
    assert fx.opened == []
    assert fx.db.query(Order).filter_by(strategy_id=fx.strategy.id).count() == 0
    assert fx.db.query(BrainApproval).one().status == "pending"


def test_approve_buys_through_version_1_with_v1_sizing(fx):
    a = _pending(fx)
    done = approvals.approve(fx.db, a.id, by="owner", note="go")
    assert fx.opened == [(fx.signal.id, 12)]
    assert (done.status, done.decided_by, done.decided_note) == ("approved", "owner", "go")
    assert done.result_note.startswith("Bought 12 shares")


def test_approving_twice_orders_once(fx):
    a = _pending(fx)
    approvals.approve(fx.db, a.id, by="owner")
    with pytest.raises(approvals.ApprovalRefused, match="already approved"):
        approvals.approve(fx.db, a.id, by="owner")
    assert len(fx.opened) == 1


def test_an_idea_from_yesterday_cannot_be_approved(fx):
    a = _pending(fx)
    with pytest.raises(approvals.ApprovalExpired, match="only be approved on the day"):
        approvals.approve(fx.db, a.id, by="owner", today=DAY + timedelta(days=1))
    assert fx.db.get(BrainApproval, a.id).status == "expired" and fx.opened == []


def test_an_idea_the_owner_overruled_after_the_scan_cannot_be_approved(fx):
    a = _pending(fx)
    fx.decision.overruled_word = "WATCH"
    fx.decision.overrule_reason = "Results next week"
    fx.db.flush()
    with pytest.raises(approvals.ApprovalExpired, match="no longer says TRADE"):
        approvals.approve(fx.db, a.id, by="owner")
    assert fx.db.get(BrainApproval, a.id).status == "expired" and fx.opened == []


def test_a_stock_already_held_by_the_brain_cannot_be_bought_again(fx):
    a = _pending(fx)
    fx.db.add(Position(
        strategy_id=fx.strategy.id, instrument_id=fx.inst.id, mode="paper", status=PositionStatus.OPEN,
        quantity=5, initial_quantity=5, entry_price=100.0, entry_at=datetime.now(UTC), stop_loss=96.0,
        initial_stop_loss=96.0, take_profit=108.0, highest_price=100.0, current_price=100.0, total_charges=0.0,
    ))
    fx.db.flush()
    with pytest.raises(approvals.ApprovalExpired, match="already hold"):
        approvals.approve(fx.db, a.id, by="owner")
    assert fx.opened == []


def test_when_the_safety_check_says_no_nothing_is_bought_and_it_stays_pending(fx):
    a = _pending(fx)
    fx.verdict["v"] = RiskDecision(False, 0, "New buying is paused by the safety switch.")
    with pytest.raises(approvals.ApprovalRefused, match="paused by the safety switch"):
        approvals.approve(fx.db, a.id, by="owner")
    assert fx.db.get(BrainApproval, a.id).status == "pending" and fx.opened == []


def test_approve_in_practice_mode_is_refused(fx):
    a = _pending(fx)
    _stage(fx.db, "shadow")
    with pytest.raises(approvals.ApprovalRefused, match="practice"):
        approvals.approve(fx.db, a.id, by="owner")
    assert fx.opened == []


def test_reject_records_why_and_never_orders(fx):
    a = _pending(fx)
    with pytest.raises(approvals.ApprovalRefused, match="Say why"):
        approvals.reject(fx.db, a.id, by="owner", reason=" ")
    done = approvals.reject(fx.db, a.id, by="owner", reason="Too risky this week")
    assert (done.status, done.decided_by, done.decided_note) == ("rejected", "owner", "Too risky this week")
    with pytest.raises(approvals.ApprovalRefused):
        approvals.approve(fx.db, a.id, by="owner")
    assert fx.opened == []


def test_old_pending_ideas_expire(fx):
    a = _pending(fx)
    assert approvals.expire_stale(fx.db, DAY + timedelta(days=1)) == 1
    assert fx.db.get(BrainApproval, a.id).status == "expired"


def test_switching_back_to_shadow_expires_pending_ideas(fx, monkeypatch):
    monkeypatch.setattr(stage, "finished_brain_ideas", lambda db: 30)
    stage.set_stage(fx.db, "approval", by="owner", reason="Enough evidence")
    (a,) = approvals.create_pending(fx.db, DAY)
    stage.set_stage(fx.db, "shadow", by="owner", reason="Back to practice")
    fx.db.refresh(a)
    assert a.status == "expired" and "practice" in a.decided_note


def test_the_automatic_stage_buys_through_the_same_checks(fx):
    _stage(fx.db, "auto")
    assert approvals.after_scan(fx.db, DAY) == {"created": 1, "approved": 1}
    assert fx.opened == [(fx.signal.id, 12)]
    assert fx.db.query(BrainApproval).one().decided_by == approvals.AUTO_BY


def test_the_automatic_stage_skips_an_overruled_idea(fx):
    fx.decision.overruled_word = "WAIT"
    fx.db.flush()
    _stage(fx.db, "auto")
    assert approvals.after_scan(fx.db, DAY) == {"created": 1, "approved": 0}
    assert fx.opened == []


def test_approval_endpoints(fx, client):
    a = _pending(fx)
    listed = client.get("/api/v1/brain/approvals", params={"status": "pending"}, headers=HEADERS).json()
    assert [x["id"] for x in listed] == [a.id] and listed[0]["symbol"] == "M18APR"
    r = client.post(f"/api/v1/brain/approvals/{a.id}/approve", json={"note": "ok"}, headers=HEADERS)
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert client.post(f"/api/v1/brain/approvals/{a.id}/approve", json={}, headers=HEADERS).status_code == 409
    assert client.post("/api/v1/brain/approvals/999999999/approve", json={}, headers=HEADERS).status_code == 404
    assert client.post(f"/api/v1/brain/approvals/{a.id}/reject", json={"reason": " "}, headers=HEADERS).status_code == 422
```

- [ ] **Step 2: Run to verify failure** — `... -m pytest -q tests/test_brain_m18_approvals.py`. Expected: FAIL (import of `BrainApproval` / `approvals`).

- [ ] **Step 3: Implement**

Model (append to `db/models/brain_golive.py`; add imports `Date, Float, ForeignKey, Index, Integer`, `date`, `TimestampMixin`):

```python
class BrainApproval(Base, TimestampMixin):
    """One brain idea waiting for (or decided by) the owner's OK (M18 stage 2)."""

    __tablename__ = "brain_approvals"
    __table_args__ = (
        Index("ix_brain_approvals_status", "status"),
        Index("ix_brain_approvals_decision_day", "decision_day"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id", ondelete="CASCADE"), unique=True)
    strategy_id: Mapped[int] = mapped_column(ForeignKey("strategies.id", ondelete="CASCADE"))
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id", ondelete="CASCADE"))
    symbol: Mapped[str] = mapped_column(String(64))
    decision_day: Mapped[date] = mapped_column(Date)
    price: Mapped[float] = mapped_column(Float)
    stop_loss: Mapped[float | None] = mapped_column(Float)
    take_profit: Mapped[float | None] = mapped_column(Float)
    suggested_qty: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(12), default="pending")  # pending | approved | rejected | expired
    decided_by: Mapped[str | None] = mapped_column(String(128))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_note: Mapped[str | None] = mapped_column(Text)
    position_id: Mapped[int | None] = mapped_column(ForeignKey("positions.id", ondelete="SET NULL"))
    result_note: Mapped[str | None] = mapped_column(Text)
```

`services/brain_golive/approvals.py`:

```python
"""M18 stages 2 and 3: the owner's OK before a brain idea is bought.

The scan path never orders for the brain ("brain" is always advisory there,
core/strategy_policy.py). This module is the ONLY place an order is placed for
it, and only through services.execution.open_position after fresh checks. The
automatic stage is this same path with the system pressing Approve; only the
owner can choose that stage (stage.py)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from swing_trade_ml.brokers import current_mode
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import SignalType
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.brain_golive import BrainApproval
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Signal, Strategy
from swing_trade_ml.notifications import notifier
from swing_trade_ml.services import risk
from swing_trade_ml.services.brain_golive.stage import current_stage
from swing_trade_ml.services.execution import open_position
from swing_trade_ml.services.portfolio import portfolio_value_and_cash
from swing_trade_ml.strategies import brain as brain_strategy

log = get_logger(__name__)

AUTO_BY = "automatic stage"
STALE_NOTE = "Not approved on the day the idea was made — an idea is only good for that day."
STATUS_PLAIN = {"pending": "Waiting for your OK", "approved": "Approved", "rejected": "Rejected", "expired": "Expired"}


class ApprovalError(Exception):
    """The message is shown to the owner as-is."""


class ApprovalNotFound(ApprovalError):
    pass


class ApprovalRefused(ApprovalError):
    """Nothing changed; the idea stays as it was."""


class ApprovalExpired(ApprovalError):
    """The idea can no longer be bought; it is now marked expired."""


def _now() -> datetime:
    return datetime.now(UTC)


def _get(db: Session, approval_id: int) -> BrainApproval:
    a = db.get(BrainApproval, approval_id)
    if a is None:
        raise ApprovalNotFound(f"No idea {approval_id} is waiting for approval.")
    return a


def _expire(db: Session, a: BrainApproval, note: str, by: str = "system") -> None:
    a.status, a.decided_by, a.decided_at, a.decided_note = "expired", by, _now(), note
    db.commit()


def expire_stale(db: Session, today: date) -> int:
    n = db.execute(
        update(BrainApproval)
        .where(BrainApproval.status == "pending", BrainApproval.decision_day < today)
        .values(status="expired", decided_by="system", decided_at=_now(), decided_note=STALE_NOTE)
    ).rowcount
    db.commit()
    return n or 0


def create_pending(db: Session, today: date) -> list[BrainApproval]:
    if current_stage(db) == "shadow":
        return []
    expire_stale(db, today)
    start, end = brain_strategy.ist_day_bounds(today)
    taken = {s for (s,) in db.execute(select(BrainApproval.symbol).where(BrainApproval.decision_day == today))}
    rows = db.execute(
        select(Signal, Instrument.tradingsymbol)
        .join(Strategy, Strategy.id == Signal.strategy_id)
        .join(Instrument, Instrument.id == Signal.instrument_id)
        .where(
            Strategy.strategy_type == "brain",
            Strategy.is_active.is_(True),
            Signal.signal_type == SignalType.BUY,
            Signal.advisory_only.is_(True),
            Signal.rejection_reason.is_(None),
            Signal.generated_at >= start,
            Signal.generated_at < end,
        )
        .order_by(Signal.generated_at.desc())
    ).all()
    created: list[BrainApproval] = []
    for sig, symbol in rows:
        if symbol in taken:  # one per stock per day; the newest scan's signal wins
            continue
        taken.add(symbol)
        a = BrainApproval(
            signal_id=sig.id, strategy_id=sig.strategy_id, instrument_id=sig.instrument_id, symbol=symbol,
            decision_day=today, price=sig.price, stop_loss=sig.stop_loss, take_profit=sig.take_profit,
            suggested_qty=sig.suggested_quantity, reason=sig.reason or "", status="pending",
        )
        db.add(a)
        created.append(a)
    db.commit()
    return created


def announce(created: list[BrainApproval]) -> bool:
    if not created:
        return False
    n = len(created)
    names = ", ".join(a.symbol for a in created)
    text = (
        f"🧠 The brain has {n} idea{'s' if n != 1 else ''} waiting for your OK: {names}.\n"
        "Nothing is bought until you press Approve. Ideas not approved today expire at midnight.\n"
        f"Open: {settings.FRONTEND_URL.rstrip('/')}/brain#approvals"
    )
    return notifier.send_sync(text, "signal")


def _no_longer_trade(db: Session, a: BrainApproval, book: str, today: date) -> str | None:
    """None while the brain still says TRADE for this stock today; else why not."""
    run, decisions = brain_strategy.todays_decisions(db, today, book)
    d = decisions.get(a.symbol)
    if run is None or d is None:
        return f"The brain has no decision for {a.symbol} today."
    word = brain_strategy.effective_word(d)
    if d.kind != "idea" or word != "TRADE":
        return f"The brain no longer says TRADE for {a.symbol} today ({word}): {brain_strategy.why(d)}"
    return None


def approve(db: Session, approval_id: int, by: str, note: str = "", today: date | None = None) -> BrainApproval:
    today = today or brain_strategy.today_ist()
    a = _get(db, approval_id)
    if a.status != "pending":
        raise ApprovalRefused(f"This idea is already {a.status}.")
    if current_stage(db) == "shadow":
        raise ApprovalRefused(
            "The brain is in practice mode (shadow), so nothing can be bought. Switch to the approval stage first."
        )
    if a.decision_day != today:
        _expire(db, a, STALE_NOTE)
        raise ApprovalExpired(
            f"This idea was made on {a.decision_day:%d %b %Y}; ideas can only be approved on the day they were made."
        )
    strategy = db.get(Strategy, a.strategy_id)
    instrument = db.get(Instrument, a.instrument_id)
    signal = db.get(Signal, a.signal_id)
    mode = current_mode()
    if strategy is None or not strategy.is_active:
        raise ApprovalRefused("The brain strategy is switched off.")
    if strategy.mode != mode:
        raise ApprovalRefused(f"The brain strategy is set up for {strategy.mode} trading but the app is in {mode} mode.")
    gone = _no_longer_trade(db, a, strategy.mode, today)
    if gone:
        _expire(db, a, gone)
        raise ApprovalExpired(gone)
    if risk.has_open_position(db, mode, a.instrument_id, strategy_id=strategy.id):
        msg = f"You already hold {a.symbol} through the brain."
        _expire(db, a, msg)
        raise ApprovalExpired(msg)
    total, cash = portfolio_value_and_cash(db, mode)
    verdict = risk.check_entry(
        db=db, mode=mode, instrument_id=a.instrument_id, price=signal.price, stop_loss=signal.stop_loss,
        portfolio_value=total, available_cash=cash, strategy=strategy,
    )
    if not verdict.allowed:
        raise ApprovalRefused(f"The safety check says no right now: {verdict.reason}")
    # Claim first: of two Approve presses only one can move the row off "pending".
    claimed = db.execute(
        update(BrainApproval)
        .where(BrainApproval.id == a.id, BrainApproval.status == "pending")
        .values(status="approved", decided_by=by, decided_at=_now(), decided_note=note.strip() or None)
    ).rowcount
    db.commit()
    if claimed != 1:
        raise ApprovalRefused("This idea was already decided.")
    db.refresh(a)
    position = open_position(db, strategy, instrument, signal, verdict.quantity)
    a.position_id = position.id if position is not None else None
    a.result_note = (
        f"Bought {position.quantity} shares at ₹{position.entry_price:,.2f}."
        if position is not None
        else f"The order was sent but did not fill: {signal.rejection_reason or 'no reason given'}."
    )
    db.commit()
    log.info("brain_golive.approval.approved", symbol=a.symbol, by=by, filled=position is not None)
    return a


def reject(db: Session, approval_id: int, by: str, reason: str) -> BrainApproval:
    a = _get(db, approval_id)
    if a.status != "pending":
        raise ApprovalRefused(f"This idea is already {a.status}.")
    reason = reason.strip()
    if not reason:
        raise ApprovalRefused("Say why you are rejecting this idea.")
    a.status, a.decided_by, a.decided_at, a.decided_note = "rejected", by, _now(), reason
    db.commit()
    return a


def list_approvals(db: Session, status: str | None = None, limit: int = 50) -> list[BrainApproval]:
    stmt = select(BrainApproval).order_by(BrainApproval.id.desc()).limit(limit)
    if status:
        stmt = stmt.where(BrainApproval.status == status)
    return list(db.execute(stmt).scalars())


def auto_approve(db: Session, today: date) -> list[BrainApproval]:
    if current_stage(db) != "auto":
        return []
    done: list[BrainApproval] = []
    pending = db.execute(
        select(BrainApproval.id)
        .where(BrainApproval.status == "pending", BrainApproval.decision_day == today)
        .order_by(BrainApproval.id)
    ).scalars().all()
    for approval_id in pending:
        try:
            done.append(approve(db, approval_id, by=AUTO_BY, today=today))
        except ApprovalError as exc:
            log.info("brain_golive.approval.auto_skipped", approval_id=approval_id, reason=str(exc))
    return done


def after_scan(db: Session, today: date) -> dict:
    created = create_pending(db, today)
    stage_now = current_stage(db)
    if stage_now == "approval":
        announce(created)
    approved = auto_approve(db, today) if stage_now == "auto" else []
    return {"created": len(created), "approved": len(approved)}


def approval_out(a: BrainApproval) -> dict:
    return {
        "id": a.id,
        "symbol": a.symbol,
        "decision_day": a.decision_day.isoformat(),
        "price": a.price,
        "stop_loss": a.stop_loss,
        "take_profit": a.take_profit,
        "suggested_qty": a.suggested_qty,
        "reason": a.reason,
        "status": a.status,
        "status_plain": STATUS_PLAIN.get(a.status, a.status),
        "decided_by": a.decided_by,
        "decided_at": a.decided_at.isoformat() if a.decided_at else None,
        "decided_note": a.decided_note,
        "position_id": a.position_id,
        "result_note": a.result_note,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }
```

`shadow.py` — import `from swing_trade_ml.services.brain_golive import approvals` and, just before the final `log.info`, add:

```python
    if combined.strategies_run:
        outcome = approvals.after_scan(db, today)
        log.info("brain_golive.approvals.after_scan", **outcome)
```

`stage.py::set_stage` — add imports `from datetime import UTC, datetime`, `from sqlalchemy import select, update` and `from swing_trade_ml.db.models.brain_golive import BrainApproval, BrainStageChange`; before `db.add(row)`:

```python
    if stage == "shadow":
        db.execute(
            update(BrainApproval)
            .where(BrainApproval.status == "pending")
            .values(status="expired", decided_by=by, decided_at=datetime.now(UTC),
                    decided_note="Switched back to practice mode (shadow), so nothing is bought.")
        )
```

Endpoints (append to `endpoints/brain_golive.py`; import `from swing_trade_ml.services.brain_golive import approvals` and `from swing_trade_ml.strategies import brain as brain_strategy` — call `brain_strategy.today_ist()` through the module so tests can pin the day):

```python
class ApprovalDecision(BaseModel):
    note: str = ""
    by: str = "owner"


class ApprovalRejection(BaseModel):
    reason: str
    by: str = "owner"

    @field_validator("reason")
    @classmethod
    def _reason_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Say why you are rejecting this idea.")
        return value


@router.get("/approvals")
def list_approvals(db: DbSession, status: str | None = Query(None, pattern="^(pending|approved|rejected|expired)$")) -> list[dict]:
    approvals.expire_stale(db, brain_strategy.today_ist())
    return [approvals.approval_out(a) for a in approvals.list_approvals(db, status)]


@router.post("/approvals/{approval_id}/approve")
def approve(approval_id: int, payload: ApprovalDecision, db: DbSession) -> dict:
    try:
        return approvals.approval_out(approvals.approve(db, approval_id, by=payload.by, note=payload.note))
    except approvals.ApprovalNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except approvals.ApprovalError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/approvals/{approval_id}/reject")
def reject(approval_id: int, payload: ApprovalRejection, db: DbSession) -> dict:
    try:
        return approvals.approval_out(approvals.reject(db, approval_id, by=payload.by, reason=payload.reason))
    except approvals.ApprovalNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except approvals.ApprovalError as exc:
        raise HTTPException(409, str(exc)) from exc
```

Migration `20261004_1000_brain_approvals.py` per the Files bullet (verified types: `signals.id` and `positions.id` are BigInteger, `strategies.id` and `instruments.id` are Integer).

- [ ] **Step 4: Run to verify pass** — `tests/test_brain_m18_approvals.py tests/test_brain_m18_stage.py tests/test_brain_m18_shadow.py tests/test_brain_m18_guard.py`. Expected: pass. `alembic heads` → `e8b3f1a6c247`.

- [ ] **Step 5: Lint and commit**

```bash
git add alembic/versions/20261004_1000_brain_approvals.py src/swing_trade_ml/db/models/brain_golive.py src/swing_trade_ml/db/models/__init__.py src/swing_trade_ml/services/brain_golive src/swing_trade_ml/api/v1/endpoints/brain_golive.py tests/test_brain_m18_approvals.py
git commit -m "M18: approvals - nothing is bought without the owner's fresh OK"
```

---

### Task 8: Console stage switch and approvals, rollback doc, real check, notes

**Files:**
- Modify: `frontend/src/api/types.ts`, `frontend/src/api/client.ts`, `frontend/src/components/BrainGoLive.tsx`, `frontend/src/pages/Brain.tsx`
- Create: `docs/brain/GO_LIVE.md`
- Modify: `docs/brain/BUILD_NOTES.md` (Status row for M18, lessons)

**Interfaces:**
- Consumes: `GET/PUT /brain/stage` (Task 6), `GET /brain/approvals`, `POST …/approve`, `POST …/reject` (Task 7).
- Produces: types `BrainStageName`, `BrainStageChange`, `BrainStage`, `BrainApprovalStatus`, `BrainApproval`; client `brainStage`, `brainSetStage`, `brainApprovals`, `brainApprove`, `brainReject`; components `BrainStageCard`, `BrainApprovalsCard`.

- [ ] **Step 1: Types and client**

```ts
export type BrainStageName = 'shadow' | 'approval' | 'auto'

export interface BrainStageChange {
  stage: BrainStageName
  previous_stage: BrainStageName
  changed_by: string
  reason: string
  changed_at: string
}

export interface BrainStage {
  stage: BrainStageName
  plain: string
  finished: number
  needed: number
  ready: boolean
  history: BrainStageChange[]
}

export type BrainApprovalStatus = 'pending' | 'approved' | 'rejected' | 'expired'

export interface BrainApproval {
  id: number
  symbol: string
  decision_day: string
  price: number
  stop_loss: number | null
  take_profit: number | null
  suggested_qty: number | null
  reason: string
  status: BrainApprovalStatus
  status_plain: string
  decided_by: string | null
  decided_at: string | null
  decided_note: string | null
  position_id: number | null
  result_note: string | null
  created_at: string | null
}
```

```ts
  brainStage: () => get<BrainStage>('/brain/stage'),
  brainSetStage: (stage: BrainStageName, reason: string) => put<BrainStage>('/brain/stage', { stage, reason }),
  brainApprovals: () => get<BrainApproval[]>('/brain/approvals'),
  brainApprove: (id: number, note: string) => post<BrainApproval>(`/brain/approvals/${id}/approve`, { note }),
  brainReject: (id: number, reason: string) => post<BrainApproval>(`/brain/approvals/${id}/reject`, { reason }),
```

- [ ] **Step 2: Components** (append to `BrainGoLive.tsx`; change the first import to `import { useState } from 'react'` + `import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'`; import the new types and `formatCurrency, formatDateTime`):

```tsx
const STAGE_TITLE: Record<BrainStageName, string> = {
  shadow: 'Practice (shadow)',
  approval: 'Your OK needed',
  auto: 'Automatic',
}

export function BrainStageCard() {
  const queryClient = useQueryClient()
  const stage = useQuery({ queryKey: ['brainStage'], queryFn: api.brainStage })
  const [target, setTarget] = useState<BrainStageName>('shadow')
  const [reason, setReason] = useState('')
  const change = useMutation({
    mutationFn: () => api.brainSetStage(target, reason),
    onSuccess: () => {
      setReason('')
      void queryClient.invalidateQueries({ queryKey: ['brainStage'] })
      void queryClient.invalidateQueries({ queryKey: ['brainApprovals'] })
    },
  })
  const s = stage.data
  const allowed = (name: BrainStageName): boolean =>
    !!s && name !== s.stage && (name === 'shadow' || (s.ready && (name === 'approval' || s.stage === 'approval')))
  return (
    <div className="card" style={{ marginBottom: '1.25rem' }}>
      <h2>Trading stage</h2>
      {stage.isLoading && <Loading />}
      {stage.isError && <ErrorBox error={stage.error} />}
      {s && (
        <>
          <p>
            <strong>Now: {STAGE_TITLE[s.stage]}</strong> — {s.plain}
          </p>
          <p className="stat-sub">
            {Math.min(s.finished, s.needed)} of {s.needed} brain ideas have finished.{' '}
            {s.ready
              ? 'That is enough evidence to move on, if you choose to.'
              : `The brain stays in practice until ${s.needed} have finished.`}{' '}
            Going back to practice is always allowed and takes effect at once.
          </p>
          <div className="brain-overrule">
            <select
              value={target}
              onChange={(e) => setTarget(e.target.value as BrainStageName)}
              aria-label="New stage"
            >
              {(['shadow', 'approval', 'auto'] as BrainStageName[]).map((name) => (
                <option key={name} value={name} disabled={!allowed(name)}>
                  {STAGE_TITLE[name]}
                </option>
              ))}
            </select>
            <input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Why? e.g. 30 ideas look good"
              aria-label="Reason for the change"
            />
            <button
              className="primary"
              disabled={!allowed(target) || !reason.trim() || change.isPending}
              onClick={() => change.mutate()}
            >
              {change.isPending ? 'Saving…' : 'Change stage'}
            </button>
          </div>
          {change.isError && <ErrorBox error={change.error} />}
          {s.history.length > 0 && (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>When</th>
                    <th>Change</th>
                    <th>By</th>
                    <th>Why</th>
                  </tr>
                </thead>
                <tbody>
                  {s.history.map((h) => (
                    <tr key={h.changed_at + h.stage}>
                      <td>{formatDateTime(h.changed_at)}</td>
                      <td>
                        {STAGE_TITLE[h.previous_stage]} → {STAGE_TITLE[h.stage]}
                      </td>
                      <td>{h.changed_by}</td>
                      <td>{h.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function ApprovalRow({ a, busy, onApprove, onReject }: {
  a: BrainApproval
  busy: boolean
  onApprove: (id: number, note: string) => void
  onReject: (id: number, reason: string) => void
}) {
  const [text, setText] = useState('')
  return (
    <tr>
      <td>
        <strong>{a.symbol}</strong>
        <div className="stat-sub">{a.reason}</div>
      </td>
      <td>
        {formatCurrency(a.price)}
        <div className="stat-sub">
          {a.stop_loss !== null && `Stop ${formatCurrency(a.stop_loss)}`}
          {a.take_profit !== null && ` · Target ${formatCurrency(a.take_profit)}`}
          {a.suggested_qty !== null && ` · about ${a.suggested_qty} shares`}
        </div>
      </td>
      <td>
        {a.status_plain}
        {a.decided_note && <div className="stat-sub">“{a.decided_note}”</div>}
        {a.result_note && <div className="stat-sub">{a.result_note}</div>}
      </td>
      <td>
        {a.status === 'pending' && (
          <div className="brain-overrule">
            <input
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Note (needed to reject)"
              aria-label={`Note for ${a.symbol}`}
            />
            <button className="primary" disabled={busy} onClick={() => onApprove(a.id, text)}>
              Approve
            </button>
            <button disabled={busy || !text.trim()} onClick={() => onReject(a.id, text)}>
              Reject
            </button>
          </div>
        )}
      </td>
    </tr>
  )
}

export function BrainApprovalsCard() {
  const queryClient = useQueryClient()
  const list = useQuery({ queryKey: ['brainApprovals'], queryFn: api.brainApprovals })
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['brainApprovals'] })
    void queryClient.invalidateQueries({ queryKey: ['brainCompare'] })
  }
  const approve = useMutation({
    mutationFn: ({ id, note }: { id: number; note: string }) => api.brainApprove(id, note),
    onSuccess: refresh,
    onError: refresh,
  })
  const reject = useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) => api.brainReject(id, reason),
    onSuccess: refresh,
  })
  return (
    <div className="card" id="approvals" style={{ marginBottom: '1.25rem' }}>
      <h2>Waiting for your OK</h2>
      <p className="stat-sub">
        In the “Your OK needed” stage, each brain idea waits here. Approve checks again that the idea is from today,
        that the brain still likes it and that the safety rules allow it — only then is it bought. Ideas not approved
        today expire at midnight.
      </p>
      {list.isLoading && <Loading />}
      {list.isError && <ErrorBox error={list.error} />}
      {list.data && list.data.length === 0 && <Empty label="Nothing is waiting." />}
      {list.data && list.data.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Stock</th>
                <th>Price</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {list.data.map((a) => (
                <ApprovalRow
                  key={a.id}
                  a={a}
                  busy={approve.isPending || reject.isPending}
                  onApprove={(id, note) => approve.mutate({ id, note })}
                  onReject={(id, reason) => reject.mutate({ id, reason })}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
      {approve.isError && <ErrorBox error={approve.error} />}
      {reject.isError && <ErrorBox error={reject.error} />}
    </div>
  )
}
```
(Import `Empty` from `./Loading` too.) In `Brain.tsx`, import `{ BrainApprovalsCard, BrainCompareCard, BrainStageCard }` and render `<BrainStageCard />` and `<BrainApprovalsCard />` directly after `<BrainCompareCard />`. Run `cd frontend && npx tsc --noEmit -p .` → no errors.

- [ ] **Step 3: Rollback documentation** — create `docs/brain/GO_LIVE.md` with these sections (plain English): **What the three stages mean** (copy `stage.PLAIN`); **How to move on** (Brain page → Trading stage; needs 30 finished ideas; automatic only after approval; a reason is always required and every change is recorded with who/when/why); **How to go back (rollback)** — one switch: Brain page → Trading stage → "Practice (shadow)" with a reason (or `PUT /api/v1/brain/stage {"stage":"shadow","reason":"..."}`); takes effect at once; ideas waiting for approval expire; shares already bought through the brain are NOT sold — version 1's stop, target and time stop keep protecting them, or sell them from the Positions page; **Switching M18 off completely** — deactivate the "TradeMind brain" strategy on the Strategies page (its ideas stop being recorded; the brain stays advisory only); **Last resort** — version 1 is tagged `v1` (`64fcb05`), the frozen rollback point; **What Telegram sends** (one message per evening listing ideas waiting, with the link; no buttons in Telegram).

- [ ] **Step 4: Real check (controller, local only)** — on the check DB (`brain_m00_check`): `alembic upgrade head`; restart the API on :8001; `swingtrade brain strategy-create`; `swingtrade brain run`; `swingtrade brain shadow-scan`. Verify: brain signals recorded for the watchlist (BUYs only for TRADE ideas), zero new rows in `orders` for the brain strategy, `/brain/compare` note, `/brain/stage` says shadow and "N of 30", `PUT /brain/stage` to approval returns 409 "Only N of 30". On `http://localhost:5173/brain` the three new cards render and "Approve" is never shown in shadow. Full suite: `tests/` (clean env), `ruff check` on created files, `npx tsc --noEmit -p .`.

- [ ] **Step 5: Notes and commit** — add the M18 row to the BUILD_NOTES Status table (branch `brain/m18-golive`; what each stage does; files) and lessons (the 15:45 scan vs 15:50 brain run timing; signal `horizon_days` is scored in calendar days by v1's evaluator; brain excluded from slot share). Commit:

```bash
git add frontend/src docs/brain/GO_LIVE.md docs/brain/BUILD_NOTES.md
git commit -m "M18: console stage switch and approvals, rollback guide, notes"
```

---

## Spec conflicts and open questions for the owner

1. **Timing (resolved in this plan, needs the owner's nod):** v1's scan runs at 15:45 IST, the brain's nightly run at 15:50, so the spec's "run the v1 scan (`swingtrade scan`)" would always see "No brain run today". The plan runs the brain strategy right after the nightly brain run and leaves it out of the 15:45 scan; the Done-when check uses `swingtrade brain shadow-scan`.
2. **"Approve on the same IST day" vs after-close ideas:** brain ideas appear around 15:55 IST, after the market has closed. Same-day approval therefore places the order after the close (paper fills at the last price; live Kite after-close orders are an open v1 blocker). Should approvals stay valid until the next session's close instead? One-line change (`approve()`'s day check and `expire_stale`).
3. **Scoring horizon:** v1's `evaluate_pending_signals` treats `horizon_days` as calendar days, so a 15-trading-day brain idea is scored over 15 calendar days (~10–11 trading days), unlike M09's own +8%/−4%/15-trading-day grading. v1 strategies have the same quirk, so the comparison is fair, but the two "brain hit rates" will differ.
4. **Spec says "No new tables"**, but the owner's decisions (pending approvals, audited stage switch) need two: `brain_stage_changes` and `brain_approvals`.
5. **Spec's comparison also lists "return after costs" and "drawdown"**; the decided scope is hit rate, average outcome %, count, by week. Costs and drawdown are left out (shadow ideas have no trades to cost).
6. **Stage 3 behaviour:** the plan makes "auto" = the system pressing Approve through the same checks right after the evening scan; it is allowed only from the approval stage, with no extra evidence bar. Does the owner want a further bar (e.g. N approved trades) before auto can be chosen?
7. **Exits:** positions opened through an approval get v1's automatic stop/target/time-stop sells (not alerts only). Rolling back to shadow does not sell them.
8. **"Owner":** the app has no owner role; like the overrule endpoint, any authenticated caller is the owner and `by` defaults to "owner".
