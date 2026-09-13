# Scan Results (Signal Track Record) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every `Signal` with a stop/target gets scored (target hit / stop hit / expired) against real intraday price action, whether or not it was ever executed, and shown in a new "Scan Results" tab with cap tier, live current price, and a click-through detail popup — replacing the Search page.

**Architecture:** Three new nullable columns on `Signal`, a scoring function mirroring the existing `evaluate_pending_predictions`, a daily job, one new read endpoint, and one new frontend tab. No new tables.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, APScheduler, pytest, React, TanStack Query, existing `Modal`/`icons.tsx` components.

**Spec:** `docs/superpowers/specs/2026-09-12-signal-track-record-design.md`

## Global Constraints

- Score using candle **high/low**, never close — a stop/target order triggers intraday (spec §6).
- A same-day double-touch (both stop and target crossed by one candle's range) resolves to `STOP_LOSS_HIT` — the conservative assumption (spec §6).
- `horizon_days` is copied onto the `Signal` at generation time, never looked up from the model later (spec §5).
- No pagination in v1 (spec §8) — current signal volume is small.
- Search.tsx and its `/search` route are removed, not just unlinked (spec §9 amendment).

---

### Task 1: Signal outcome columns + migration

**Files:**
- Modify: `backend/src/swing_trade_ml/db/models/trading.py` (the `Signal` class, currently ends around line 133)
- Create: `backend/alembic/versions/<timestamp>_signal_outcome_columns.py`
- Test: `backend/tests/test_signal_scoring.py` (new file — this task only adds a model-shape test; scoring logic tests come in Task 2)

**Interfaces:**
- Produces: `Signal.horizon_days: int`, `Signal.outcome: str | None`, `Signal.outcome_pct: float | None`, `Signal.outcome_at: datetime | None` — every later task in this plan reads/writes these exact names.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_signal_scoring.py
"""Outcome scoring for Signal rows — see docs/superpowers/specs/2026-09-12-signal-track-record-design.md."""

from __future__ import annotations

from datetime import UTC, datetime

from swing_trade_ml.core.enums import SignalType
from swing_trade_ml.db.models.trading import Signal


def test_signal_has_outcome_columns(db_session):
    """New columns exist, default to unscored, and round-trip through a commit."""
    signal = Signal(
        strategy_id=1,
        instrument_id=1,
        signal_type=SignalType.BUY,
        mode="paper",
        price=100.0,
        stop_loss=90.0,
        take_profit=120.0,
        horizon_days=10,
        generated_at=datetime.now(UTC),
    )
    db_session.add(signal)
    db_session.flush()

    assert signal.horizon_days == 10
    assert signal.outcome is None
    assert signal.outcome_pct is None
    assert signal.outcome_at is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_signal_scoring.py -v`
Expected: FAIL — `TypeError: 'horizon_days' is an invalid keyword argument for Signal` (column doesn't exist yet)

- [ ] **Step 3: Add the columns to the model**

In `backend/src/swing_trade_ml/db/models/trading.py`, find the `Signal` class (`generated_at: Mapped[datetime]` is its last field before the relationships). Add directly above the `generated_at` line:

```python
    # Outcome scoring — see ml/predict.py::evaluate_pending_signals. Only
    # signals with both stop_loss and take_profit set are ever scored;
    # horizon_days is copied from the model/strategy at generation time so
    # scoring stays correct even after the active model later changes.
    horizon_days: Mapped[int | None] = mapped_column(Integer)
    outcome: Mapped[str | None] = mapped_column(String(24), index=True)
    outcome_pct: Mapped[float | None] = mapped_column(Float)
    outcome_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_signal_scoring.py -v`
Expected: PASS

- [ ] **Step 5: Generate and edit the Alembic migration**

Run: `cd backend && alembic revision -m "signal_outcome_columns"`

This creates a new file under `backend/alembic/versions/` with an auto-generated revision id and `down_revision` set to the current head. Open it and replace the body with:

```python
"""signal_outcome_columns

Revision ID: <the generated id — leave as-is>
Revises: <the generated down_revision — leave as-is>
Create Date: <the generated date — leave as-is>
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "<the generated id>"
down_revision: str | None = "<the generated down_revision>"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("signals", sa.Column("horizon_days", sa.Integer(), nullable=True))
    op.add_column("signals", sa.Column("outcome", sa.String(length=24), nullable=True))
    op.add_column("signals", sa.Column("outcome_pct", sa.Float(), nullable=True))
    op.add_column(
        "signals", sa.Column("outcome_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index("ix_signals_outcome", "signals", ["outcome"])


def downgrade() -> None:
    op.drop_index("ix_signals_outcome", table_name="signals")
    op.drop_column("signals", "outcome_at")
    op.drop_column("signals", "outcome_pct")
    op.drop_column("signals", "outcome")
    op.drop_column("signals", "horizon_days")
```

Do not hand-write the revision id — use exactly what `alembic revision` generated so `down_revision` chains correctly onto the real current head.

- [ ] **Step 6: Verify the migration applies**

Run: `cd backend && alembic upgrade head` (against the local dev Postgres — `docker compose up -d postgres` if it isn't already running)
Expected: no errors; `alembic current` shows the new revision as head.

- [ ] **Step 7: Commit**

```bash
git add backend/src/swing_trade_ml/db/models/trading.py backend/alembic/versions/ backend/tests/test_signal_scoring.py
git commit -m "feat: add outcome scoring columns to Signal

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: Set `horizon_days` at signal generation time

**Files:**
- Modify: `backend/src/swing_trade_ml/strategies/ml_swing.py` (the `SignalDecision(signal=SignalType.BUY, ...)` return, currently ~line 196)
- Modify: `backend/src/swing_trade_ml/strategies/sma_crossover.py` (the `SignalDecision` construction with `stop_loss`/`take_profit`, ~line 130)
- Modify: `backend/src/swing_trade_ml/strategies/base.py` (`SignalDecision` dataclass)
- Test: `backend/tests/test_signal_scoring.py`

**Interfaces:**
- Consumes: `SignalDecision` dataclass (Task's own modification)
- Produces: `SignalDecision.horizon_days: int | None` — the field the engine service copies onto the persisted `Signal` row (Task 2 also updates that copy site).

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_signal_scoring.py`:

```python
def test_signal_decision_carries_horizon_days():
    """SignalDecision must be able to carry a horizon so strategies can set
    it — this is a shape test; per-strategy value tests are separate."""
    from swing_trade_ml.core.enums import SignalType
    from swing_trade_ml.strategies.base import SignalDecision

    decision = SignalDecision(
        signal=SignalType.BUY,
        price=100.0,
        stop_loss=90.0,
        take_profit=120.0,
        horizon_days=10,
    )
    assert decision.horizon_days == 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_signal_scoring.py::test_signal_decision_carries_horizon_days -v`
Expected: FAIL — `TypeError: SignalDecision.__init__() got an unexpected keyword argument 'horizon_days'`

- [ ] **Step 3: Add the field to `SignalDecision`**

In `backend/src/swing_trade_ml/strategies/base.py`, add to the `SignalDecision` dataclass, after `take_profit`:

```python
    take_profit: float | None = None
    horizon_days: int | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_signal_scoring.py::test_signal_decision_carries_horizon_days -v`
Expected: PASS

- [ ] **Step 5: Set it in `ml_swing.py`**

In `backend/src/swing_trade_ml/strategies/ml_swing.py`, the final `return SignalDecision(...)` for the `BUY` case (with `stop_loss=round(stop_loss, 2), take_profit=round(take_profit, 2),`) — add a line setting `horizon_days=model.prediction_horizon_days,` right after `take_profit=round(take_profit, 2),`.

- [ ] **Step 6: Set it in `sma_crossover.py`**

In `backend/src/swing_trade_ml/strategies/sma_crossover.py`, add a new default param and use it at the `SignalDecision` construction that sets `stop_loss`/`take_profit` (~line 130-134). First, find that strategy's `default_params: ClassVar[dict[str, Any]]` block and add:

```python
        # No ML model to read a trained horizon from — 15 trading days is
        # this strategy's own SMA-crossover-appropriate hold window, roughly
        # matching the swing model's own horizon range.
        "horizon_days": 15,
```

Then in the `SignalDecision(...)` call that sets `stop_loss=round(price * (1 - stop_pct), 2), take_profit=round(price * (1 + target_pct), 2),`, add directly after: `horizon_days=int(self.params["horizon_days"]),`.

- [ ] **Step 7: Copy it onto the persisted `Signal` row**

Find where `SignalDecision` becomes a `Signal` row — search:

Run: `cd backend && grep -rn "stop_loss=decision.stop_loss\|stop_loss=.*\.stop_loss" src/swing_trade_ml/services/engine.py`

At that construction site (in `services/engine.py`, the function that turns a strategy's `SignalDecision` into a persisted `Signal`), add `horizon_days=decision.horizon_days,` alongside the existing `stop_loss=decision.stop_loss, take_profit=decision.take_profit,` lines.

- [ ] **Step 8: Run the full strategy test suite**

Run: `cd backend && pytest tests/test_engine.py tests/test_signal_scoring.py -v`
Expected: PASS — confirms nothing in `engine.py`'s existing signal-creation tests broke.

- [ ] **Step 9: Commit**

```bash
git add backend/src/swing_trade_ml/strategies/base.py backend/src/swing_trade_ml/strategies/ml_swing.py backend/src/swing_trade_ml/strategies/sma_crossover.py backend/src/swing_trade_ml/services/engine.py backend/tests/test_signal_scoring.py
git commit -m "feat: set horizon_days on generated signals

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: `evaluate_pending_signals` scoring function

**Files:**
- Modify: `backend/src/swing_trade_ml/ml/predict.py` (add next to `evaluate_pending_predictions`, ~line 199)
- Test: `backend/tests/test_signal_scoring.py`

**Interfaces:**
- Consumes: `Signal.horizon_days/outcome/outcome_pct/outcome_at` (Task 1), `forward_return_at_horizon` (already exists in `ml/predict.py`), `Candle` model (existing).
- Produces: `evaluate_pending_signals(db: Session, interval: str = "day", now: datetime | None = None) -> int` — Task 4's job calls this exact signature.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_signal_scoring.py`:

```python
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.trading import Strategy


def _instrument(db_session, tradingsymbol="TEST") -> Instrument:
    inst = Instrument(
        instrument_token=hash(tradingsymbol) % 1_000_000,
        tradingsymbol=tradingsymbol,
        exchange="NSE",
        is_watchlisted=True,
    )
    db_session.add(inst)
    db_session.flush()
    return inst


def _strategy(db_session) -> Strategy:
    strat = Strategy(name="test_strategy", strategy_type="ml_swing", mode="paper")
    db_session.add(strat)
    db_session.flush()
    return strat


def _candle(db_session, instrument_id, ts, o, h, l, c, v=100_000):
    db_session.add(
        Candle(
            instrument_id=instrument_id, interval="day", ts=ts,
            open=o, high=h, low=l, close=c, volume=v,
        )
    )


def _signal(db_session, strategy_id, instrument_id, generated_at, price, stop_loss, take_profit, horizon_days=5):
    from swing_trade_ml.core.enums import SignalType
    sig = Signal(
        strategy_id=strategy_id, instrument_id=instrument_id,
        signal_type=SignalType.BUY, mode="paper",
        price=price, stop_loss=stop_loss, take_profit=take_profit,
        horizon_days=horizon_days, generated_at=generated_at,
    )
    db_session.add(sig)
    db_session.flush()
    return sig


def test_target_hit_before_stop(db_session):
    from swing_trade_ml.ml.predict import evaluate_pending_signals

    inst = _instrument(db_session)
    strat = _strategy(db_session)
    gen_at = datetime(2026, 1, 1, tzinfo=UTC)
    sig = _signal(db_session, strat.id, inst.id, gen_at, price=100.0, stop_loss=90.0, take_profit=110.0)
    # Day after generation: high crosses take_profit, low stays above stop.
    _candle(db_session, inst.id, datetime(2026, 1, 2, tzinfo=UTC), 101, 112, 100, 111)
    db_session.commit()

    count = evaluate_pending_signals(db_session, now=datetime(2026, 1, 10, tzinfo=UTC))

    assert count == 1
    db_session.refresh(sig)
    assert sig.outcome == "TARGET_HIT"
    assert sig.outcome_pct == 0.10  # (110 - 100) / 100


def test_stop_hit_before_target(db_session):
    from swing_trade_ml.ml.predict import evaluate_pending_signals

    inst = _instrument(db_session)
    strat = _strategy(db_session)
    gen_at = datetime(2026, 1, 1, tzinfo=UTC)
    sig = _signal(db_session, strat.id, inst.id, gen_at, price=100.0, stop_loss=90.0, take_profit=110.0)
    _candle(db_session, inst.id, datetime(2026, 1, 2, tzinfo=UTC), 99, 101, 88, 89)
    db_session.commit()

    evaluate_pending_signals(db_session, now=datetime(2026, 1, 10, tzinfo=UTC))

    db_session.refresh(sig)
    assert sig.outcome == "STOP_LOSS_HIT"
    assert sig.outcome_pct == -0.10  # (90 - 100) / 100


def test_same_day_double_touch_favours_stop(db_session):
    from swing_trade_ml.ml.predict import evaluate_pending_signals

    inst = _instrument(db_session)
    strat = _strategy(db_session)
    gen_at = datetime(2026, 1, 1, tzinfo=UTC)
    sig = _signal(db_session, strat.id, inst.id, gen_at, price=100.0, stop_loss=90.0, take_profit=110.0)
    # One wide-range candle crosses both levels.
    _candle(db_session, inst.id, datetime(2026, 1, 2, tzinfo=UTC), 100, 115, 85, 105)
    db_session.commit()

    evaluate_pending_signals(db_session, now=datetime(2026, 1, 10, tzinfo=UTC))

    db_session.refresh(sig)
    assert sig.outcome == "STOP_LOSS_HIT"


def test_expires_with_no_hit_within_horizon(db_session):
    from swing_trade_ml.ml.predict import evaluate_pending_signals

    inst = _instrument(db_session)
    strat = _strategy(db_session)
    gen_at = datetime(2026, 1, 1, tzinfo=UTC)
    sig = _signal(
        db_session, strat.id, inst.id, gen_at, price=100.0, stop_loss=90.0,
        take_profit=110.0, horizon_days=3,
    )
    # Every candle stays inside the band, past the 3-day horizon.
    for day, close in [(2, 102), (3, 103), (4, 104), (5, 105)]:
        _candle(db_session, inst.id, datetime(2026, 1, day, tzinfo=UTC), close - 1, close + 1, close - 2, close)
    db_session.commit()

    evaluate_pending_signals(db_session, now=datetime(2026, 1, 10, tzinfo=UTC))

    db_session.refresh(sig)
    assert sig.outcome == "EXPIRED_NO_HIT"
    assert sig.outcome_pct is not None


def test_still_open_signal_is_not_scored(db_session):
    from swing_trade_ml.ml.predict import evaluate_pending_signals

    inst = _instrument(db_session)
    strat = _strategy(db_session)
    gen_at = datetime(2026, 1, 1, tzinfo=UTC)
    sig = _signal(
        db_session, strat.id, inst.id, gen_at, price=100.0, stop_loss=90.0,
        take_profit=110.0, horizon_days=30,
    )
    _candle(db_session, inst.id, datetime(2026, 1, 2, tzinfo=UTC), 100, 105, 98, 102)
    db_session.commit()

    count = evaluate_pending_signals(db_session, now=datetime(2026, 1, 5, tzinfo=UTC))

    assert count == 0
    db_session.refresh(sig)
    assert sig.outcome is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_signal_scoring.py -k "hit or expires or still_open" -v`
Expected: FAIL — `ImportError: cannot import name 'evaluate_pending_signals'`

- [ ] **Step 3: Implement `evaluate_pending_signals`**

In `backend/src/swing_trade_ml/ml/predict.py`, add after `evaluate_pending_predictions` (which ends around line 237):

```python
def evaluate_pending_signals(db: Session, interval: str = "day", now: datetime | None = None) -> int:
    """Score every not-yet-scored Signal that has a stop/target against real
    intraday price action — target hit, stop hit, or expired with no hit by
    its own horizon. See docs/superpowers/specs/2026-09-12-signal-track-record-design.md
    §6. Unlike evaluate_pending_predictions, this checks candle high/low, not
    close — a stop or target order triggers intraday, and close-only scoring
    would misrepresent what a real order does.
    """
    now = now or datetime.now(UTC)
    scored = 0

    pending = list(
        db.execute(
            select(Signal).where(
                Signal.outcome.is_(None),
                Signal.stop_loss.isnot(None),
                Signal.take_profit.isnot(None),
                Signal.horizon_days.isnot(None),
            )
        ).scalars().all()
    )

    for sig in pending:
        horizon_end = sig.generated_at + timedelta(days=sig.horizon_days)

        candles = list(
            db.execute(
                select(Candle)
                .where(
                    Candle.instrument_id == sig.instrument_id,
                    Candle.interval == interval,
                    Candle.ts > sig.generated_at,
                    Candle.ts <= min(now, horizon_end),
                )
                .order_by(Candle.ts.asc())
            ).scalars().all()
        )

        hit = False
        for candle in candles:
            stop_touched = candle.low <= sig.stop_loss
            target_touched = candle.high >= sig.take_profit
            if stop_touched:
                sig.outcome = "STOP_LOSS_HIT"
                sig.outcome_pct = (sig.stop_loss - sig.price) / sig.price
                sig.outcome_at = candle.ts
                hit = True
                break
            if target_touched:
                sig.outcome = "TARGET_HIT"
                sig.outcome_pct = (sig.take_profit - sig.price) / sig.price
                sig.outcome_at = candle.ts
                hit = True
                break

        if hit:
            scored += 1
            continue

        if now < horizon_end + timedelta(days=2):
            continue  # horizon hasn't elapsed yet — stays open

        actual_return = forward_return_at_horizon(
            db, sig.instrument_id, sig.generated_at, sig.price, sig.horizon_days, interval, now,
        )
        if actual_return is None:
            continue  # no candle data past the horizon yet — stays open

        sig.outcome = "EXPIRED_NO_HIT"
        sig.outcome_pct = actual_return
        sig.outcome_at = horizon_end
        scored += 1

    if scored:
        db.commit()
        log.info("predict.signals_evaluated", count=scored)
    return scored
```

Add `Signal` and `Candle` to this file's imports if not already present — check the top of `ml/predict.py` for its existing `from swing_trade_ml.db.models...` imports and add:

```python
from swing_trade_ml.db.models.market import Candle
from swing_trade_ml.db.models.trading import Signal
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_signal_scoring.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Commit**

```bash
git add backend/src/swing_trade_ml/ml/predict.py backend/tests/test_signal_scoring.py
git commit -m "feat: score signals against real price action (evaluate_pending_signals)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: Job wiring

**Files:**
- Modify: `backend/src/swing_trade_ml/workers/jobs.py` (add next to `job_evaluate_predictions`)
- Modify: `backend/src/swing_trade_ml/workers/scheduler.py` (register the new job)

**Interfaces:**
- Consumes: `evaluate_pending_signals` (Task 3)
- Produces: `job_evaluate_signals()` — no other task depends on its name, but it must follow the exact `_report_error` pattern every neighboring job uses.

- [ ] **Step 1: Add the job function**

In `backend/src/swing_trade_ml/workers/jobs.py`, add directly after `job_evaluate_predictions`:

```python
def job_evaluate_signals() -> None:
    """Backfill outcomes on signals whose stop/target/horizon has resolved."""
    try:
        from swing_trade_ml.ml.predict import evaluate_pending_signals

        with session_scope() as db:
            evaluate_pending_signals(db)
    except Exception as exc:  # noqa: BLE001
        _report_error("evaluate_signals", exc)
```

- [ ] **Step 2: Register it in the scheduler**

In `backend/src/swing_trade_ml/workers/scheduler.py`, directly after the `evaluate_predictions` job registration (`hour=16, minute=15`), add:

```python
    scheduler.add_job(
        jobs.job_evaluate_signals,
        CronTrigger(day_of_week=WEEKDAYS, hour=16, minute=17, timezone=IST),
        id="evaluate_signals",
        replace_existing=True,
    )
```

(Two minutes after `evaluate_predictions` — same daily cluster, no clash with any existing slot in the file.)

- [ ] **Step 3: Verify the job runs standalone**

Run: `cd backend && python -c "from swing_trade_ml.workers.jobs import job_evaluate_signals; job_evaluate_signals()"`
Expected: no exception (with `ENABLE_SCHEDULER=false` and a working `DATABASE_URL` in your `.env`, this runs the job body directly against your dev DB — fine even with zero pending signals, it should just log `predict.signals_evaluated` or nothing).

- [ ] **Step 4: Commit**

```bash
git add backend/src/swing_trade_ml/workers/jobs.py backend/src/swing_trade_ml/workers/scheduler.py
git commit -m "feat: schedule daily signal outcome evaluation

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: `GET /signals/track-record` endpoint

**Files:**
- Modify: `backend/src/swing_trade_ml/api/v1/endpoints/signals.py` (add alongside `top_picks`/`buy_list`)
- Test: `backend/tests/test_signal_scoring.py`

**Interfaces:**
- Consumes: `Signal` (with outcome columns from Task 1), `_cap_tier()` (existing, `signals.py` line ~116), `Trade` model (existing), `Position.current_price` pattern (existing, see `services/portfolio.py::mark_to_market` for the live-price lookup this reuses).
- Produces: `GET /api/v1/signals/track-record` → `list[dict]` — Task 6's frontend fetches this exact shape.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_signal_scoring.py`:

```python
def test_track_record_endpoint_returns_scored_and_open_signals(client, db_session):
    inst = _instrument(db_session, "TRKTEST")
    strat = _strategy(db_session)
    gen_at = datetime(2026, 1, 1, tzinfo=UTC)
    scored = _signal(db_session, strat.id, inst.id, gen_at, price=100.0, stop_loss=90.0, take_profit=110.0)
    scored.outcome = "TARGET_HIT"
    scored.outcome_pct = 0.10
    scored.outcome_at = datetime(2026, 1, 2, tzinfo=UTC)
    db_session.commit()

    resp = client.get("/api/v1/signals/track-record", headers={"X-API-Key": "test-api-key"})

    assert resp.status_code == 200
    rows = resp.json()
    matching = [r for r in rows if r["symbol"] == "TRKTEST"]
    assert len(matching) == 1
    assert matching[0]["outcome"] == "TARGET_HIT"
    assert matching[0]["cap_tier"] == "large"
    assert "current_price" in matching[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_signal_scoring.py::test_track_record_endpoint_returns_scored_and_open_signals -v`
Expected: FAIL — 404 (route doesn't exist)

- [ ] **Step 3: Implement the endpoint**

In `backend/src/swing_trade_ml/api/v1/endpoints/signals.py`, add after `buy_list` (the last function in the file, ~line 262):

```python
@router.get("/track-record", response_model=list[dict])
def track_record(db: DbSession) -> list[dict]:
    """Every signal with a stop/target set, scored or still open — the
    honest ledger behind the Scan Results tab. Unlike /top-picks (a
    same-day shortlist), this returns full history: wins, losses, and
    expirations together, never filtered down to only the flattering ones.
    See docs/superpowers/specs/2026-09-12-signal-track-record-design.md.
    """
    rows = db.execute(
        select(Signal, Instrument.tradingsymbol, Instrument.name, Strategy)
        .join(Instrument, Instrument.id == Signal.instrument_id)
        .join(Strategy, Strategy.id == Signal.strategy_id)
        .where(Signal.stop_loss.isnot(None), Signal.take_profit.isnot(None))
        .order_by(Signal.generated_at.desc())
    ).all()

    out: list[dict] = []
    for sig, symbol, name, strategy in rows:
        trade_row = None
        if sig.was_executed:
            trade_row = db.execute(
                select(Trade).where(Trade.instrument_id == sig.instrument_id, Trade.entry_at >= sig.generated_at)
                .order_by(Trade.entry_at.asc())
                .limit(1)
            ).scalar_one_or_none()

        current_price = None
        latest_candle = db.execute(
            select(Candle.close)
            .where(Candle.instrument_id == sig.instrument_id, Candle.interval == "day")
            .order_by(Candle.ts.desc())
            .limit(1)
        ).scalar_one_or_none()
        if latest_candle is not None:
            current_price = float(latest_candle)

        age_days = (datetime.now(UTC) - sig.generated_at).days

        out.append({
            "signal_id": sig.id,
            "symbol": symbol,
            "name": name,
            "cap_tier": _cap_tier(strategy.params.get("model_name") if strategy.params else None),
            "strategy_name": strategy.name,
            "mode": sig.mode,
            "generated_at": sig.generated_at,
            "age_days": age_days,
            "price": sig.price,
            "stop_loss": sig.stop_loss,
            "take_profit": sig.take_profit,
            "current_price": current_price,
            "confidence": sig.confidence,
            "outcome": sig.outcome,
            "outcome_pct": sig.outcome_pct,
            "outcome_at": sig.outcome_at,
            "was_executed": sig.was_executed,
            "reason": sig.reason,
            "trade_net_pnl": trade_row.net_pnl if trade_row else None,
            "trade_return_pct": trade_row.return_pct if trade_row else None,
        })
    return out
```

Add `Candle` and `Trade` to this file's existing imports from `swing_trade_ml.db.models.market` and `swing_trade_ml.db.models.trading` if not already imported (check the top of `signals.py`).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_signal_scoring.py::test_track_record_endpoint_returns_scored_and_open_signals -v`
Expected: PASS

- [ ] **Step 5: Run the full backend test suite**

Run: `cd backend && pytest -v`
Expected: PASS — no regressions in `signals.py`'s existing endpoints.

- [ ] **Step 6: Commit**

```bash
git add backend/src/swing_trade_ml/api/v1/endpoints/signals.py backend/tests/test_signal_scoring.py
git commit -m "feat: add GET /signals/track-record endpoint

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 6: Frontend types + API client

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/client.ts`

**Interfaces:**
- Produces: `ScanResult` type, `api.scanResults(): Promise<ScanResult[]>` — Task 7's page consumes both by these exact names.

- [ ] **Step 1: Add the type**

In `frontend/src/api/types.ts`, add:

```typescript
export interface ScanResult {
  signal_id: number
  symbol: string
  name: string | null
  cap_tier: 'large' | 'midcap' | 'smallcap'
  strategy_name: string
  mode: 'paper' | 'real'
  generated_at: string
  age_days: number
  price: number
  stop_loss: number
  take_profit: number
  current_price: number | null
  confidence: number | null
  outcome: 'TARGET_HIT' | 'STOP_LOSS_HIT' | 'EXPIRED_NO_HIT' | null
  outcome_pct: number | null
  outcome_at: string | null
  was_executed: boolean
  reason: string | null
  trade_net_pnl: number | null
  trade_return_pct: number | null
}
```

- [ ] **Step 2: Add the client method**

In `frontend/src/api/client.ts`, find where other `signals`-adjacent methods are defined (e.g. `buyList`, near the `api` object's other `GET` wrappers) and add alongside them, following that file's existing `get<T>('/path')` convention:

```typescript
  scanResults: () => get<ScanResult[]>('/signals/track-record'),
```

Add `ScanResult` to this file's existing `import type { ... } from './types'` line.

- [ ] **Step 3: Verify the frontend still typechecks**

Run: `cd frontend && npx tsc --noEmit`
Expected: no new errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/client.ts
git commit -m "feat: add ScanResult type and api.scanResults() client method

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 7: Scan Results page, nav entry, and Search removal

**Files:**
- Create: `frontend/src/pages/ScanResults.tsx`
- Modify: `frontend/src/App.tsx` (nav, routes)
- Modify: `frontend/src/components/icons.tsx` (add `LayersIcon` if not present — check first, `LayersIcon` is referenced in the spec as already existing)
- Delete: `frontend/src/pages/Search.tsx`

**Interfaces:**
- Consumes: `api.scanResults()`, `ScanResult` (Task 6), `Modal` component (existing, see `Finance.tsx` for usage pattern), `formatCurrency`/`formatDate` (existing, `lib/format.ts`).

- [ ] **Step 1: Confirm `LayersIcon` exists**

Run: `cd frontend && grep -n "LayersIcon" src/components/icons.tsx`

If it exists (it does, per the earlier codebase scan — `export function LayersIcon()` at line 46), skip to Step 2. If the grep finds nothing, add one following the file's existing icon shape (same `<svg>` wrapper as `BriefcaseIcon`), using a simple stacked-layers path.

- [ ] **Step 2: Write the page**

```typescript
// frontend/src/pages/ScanResults.tsx
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { api } from '../api/client'
import { Empty, ErrorBox, Loading } from '../components/Loading'
import Modal from '../components/Modal'
import type { ScanResult } from '../api/types'
import { formatCurrency, formatDate } from '../lib/format'

const OUTCOME_LABEL: Record<string, { label: string; icon: string }> = {
  TARGET_HIT: { label: 'Hit Target', icon: '🟢' },
  STOP_LOSS_HIT: { label: 'Hit Stop', icon: '🔴' },
  EXPIRED_NO_HIT: { label: 'Expired, no hit', icon: '⚫' },
}

function statusFor(row: ScanResult): { label: string; icon: string } {
  if (row.outcome) return OUTCOME_LABEL[row.outcome] ?? { label: row.outcome, icon: '•' }
  return { label: 'Open', icon: '⚪' }
}

function resultPctFor(row: ScanResult): number | null {
  return row.was_executed && row.trade_return_pct != null ? row.trade_return_pct : row.outcome_pct
}

export default function ScanResults() {
  const [selected, setSelected] = useState<ScanResult | null>(null)
  const scanResults = useQuery({ queryKey: ['scanResults'], queryFn: api.scanResults })

  const rows = useMemo(() => scanResults.data ?? [], [scanResults.data])

  return (
    <>
      <div className="page-head">
        <h1>Scan Results</h1>
      </div>

      {scanResults.isLoading && <Loading />}
      {scanResults.isError && <ErrorBox error={scanResults.error as Error} />}
      {!scanResults.isLoading && rows.length === 0 && (
        <Empty message="No signals with a stop and target have been generated yet." />
      )}

      {rows.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Stock</th>
                <th>Cap tier</th>
                <th>Called on</th>
                <th>Entry</th>
                <th>Stop</th>
                <th>Target</th>
                <th>Current</th>
                <th>Status</th>
                <th>Result</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const status = statusFor(row)
                const resultPct = resultPctFor(row)
                return (
                  <tr key={row.signal_id} onClick={() => setSelected(row)} style={{ cursor: 'pointer' }}>
                    <td>{row.symbol}</td>
                    <td>{row.cap_tier}</td>
                    <td>
                      {formatDate(row.generated_at)} <span className="muted">({row.age_days}d ago)</span>
                    </td>
                    <td>{formatCurrency(row.price)}</td>
                    <td>{formatCurrency(row.stop_loss)}</td>
                    <td>{formatCurrency(row.take_profit)}</td>
                    <td>{row.current_price != null ? formatCurrency(row.current_price) : '—'}</td>
                    <td>
                      {status.icon} {status.label}
                    </td>
                    <td className={resultPct != null ? (resultPct >= 0 ? 'pos' : 'neg') : undefined}>
                      {resultPct != null ? `${(resultPct * 100).toFixed(1)}%` : '—'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {selected && (
        <Modal onClose={() => setSelected(null)}>
          <h2>{selected.symbol} — signal detail</h2>
          <p>
            <strong>Strategy:</strong> {selected.strategy_name} ({selected.mode})
          </p>
          <p>
            <strong>Confidence:</strong>{' '}
            {selected.confidence != null ? `${(selected.confidence * 100).toFixed(0)}%` : '—'}
          </p>
          <p>
            <strong>Reason:</strong> {selected.reason ?? '—'}
          </p>
          {selected.was_executed && (
            <p>
              <strong>Actual trade result:</strong>{' '}
              {selected.trade_net_pnl != null ? formatCurrency(selected.trade_net_pnl) : 'pending'}
              {selected.trade_return_pct != null ? ` (${(selected.trade_return_pct * 100).toFixed(1)}%)` : ''}
            </p>
          )}
        </Modal>
      )}
    </>
  )
}
```

Check `frontend/src/components/Modal.tsx`'s actual prop names before this step (`onClose`/`title`/`children` is the expected shape based on `Finance.tsx`'s usage — confirm with `grep -n "interface.*Modal\|function Modal" frontend/src/components/Modal.tsx` and adjust the props above to match exactly if they differ).

- [ ] **Step 3: Wire the route and nav, remove Search**

In `frontend/src/App.tsx`:
1. Remove `import Search from './pages/Search'` and add `import ScanResults from './pages/ScanResults'`.
2. Remove `SearchIcon` from the icons import if `ScanResults` doesn't need it; add `LayersIcon` to that same import line.
3. In the `NAV` array, replace `{ to: '/search', label: 'Search' }` with `{ to: '/scans', label: 'Scan Results' }`.
4. In the `TAB_BAR` array, replace the `Search` entry (`{ to: '/search', label: 'Search', Icon: SearchIcon }`) with `{ to: '/finance', label: 'Finance', Icon: WalletIcon }` — this is the sidebar-fix batch's change, landing in the same file; import `WalletIcon` alongside `LayersIcon`.
5. In the `<Routes>` block, replace `<Route path="/search" element={<Search />} />` with `<Route path="/scans" element={<ScanResults />} />`.

- [ ] **Step 4: Delete the old page**

Run: `cd frontend && rm src/pages/Search.tsx`

- [ ] **Step 5: Verify it builds and typechecks**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: no errors, build succeeds.

- [ ] **Step 6: Visual check**

Use the `run` skill (or `browser-automation` skill directly against `http://localhost:5173` if the dev containers are already up) to confirm: `/scans` renders the table, clicking a row opens the popup, `/search` is gone from the nav, and the mobile tab bar now shows Finance instead of Search.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/ScanResults.tsx frontend/src/App.tsx
git rm frontend/src/pages/Search.tsx
git commit -m "feat: add Scan Results tab, remove Search, Finance into mobile tab bar

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```
