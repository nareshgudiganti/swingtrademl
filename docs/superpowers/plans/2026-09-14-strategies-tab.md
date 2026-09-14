# Strategies Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A user-facing "Strategies" tab with plain-English cap-tier cards (tier, stock count, win rate, "Recommended" badge), strategy attribution surfaced on Holdings/Portfolio, and a lighter Reports page with a by-strategy breakdown — using only data the backend already has (`Trade.strategy_id`, `Trade.is_win`).

**Architecture:** One new backend read endpoint (`GET /strategies/performance`) aggregating existing `Trade` rows per strategy per time window with a deterministic recommendation rule; two existing endpoints (`positions/detailed`, `trades`) gain `strategy_name`/`cap_tier` fields; a duplicated `_cap_tier` helper is consolidated into one shared module. Frontend: the existing hidden `/strategies` admin page is restructured into cap-tier cards + a collapsed advanced table, promoted into nav; three other pages (Dashboard, Positions/Holdings, Reports) get small additive changes. No new tables, no DB migration, no ML changes.

**Tech Stack:** FastAPI, SQLAlchemy, pytest (backend); React, TanStack Query, TypeScript (frontend).

**Spec:** `docs/superpowers/specs/2026-09-14-strategies-tab-design.md`

## Global Constraints

- No schema/migration changes — `Strategy`, `Trade`, `Position` already carry every field needed (spec §4).
- No changes to ML model/prediction code (spec §3).
- Recommendation is informational only, never auto-switches a strategy (spec §3, §5b).
- Recommendation eligibility: `strategy_type == "ml_swing"` and `execution_mode == "auto"` (excludes the advisory `real_trading` strategy — spec §8) and `all_time.trades >= 10` (spec §5b).
- 90-day window is only used for ranking when it has `>= 3` trades of its own; otherwise fall back to the all-time window (spec §5b).
- The Strategies tab's primary cards show only the three cap-tier `ml_swing` strategies; `sma_crossover`, `long_term_value`, and `real_trading` move to a collapsed "Advanced strategies" section, not deleted (spec §3, §6a).
- Reports drops its Recharts `BarChart` entirely — no replacement chart (spec §6d).

---

### Task 1: Shared cap-tier helper

**Files:**
- Create: `backend/src/swing_trade_ml/strategies/tier.py`
- Modify: `backend/src/swing_trade_ml/api/v1/endpoints/signals.py` (removes the two duplicated `_cap_tier` defs at lines 21-31 and 129-140, and both call sites at lines 207 and 370)
- Test: `backend/tests/test_strategy_tier.py`

**Interfaces:**
- Produces: `cap_tier(model_name: str | None) -> str` in `swing_trade_ml.strategies.tier`, returning `"large" | "midcap" | "smallcap"`. Every later backend task that needs a cap tier imports this.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_strategy_tier.py
"""Cap-tier convention shared by signals.py and the new strategies/performance
endpoint — see docs/superpowers/specs/2026-09-14-strategies-tab-design.md §5a."""

from __future__ import annotations

from swing_trade_ml.strategies.tier import cap_tier


def test_default_model_name_is_large_cap():
    assert cap_tier("swing_classifier") == "large"


def test_midcap_model_name():
    assert cap_tier("swing_classifier_midcap") == "midcap"


def test_smallcap_model_name():
    assert cap_tier("swing_classifier_smallcap") == "smallcap"


def test_none_falls_back_to_large():
    assert cap_tier(None) == "large"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_strategy_tier.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'swing_trade_ml.strategies.tier'`

- [ ] **Step 3: Create the shared helper**

```python
# backend/src/swing_trade_ml/strategies/tier.py
"""Cap-tier convention shared by every backend consumer that groups
strategies or signals by cap size — mirrors frontend/src/lib/tiers.ts's
TIERS list. One definition so "swing_classifier_midcap is midcap" means the
same thing everywhere instead of two call sites agreeing by convention."""

from __future__ import annotations


def cap_tier(model_name: str | None) -> str:
    """Map an ml_swing strategy's params.model_name to a cap tier. Strategies
    with no model (e.g. sma_crossover) or the default large-cap model both
    fall back to "large" — the safest assumption when tier genuinely isn't
    known."""
    name = model_name or ""
    if name.endswith("_smallcap"):
        return "smallcap"
    if name.endswith("_midcap"):
        return "midcap"
    return "large"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_strategy_tier.py -v`
Expected: PASS

- [ ] **Step 5: Remove the duplicated helpers from signals.py and use the shared one**

In `backend/src/swing_trade_ml/api/v1/endpoints/signals.py`:

Add to the imports (near the other `swing_trade_ml` imports, after the `PositionStatus` import):

```python
from swing_trade_ml.strategies.tier import cap_tier
```

Delete the first `_cap_tier` definition (lines 21-31):

```python
def _cap_tier(model_name: str | None) -> str:
    """Map an ml_swing strategy's model_name param to a cap tier — mirrors
    frontend/src/lib/tiers.ts's TIERS convention. Strategies with no model
    (e.g. sma_crossover) or the default large-cap model both fall back to
    "large".
    """
    if model_name == "swing_classifier_midcap":
        return "midcap"
    if model_name == "swing_classifier_smallcap":
        return "smallcap"
    return "large"
```

Delete the second `_cap_tier` definition (lines 129-140):

```python
def _cap_tier(model_name: str | None) -> str:
    """Cap-tier label from an ml_swing strategy's model_name — see
    ml.sector_map's neighbouring cap-tier convention
    (swing_classifier[_midcap|_smallcap]). Anything else (a non-ML strategy
    like sma_crossover, or no model_name at all) is treated as "large" —
    the safest assumption when tier genuinely isn't known."""
    name = model_name or ""
    if name.endswith("_smallcap"):
        return "smallcap"
    if name.endswith("_midcap"):
        return "midcap"
    return "large"
```

Replace both call sites' function name (`_cap_tier` → `cap_tier`), same arguments:

Line 207 (inside `top_picks`):
```python
        tier = cap_tier(strategy.params.get("model_name") if strategy.params else None)
```

Line 370 (inside the track-record row builder):
```python
            "cap_tier": cap_tier(strategy.params.get("model_name") if strategy.params else None),
```

- [ ] **Step 6: Run the full signals test suite to confirm nothing broke**

Run: `cd backend && pytest tests/test_signal_scoring.py -v`
Expected: PASS (unrelated to this change, but exercises the same file's imports)

- [ ] **Step 7: Commit**

```bash
git add backend/src/swing_trade_ml/strategies/tier.py backend/src/swing_trade_ml/api/v1/endpoints/signals.py backend/tests/test_strategy_tier.py
git commit -m "$(cat <<'EOF'
Consolidate the duplicated cap-tier helper into one shared module

signals.py had two copies of _cap_tier with slightly different matching
logic. Extracted to strategies/tier.py so the new strategy-performance
endpoint can reuse the same convention instead of a third copy.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Rename `_eligible_instruments` to a public name

**Files:**
- Modify: `backend/src/swing_trade_ml/services/engine.py:36,84`

**Interfaces:**
- Produces: `engine.eligible_instruments(db: Session, strategy: Strategy) -> list[Instrument]` (was private `_eligible_instruments`) — Task 4's new endpoint calls this to compute `universe_size`.

- [ ] **Step 1: Rename the function definition**

In `backend/src/swing_trade_ml/services/engine.py`, line 36:

```python
def eligible_instruments(db: Session, strategy: Strategy) -> list[Instrument]:
```

(was `def _eligible_instruments(...)`, docstring unchanged)

- [ ] **Step 2: Update the one internal call site**

Line 84:

```python
    instruments = eligible_instruments(db, strategy)
```

- [ ] **Step 3: Run the engine test suite to confirm the rename didn't break anything**

Run: `cd backend && pytest tests/test_engine.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/src/swing_trade_ml/services/engine.py
git commit -m "$(cat <<'EOF'
Make eligible_instruments public so the new strategy-performance
endpoint can reuse it for universe_size

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `strategy_performance_stats()` service function

**Files:**
- Modify: `backend/src/swing_trade_ml/services/portfolio.py` (insert after `performance_stats`, which ends at line 308, before `recent_post_exit_watch` at line 311)
- Test: `backend/tests/test_strategy_performance_stats.py`

**Interfaces:**
- Consumes: `Trade` model (`strategy_id`, `is_win`, `net_pnl`, `exit_at` — see `db/models/trading.py:286-324`).
- Produces: `strategy_performance_stats(db: Session, strategy_id: int, since: datetime | None = None) -> dict[str, Any]` with keys `trades: int`, `win_rate: float`, `profit_factor: float`, `net_pnl: float`. Task 4's endpoint calls this three times per strategy (30d/90d/all-time windows).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_strategy_performance_stats.py
"""strategy_performance_stats() — per-strategy win rate for the Strategies
tab. See docs/superpowers/specs/2026-09-14-strategies-tab-design.md §5b."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Strategy, Trade
from swing_trade_ml.services.portfolio import strategy_performance_stats


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


def _strategy(db_session, name="test_strategy") -> Strategy:
    strat = Strategy(name=name, strategy_type="ml_swing", mode="paper")
    db_session.add(strat)
    db_session.flush()
    return strat


def _trade(db_session, *, strategy_id, instrument_id, is_win, net_pnl, exit_at) -> Trade:
    trade = Trade(
        strategy_id=strategy_id,
        instrument_id=instrument_id,
        mode="paper",
        symbol="TEST",
        quantity=10,
        entry_price=100.0,
        exit_price=110.0 if is_win else 90.0,
        entry_at=exit_at - timedelta(days=5),
        exit_at=exit_at,
        holding_days=5,
        gross_pnl=net_pnl,
        charges=0.0,
        net_pnl=net_pnl,
        return_pct=net_pnl / 1000,
        is_win=is_win,
    )
    db_session.add(trade)
    db_session.flush()
    return trade


def test_no_trades_returns_zeroed_stats(db_session):
    strat = _strategy(db_session)
    db_session.commit()

    stats = strategy_performance_stats(db_session, strat.id)

    assert stats == {"trades": 0, "win_rate": 0.0, "profit_factor": 0.0, "net_pnl": 0.0}


def test_win_rate_and_profit_factor(db_session):
    strat = _strategy(db_session)
    inst = _instrument(db_session)
    now = datetime.now(UTC)
    _trade(db_session, strategy_id=strat.id, instrument_id=inst.id, is_win=True, net_pnl=200.0, exit_at=now)
    _trade(db_session, strategy_id=strat.id, instrument_id=inst.id, is_win=True, net_pnl=100.0, exit_at=now)
    _trade(db_session, strategy_id=strat.id, instrument_id=inst.id, is_win=False, net_pnl=-100.0, exit_at=now)
    db_session.commit()

    stats = strategy_performance_stats(db_session, strat.id)

    assert stats["trades"] == 3
    assert stats["win_rate"] == 2 / 3
    assert stats["profit_factor"] == 3.0  # 300 gross profit / 100 gross loss
    assert stats["net_pnl"] == 200.0


def test_since_filters_out_older_trades(db_session):
    strat = _strategy(db_session)
    inst = _instrument(db_session)
    now = datetime.now(UTC)
    _trade(db_session, strategy_id=strat.id, instrument_id=inst.id, is_win=True, net_pnl=100.0, exit_at=now - timedelta(days=100))
    _trade(db_session, strategy_id=strat.id, instrument_id=inst.id, is_win=False, net_pnl=-50.0, exit_at=now - timedelta(days=5))
    db_session.commit()

    stats = strategy_performance_stats(db_session, strat.id, since=now - timedelta(days=30))

    assert stats["trades"] == 1
    assert stats["win_rate"] == 0.0


def test_a_different_strategys_trades_are_excluded(db_session):
    strat_a = _strategy(db_session, name="strategy_a")
    strat_b = _strategy(db_session, name="strategy_b")
    inst = _instrument(db_session)
    now = datetime.now(UTC)
    _trade(db_session, strategy_id=strat_a.id, instrument_id=inst.id, is_win=True, net_pnl=100.0, exit_at=now)
    _trade(db_session, strategy_id=strat_b.id, instrument_id=inst.id, is_win=False, net_pnl=-100.0, exit_at=now)
    db_session.commit()

    stats = strategy_performance_stats(db_session, strat_a.id)

    assert stats["trades"] == 1
    assert stats["win_rate"] == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_strategy_performance_stats.py -v`
Expected: FAIL — `ImportError: cannot import name 'strategy_performance_stats'`

- [ ] **Step 3: Add the function to portfolio.py**

In `backend/src/swing_trade_ml/services/portfolio.py`, insert immediately after `performance_stats` (which ends with `return stats` at line 308), before the blank lines leading into `recent_post_exit_watch`:

```python
def strategy_performance_stats(
    db: Session, strategy_id: int, since: datetime | None = None
) -> dict[str, Any]:
    """Win rate / profit factor / net P&L for one strategy's closed trades —
    the per-strategy counterpart to performance_stats() above, which is
    scoped by broker mode instead. Powers the Strategies tab's win-rate cards
    and the by-strategy Reports breakdown. `since` restricts to trades closed
    on/after that timestamp; omit for all-time.
    """
    stmt = select(Trade).where(Trade.strategy_id == strategy_id)
    if since is not None:
        stmt = stmt.where(Trade.exit_at >= since)
    trades = list(db.execute(stmt).scalars().all())

    if not trades:
        return {"trades": 0, "win_rate": 0.0, "profit_factor": 0.0, "net_pnl": 0.0}

    wins = [t for t in trades if t.is_win]
    losses = [t for t in trades if not t.is_win]
    gross_profit = sum(t.net_pnl for t in wins)
    gross_loss = abs(sum(t.net_pnl for t in losses))

    return {
        "trades": len(trades),
        "win_rate": len(wins) / len(trades),
        "profit_factor": (gross_profit / gross_loss) if gross_loss else float("inf"),
        "net_pnl": sum(t.net_pnl for t in trades),
    }
```

This needs `datetime` imported in portfolio.py — check the existing import line near the top (`from datetime import ...`) and add `datetime` to it if not already present.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_strategy_performance_stats.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/swing_trade_ml/services/portfolio.py backend/tests/test_strategy_performance_stats.py
git commit -m "$(cat <<'EOF'
Add strategy_performance_stats() for per-strategy win rate

Per-strategy counterpart to the existing mode-scoped performance_stats()
— win rate, profit factor, and net P&L for one strategy's closed trades,
optionally windowed by a since date. Powers the upcoming Strategies tab.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: `GET /strategies/performance` endpoint with recommendation logic

**Files:**
- Modify: `backend/src/swing_trade_ml/api/v1/endpoints/strategies.py`
- Test: `backend/tests/test_strategy_performance_api.py`

**Interfaces:**
- Consumes: `strategy_performance_stats` (Task 3), `cap_tier` (Task 1), `engine.eligible_instruments` (Task 2).
- Produces: `GET /api/v1/strategies/performance` → `{"strategies": [...], "recommended_strategy_id": int | None, "recommendation_reason": str}`, each strategy entry shaped as in spec §5b. Task 8/10/11 (frontend) consume this exact shape.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_strategy_performance_api.py
"""GET /strategies/performance — see
docs/superpowers/specs/2026-09-14-strategies-tab-design.md §5b."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Strategy, Trade

HEADERS = {"X-API-Key": "test-api-key"}


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


def _strategy(db_session, *, name, model_name=None, is_active=True, execution_mode="auto") -> Strategy:
    strat = Strategy(
        name=name,
        strategy_type="ml_swing",
        mode="paper",
        is_active=is_active,
        execution_mode=execution_mode,
        params={"model_name": model_name} if model_name else {},
    )
    db_session.add(strat)
    db_session.flush()
    return strat


def _trade(db_session, *, strategy_id, instrument_id, is_win, net_pnl, exit_at) -> Trade:
    trade = Trade(
        strategy_id=strategy_id,
        instrument_id=instrument_id,
        mode="paper",
        symbol="TEST",
        quantity=10,
        entry_price=100.0,
        exit_price=110.0 if is_win else 90.0,
        entry_at=exit_at - timedelta(days=5),
        exit_at=exit_at,
        holding_days=5,
        gross_pnl=net_pnl,
        charges=0.0,
        net_pnl=net_pnl,
        return_pct=net_pnl / 1000,
        is_win=is_win,
    )
    db_session.add(trade)
    db_session.flush()
    return trade


def test_strategy_with_no_trades_shows_zeroed_windows(client, db_session):
    _strategy(db_session, name="ml_swing_main")
    db_session.commit()

    resp = client.get("/api/v1/strategies/performance", headers=HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    row = next(s for s in body["strategies"] if s["name"] == "ml_swing_main")
    assert row["cap_tier"] == "large"
    assert row["windows"]["all_time"] == {"trades": 0, "win_rate": 0.0, "profit_factor": 0.0, "net_pnl": 0.0}


def test_below_trade_threshold_gives_no_recommendation(client, db_session):
    strat = _strategy(db_session, name="ml_swing_midcap", model_name="swing_classifier_midcap")
    inst = _instrument(db_session)
    now = datetime.now(UTC)
    for _ in range(5):  # below the 10-trade threshold
        _trade(db_session, strategy_id=strat.id, instrument_id=inst.id, is_win=True, net_pnl=100.0, exit_at=now)
    db_session.commit()

    resp = client.get("/api/v1/strategies/performance", headers=HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["recommended_strategy_id"] is None
    assert "10" in body["recommendation_reason"] or "more" in body["recommendation_reason"]


def test_highest_win_rate_active_strategy_is_recommended(client, db_session):
    good = _strategy(db_session, name="ml_swing_midcap", model_name="swing_classifier_midcap")
    bad = _strategy(db_session, name="ml_swing_smallcap", model_name="swing_classifier_smallcap")
    inst = _instrument(db_session)
    now = datetime.now(UTC)
    for _ in range(9):
        _trade(db_session, strategy_id=good.id, instrument_id=inst.id, is_win=True, net_pnl=100.0, exit_at=now)
    _trade(db_session, strategy_id=good.id, instrument_id=inst.id, is_win=False, net_pnl=-50.0, exit_at=now)
    for _ in range(2):
        _trade(db_session, strategy_id=bad.id, instrument_id=inst.id, is_win=True, net_pnl=100.0, exit_at=now)
    for _ in range(8):
        _trade(db_session, strategy_id=bad.id, instrument_id=inst.id, is_win=False, net_pnl=-100.0, exit_at=now)
    db_session.commit()

    resp = client.get("/api/v1/strategies/performance", headers=HEADERS)

    assert resp.status_code == 200
    assert resp.json()["recommended_strategy_id"] == good.id


def test_advisory_strategy_is_never_recommended(client, db_session):
    """real_trading-style strategies (execution_mode=advisory) track personal
    holdings, not a competing cap-tier approach — never eligible."""
    advisory = _strategy(db_session, name="real_trading", execution_mode="advisory")
    inst = _instrument(db_session)
    now = datetime.now(UTC)
    for _ in range(15):
        _trade(db_session, strategy_id=advisory.id, instrument_id=inst.id, is_win=True, net_pnl=100.0, exit_at=now)
    db_session.commit()

    resp = client.get("/api/v1/strategies/performance", headers=HEADERS)

    assert resp.status_code == 200
    assert resp.json()["recommended_strategy_id"] is None


def test_inactive_strategy_is_never_recommended(client, db_session):
    strat = _strategy(db_session, name="ml_swing_main", is_active=False)
    inst = _instrument(db_session)
    now = datetime.now(UTC)
    for _ in range(15):
        _trade(db_session, strategy_id=strat.id, instrument_id=inst.id, is_win=True, net_pnl=100.0, exit_at=now)
    db_session.commit()

    resp = client.get("/api/v1/strategies/performance", headers=HEADERS)

    assert resp.status_code == 200
    assert resp.json()["recommended_strategy_id"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_strategy_performance_api.py -v`
Expected: FAIL — 404 (route doesn't exist yet)

- [ ] **Step 3: Add the endpoint**

In `backend/src/swing_trade_ml/api/v1/endpoints/strategies.py`, update imports at the top:

```python
"""Strategy CRUD, activation, and manual scan triggering."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from swing_trade_ml.api.deps import DbSession
from swing_trade_ml.brokers import get_broker
from swing_trade_ml.core.enums import PositionStatus
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Position, Signal, Strategy
from swing_trade_ml.schemas import (
    MessageResponse,
    ScanResponse,
    SignalOut,
    StrategyCreate,
    StrategyOut,
    StrategyTypeInfo,
    StrategyUpdate,
)
from swing_trade_ml.services import engine
from swing_trade_ml.services import portfolio as portfolio_service
from swing_trade_ml.strategies import STRATEGY_REGISTRY
from swing_trade_ml.strategies.tier import cap_tier

router = APIRouter(prefix="/strategies", tags=["strategies"])

# A strategy needs this many all-time closed trades before it's eligible to
# be recommended — fewer than this and win rate is noise, not signal.
MIN_TRADES_FOR_RECOMMENDATION = 10
# The 90-day window is only trusted for ranking once it has this many trades
# of its own; below that, all-time win rate is the fairer comparison.
MIN_TRADES_FOR_90D_WINDOW = 3
# Only ml_swing strategies running in "auto" mode compete for the
# recommendation — advisory strategies like real_trading track personal
# holdings, not a switchable trading approach.
RECOMMENDABLE_STRATEGY_TYPE = "ml_swing"
RECOMMENDABLE_EXECUTION_MODE = "auto"
```

Add the new route, placed after `list_strategy_types` (so `/performance` isn't shadowed by the `/{strategy_id}` path parameter routes below it):

```python
@router.get("/performance", response_model=dict)
def strategy_performance(db: DbSession) -> dict[str, Any]:
    """Per-strategy win rate over three windows, plus a deterministic
    recommendation — the data behind the Strategies tab's cards. See
    docs/superpowers/specs/2026-09-14-strategies-tab-design.md §5b.
    """
    strategies = list(db.execute(select(Strategy).order_by(Strategy.name)).scalars().all())
    now = datetime.now(UTC)
    since_30d = now - timedelta(days=30)
    since_90d = now - timedelta(days=90)

    rows: list[dict[str, Any]] = []
    for strategy in strategies:
        model_name = strategy.params.get("model_name") if strategy.params else None
        open_positions = db.execute(
            select(func.count(Position.id)).where(
                Position.strategy_id == strategy.id, Position.status == PositionStatus.OPEN
            )
        ).scalar_one()
        rows.append(
            {
                "id": strategy.id,
                "name": strategy.name,
                "strategy_type": strategy.strategy_type,
                "execution_mode": strategy.execution_mode,
                "cap_tier": cap_tier(model_name),
                "is_active": strategy.is_active,
                "universe_size": len(engine.eligible_instruments(db, strategy)),
                "open_positions": open_positions,
                "windows": {
                    "last_30d": portfolio_service.strategy_performance_stats(db, strategy.id, since=since_30d),
                    "last_90d": portfolio_service.strategy_performance_stats(db, strategy.id, since=since_90d),
                    "all_time": portfolio_service.strategy_performance_stats(db, strategy.id),
                },
            }
        )

    def _rank_key(row: dict[str, Any]) -> tuple[float, float, float]:
        w90 = row["windows"]["last_90d"]
        primary = w90 if w90["trades"] >= MIN_TRADES_FOR_90D_WINDOW else row["windows"]["all_time"]
        return (primary["win_rate"], primary["profit_factor"], primary["net_pnl"])

    eligible = [
        row
        for row in rows
        if row["is_active"]
        and row["strategy_type"] == RECOMMENDABLE_STRATEGY_TYPE
        and row["execution_mode"] == RECOMMENDABLE_EXECUTION_MODE
        and row["windows"]["all_time"]["trades"] >= MIN_TRADES_FOR_RECOMMENDATION
    ]

    recommended_id: int | None = None
    if eligible:
        best = max(eligible, key=_rank_key)
        recommended_id = best["id"]
        w90 = best["windows"]["last_90d"]
        used_90d = w90["trades"] >= MIN_TRADES_FOR_90D_WINDOW
        primary = w90 if used_90d else best["windows"]["all_time"]
        window_label = "the last 90 days" if used_90d else "all time"
        reason = (
            f"{best['name']}: best win rate ({primary['win_rate']:.0%}) over {window_label} "
            f"among strategies with at least {MIN_TRADES_FOR_RECOMMENDATION} closed trades."
        )
    else:
        candidates = [
            row
            for row in rows
            if row["strategy_type"] == RECOMMENDABLE_STRATEGY_TYPE
            and row["execution_mode"] == RECOMMENDABLE_EXECUTION_MODE
        ]
        closest = max(candidates, key=lambda r: r["windows"]["all_time"]["trades"], default=None)
        if closest is not None and closest["windows"]["all_time"]["trades"] > 0:
            have = closest["windows"]["all_time"]["trades"]
            need = MIN_TRADES_FOR_RECOMMENDATION - have
            reason = (
                f"{closest['name']} is closest with {have} closed trade{'s' if have != 1 else ''} — "
                f"{need} more needed before a recommendation."
            )
        else:
            reason = "Not enough closed trades yet to recommend a strategy."

    return {"strategies": rows, "recommended_strategy_id": recommended_id, "recommendation_reason": reason}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_strategy_performance_api.py -v`
Expected: PASS

- [ ] **Step 5: Run the full strategies-related test suite**

Run: `cd backend && pytest tests/test_engine.py tests/test_strategy_tier.py tests/test_strategy_performance_stats.py tests/test_strategy_performance_api.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/swing_trade_ml/api/v1/endpoints/strategies.py backend/tests/test_strategy_performance_api.py
git commit -m "$(cat <<'EOF'
Add GET /strategies/performance with a deterministic recommendation

Per-strategy win rate/profit factor/net P&L over 30d/90d/all-time
windows, plus which active ml_swing strategy (if any) has the best
track record with enough closed trades to trust. Powers the Strategies
tab (spec: docs/superpowers/specs/2026-09-14-strategies-tab-design.md).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Strategy attribution on `positions/detailed`

**Files:**
- Modify: `backend/src/swing_trade_ml/api/v1/endpoints/portfolio.py:173-197` (the `result.append(...)` block inside `detailed_positions`)
- Test: `backend/tests/test_positions_detailed_strategy_attribution.py`

**Interfaces:**
- Produces: two new keys on each `positions/detailed` row: `strategy_name: str | None`, `cap_tier: str | None`. Task 9 (frontend `PositionsTable`) reads these.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_positions_detailed_strategy_attribution.py
"""positions/detailed exposes which strategy opened each position — see
docs/superpowers/specs/2026-09-14-strategies-tab-design.md §5c."""

from __future__ import annotations

from datetime import UTC, datetime

from swing_trade_ml.core.enums import PositionStatus
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Position, Strategy

HEADERS = {"X-API-Key": "test-api-key"}


def test_open_position_carries_strategy_name_and_cap_tier(client, db_session):
    strat = Strategy(
        name="ml_swing_midcap",
        strategy_type="ml_swing",
        mode="paper",
        is_active=True,
        params={"model_name": "swing_classifier_midcap"},
    )
    db_session.add(strat)
    db_session.flush()

    inst = Instrument(instrument_token=555001, tradingsymbol="TESTMID", exchange="NSE", is_watchlisted=True)
    db_session.add(inst)
    db_session.flush()

    position = Position(
        strategy_id=strat.id,
        instrument_id=inst.id,
        mode="paper",
        quantity=10,
        entry_price=100.0,
        current_price=110.0,
        stop_loss=90.0,
        entry_at=datetime.now(UTC),
        status=PositionStatus.OPEN,
    )
    db_session.add(position)
    db_session.commit()

    resp = client.get("/api/v1/portfolio/positions/detailed", headers=HEADERS)

    assert resp.status_code == 200
    row = next(r for r in resp.json() if r["symbol"] == "TESTMID")
    assert row["strategy_name"] == "ml_swing_midcap"
    assert row["cap_tier"] == "midcap"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_positions_detailed_strategy_attribution.py -v`
Expected: FAIL — `KeyError: 'strategy_name'`

- [ ] **Step 3: Add the fields**

In `backend/src/swing_trade_ml/api/v1/endpoints/portfolio.py`, add the import (near the other `swing_trade_ml` imports):

```python
from swing_trade_ml.strategies.tier import cap_tier
```

In the `result.append({...})` block inside `detailed_positions` (currently lines 173-197), add two keys after `"strategy_id": position.strategy_id,`:

```python
                "strategy_id": position.strategy_id,
                "strategy_name": position.strategy.name if position.strategy else None,
                "cap_tier": (
                    cap_tier(position.strategy.params.get("model_name") if position.strategy.params else None)
                    if position.strategy
                    else None
                ),
```

`position.strategy` is already accessed a few lines above this block (line 161, for `exit_confidence`), so this adds no new query.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_positions_detailed_strategy_attribution.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/swing_trade_ml/api/v1/endpoints/portfolio.py backend/tests/test_positions_detailed_strategy_attribution.py
git commit -m "$(cat <<'EOF'
Expose strategy_name/cap_tier on positions/detailed

So Holdings and Portfolio can show which strategy opened each
position, without a second round-trip. position.strategy was already
loaded for the exit_confidence lookup a few lines above.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Strategy attribution on `trades`

**Files:**
- Modify: `backend/src/swing_trade_ml/api/v1/endpoints/portfolio.py:593-639` (`list_trades`)
- Modify: `backend/src/swing_trade_ml/schemas/__init__.py:338-370` (`TradeOut`)
- Test: `backend/tests/test_trades_strategy_attribution.py`

**Interfaces:**
- Produces: two new fields on `TradeOut`/`GET /portfolio/trades` rows: `strategy_name: str | None`, `cap_tier: str | None`. Task 11 (frontend Reports "By Strategy" table) reads these.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_trades_strategy_attribution.py
"""GET /portfolio/trades exposes which strategy made each trade — see
docs/superpowers/specs/2026-09-14-strategies-tab-design.md §5c."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Strategy, Trade

HEADERS = {"X-API-Key": "test-api-key"}


def test_trade_row_carries_strategy_name_and_cap_tier(client, db_session):
    strat = Strategy(
        name="ml_swing_smallcap",
        strategy_type="ml_swing",
        mode="paper",
        params={"model_name": "swing_classifier_smallcap"},
    )
    db_session.add(strat)
    db_session.flush()

    inst = Instrument(instrument_token=555002, tradingsymbol="TESTSMALL", exchange="NSE", is_watchlisted=True)
    db_session.add(inst)
    db_session.flush()

    now = datetime.now(UTC)
    trade = Trade(
        strategy_id=strat.id,
        instrument_id=inst.id,
        mode="paper",
        symbol="TESTSMALL",
        quantity=10,
        entry_price=100.0,
        exit_price=120.0,
        entry_at=now - timedelta(days=5),
        exit_at=now,
        holding_days=5,
        gross_pnl=200.0,
        charges=10.0,
        net_pnl=190.0,
        return_pct=0.19,
        is_win=True,
    )
    db_session.add(trade)
    db_session.commit()

    resp = client.get("/api/v1/portfolio/trades", headers=HEADERS)

    assert resp.status_code == 200
    row = next(r for r in resp.json() if r["symbol"] == "TESTSMALL")
    assert row["strategy_name"] == "ml_swing_smallcap"
    assert row["cap_tier"] == "smallcap"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_trades_strategy_attribution.py -v`
Expected: FAIL — response validated against `TradeOut` strips the field, so `KeyError: 'strategy_name'`

- [ ] **Step 3: Extend `TradeOut`**

In `backend/src/swing_trade_ml/schemas/__init__.py`, add to `TradeOut` (after `last_confidence: float | None = None` at line 362):

```python
    # Which strategy made this trade, and its cap tier — see
    # strategies/tier.py. Null only if the strategy was later deleted.
    strategy_name: str | None = None
    cap_tier: str | None = None
```

- [ ] **Step 4: Populate the fields in `list_trades`**

In `backend/src/swing_trade_ml/api/v1/endpoints/portfolio.py`, `list_trades` currently selects `Trade, Position` only (lines 599-605). Add a join to `Strategy`:

```python
    stmt = (
        select(Trade, Position, Strategy)
        .outerjoin(Position, Position.id == Trade.position_id)
        .outerjoin(Strategy, Strategy.id == Trade.strategy_id)
        .where(Trade.mode == get_broker().mode)
        .order_by(Trade.exit_at.desc())
        .limit(limit)
    )
    if wins_only is not None:
        stmt = stmt.where(Trade.is_win.is_(wins_only))

    triples = db.execute(stmt).all()
    post_exit = _post_exit_moves(db, [trade for trade, _, _ in triples])

    result = []
    for trade, position, strategy in triples:
        result.append(
            {
                "id": trade.id,
                "symbol": trade.symbol,
                "mode": trade.mode,
                "quantity": trade.quantity,
                "entry_price": trade.entry_price,
                "exit_price": trade.exit_price,
                "entry_at": trade.entry_at,
                "exit_at": trade.exit_at,
                "holding_days": trade.holding_days,
                "gross_pnl": trade.gross_pnl,
                "charges": trade.charges,
                "net_pnl": trade.net_pnl,
                "return_pct": trade.return_pct,
                "exit_reason": trade.exit_reason,
                "exit_reason_label": EXIT_REASON_LABELS.get(trade.exit_reason, trade.exit_reason),
                "is_win": trade.is_win,
                "stop_loss": position.stop_loss if position else None,
                "take_profit": position.take_profit if position else None,
                "entry_confidence": position.entry_confidence if position else None,
                "last_confidence": position.last_confidence if position else None,
                "strategy_name": strategy.name if strategy else None,
                "cap_tier": (
                    cap_tier(strategy.params.get("model_name") if strategy.params else None)
                    if strategy
                    else None
                ),
                **post_exit.get(trade.id, {}),
            }
        )
    return result
```

This replaces the existing `pairs = db.execute(stmt).all()` / `for trade, position in pairs:` block (lines 609-638) — same variable names elsewhere in the function are unaffected. `cap_tier` needs the same import added in Task 5 (`from swing_trade_ml.strategies.tier import cap_tier`) — already present after that task; if implementing this task standalone, add it.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/test_trades_strategy_attribution.py -v`
Expected: PASS

- [ ] **Step 6: Run the broader portfolio test suite**

Run: `cd backend && pytest tests/ -k "portfolio or trades or trailing_stop" -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/src/swing_trade_ml/api/v1/endpoints/portfolio.py backend/src/swing_trade_ml/schemas/__init__.py backend/tests/test_trades_strategy_attribution.py
git commit -m "$(cat <<'EOF'
Expose strategy_name/cap_tier on GET /portfolio/trades

So Reports can group the trade log by strategy without a second
endpoint — the by-strategy breakdown groups this client-side.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Frontend types + API client + tier descriptions

**Files:**
- Modify: `frontend/src/lib/tiers.ts`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/client.ts`

**Interfaces:**
- Consumes: backend shapes from Tasks 4-6.
- Produces: `StrategyPerformance`, `StrategyPerformanceWindow`, `StrategyPerformanceResponse` types; `api.strategyPerformance(): Promise<StrategyPerformanceResponse>`; `DetailedPosition.strategy_name`/`cap_tier`; `Trade.strategy_name`/`cap_tier`; `Tier.description`. Tasks 8-11 all import from here.

- [ ] **Step 1: Add a plain-English description to each tier**

In `frontend/src/lib/tiers.ts`, add a `description` field to each entry in `TIERS`:

```typescript
export const TIERS = [
  {
    match: 'ml_swing_main',
    modelName: 'swing_classifier',
    label: 'Large Cap',
    description: 'Bigger, steadier companies. Fewer trades, aimed at lower risk.',
    color: '#4f8cff',
    Icon: BuildingIcon,
  },
  {
    match: 'ml_swing_midcap',
    modelName: 'swing_classifier_midcap',
    label: 'Mid Cap',
    description: 'Mid-sized companies. A balance of risk and reward.',
    color: '#a78bfa',
    Icon: ScaleIcon,
  },
  {
    match: 'ml_swing_smallcap',
    modelName: 'swing_classifier_smallcap',
    label: 'Small Cap',
    description: 'Smaller, more volatile companies. Higher risk, higher potential reward.',
    color: '#2dd4bf',
    Icon: SproutIcon,
  },
] as const
```

- [ ] **Step 2: Add the strategy-performance types**

In `frontend/src/api/types.ts`, add after the `StrategyType` interface (end of file):

```typescript
export interface StrategyPerformanceWindow {
  trades: number
  win_rate: number
  profit_factor: number
  net_pnl: number
}

export interface StrategyPerformance {
  id: number
  name: string
  strategy_type: string
  execution_mode: 'auto' | 'advisory'
  cap_tier: 'large' | 'midcap' | 'smallcap'
  is_active: boolean
  universe_size: number
  open_positions: number
  windows: {
    last_30d: StrategyPerformanceWindow
    last_90d: StrategyPerformanceWindow
    all_time: StrategyPerformanceWindow
  }
}

export interface StrategyPerformanceResponse {
  strategies: StrategyPerformance[]
  recommended_strategy_id: number | null
  recommendation_reason: string
}
```

Also add `strategy_name: string | null` and `cap_tier: string | null` to `DetailedPosition` (after `strategy_id: number | null` at line 122):

```typescript
  strategy_id: number | null
  strategy_name: string | null
  cap_tier: string | null
```

And to `Trade` (after `last_confidence: number | null` at line 255):

```typescript
  last_confidence: number | null
  strategy_name: string | null
  cap_tier: string | null
```

- [ ] **Step 3: Add the client method**

In `frontend/src/api/client.ts`, add next to the other strategies methods (after `scanAll`, before `strategySignals`):

```typescript
  strategyPerformance: () => get<StrategyPerformanceResponse>('/strategies/performance'),
```

Add `StrategyPerformanceResponse` to the type-only import block at the top of the file (alongside `Strategy`, `StrategySignal`, `StrategyType`).

- [ ] **Step 4: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: PASS (no consumers of the new fields/types yet, so nothing should fail)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/tiers.ts frontend/src/api/types.ts frontend/src/api/client.ts
git commit -m "$(cat <<'EOF'
Add strategy-performance types, API client method, and tier copy

Wires up the frontend for GET /strategies/performance and the new
strategy_name/cap_tier fields on positions/trades. No page uses these
yet — that's the next few tasks.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Redesign the Strategies page and promote it to nav

**Files:**
- Modify: `frontend/src/pages/Strategies.tsx` (full restructure)
- Modify: `frontend/src/App.tsx:16,27-34` (nav)

**Interfaces:**
- Consumes: `api.strategyPerformance()`, `api.strategies()`, `api.activateStrategy`/`deactivateStrategy` (all existing), `tierFor`, `TierBadge`, `riskLabelFor` (all existing).

- [ ] **Step 1: Add "Strategies" to the main nav**

In `frontend/src/App.tsx`, add `LayersIcon`-style import for a strategies icon — reuse the existing `ScaleIcon` used by the Mid Cap tier badge (already imported nowhere in App.tsx; import it fresh):

```typescript
import { BarChartIcon, BriefcaseIcon, HomeIcon, LayersIcon, ScaleIcon, WalletIcon } from './components/icons'
```

Update the `NAV` array (currently lines 27-34) to insert Strategies after Dashboard:

```typescript
const NAV = [
  { to: '/dashboard', label: 'Dashboard', Icon: HomeIcon },
  { to: '/strategies', label: 'Strategies', Icon: ScaleIcon },
  { to: '/holdings', label: 'My Holdings', Icon: WalletIcon },
  { to: '/portfolio', label: 'Portfolio', Icon: BriefcaseIcon },
  { to: '/reports', label: 'Reports', Icon: BarChartIcon },
  { to: '/scans', label: 'Scan Results', Icon: LayersIcon },
  { to: '/finance', label: 'Finance', Icon: WalletIcon },
]
```

Update the comment above it (currently explains Settings/Strategies/Models are hidden) to drop the now-inaccurate claim about Strategies:

```typescript
// Settings and ML Models are still routed but deliberately left out of the
// top-level nav — they're admin/config screens, not something a day-to-day
// user needs alongside Dashboard/Strategies/Portfolio/Reports. The user and
// Log out already live in the sidebar status strip below, so Settings earned
// no place in the nav once auto-login removed the daily Kite login chore.
//
// They remain reachable by URL: /settings (watchlist editor, sync + backfill,
// scheduler status) and /models. Nothing was deleted — if either needs to
// come back, add it here.
```

- [ ] **Step 2: Rebuild Strategies.tsx around cap-tier cards + a collapsed advanced table**

Replace the full contents of `frontend/src/pages/Strategies.tsx`:

```tsx
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import type { Strategy, StrategyPerformance } from '../api/types'
import { Empty, ErrorBox, Loading } from '../components/Loading'
import SymbolPicker from '../components/SymbolPicker'
import TierBadge from '../components/TierBadge'
import { formatDate, formatPercent } from '../lib/format'
import { TIERS, tierFor } from '../lib/tiers'
import { riskLabelFor, type RiskLabel } from '../lib/strategyRisk'

const RISK_BADGE_CLASS: Record<RiskLabel, string> = {
  Conservative: 'badge-buy',
  Moderate: 'badge-hold',
  Aggressive: 'badge-sell',
}

const MIN_TRADES_FOR_RECOMMENDATION = 10

function ExecutionIcon({ auto }: { auto: boolean }) {
  return auto ? (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
      <path d="M13 2 4 14h6l-1 8 9-12h-6l1-8z" fill="currentColor" />
    </svg>
  ) : (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
      <path
        d="M9 11V6a2 2 0 0 1 4 0v5M13 6a2 2 0 0 1 4 0v6M17 8a2 2 0 0 1 4 0v6c0 3.3-2.7 6-6 6h-2a6 6 0 0 1-5-2.7L4 12"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

/** One cap-tier strategy card — the "which strategy should I use" view a
 * non-expert user actually wants, plain English first, numbers second. */
function StrategyCard({
  strategy,
  performance,
  isRecommended,
  recommendationReason,
  onToggle,
  toggling,
}: {
  strategy: Strategy
  performance: StrategyPerformance | undefined
  isRecommended: boolean
  recommendationReason: string | null
  onToggle: () => void
  toggling: boolean
}) {
  const tier = tierFor(strategy.name)
  const risk = riskLabelFor({ ...strategy.params, stop_loss_pct: strategy.stop_loss_pct ?? strategy.params.stop_loss_pct })
  const w90 = performance?.windows.last_90d
  const wAll = performance?.windows.all_time
  const hasEnoughData = (wAll?.trades ?? 0) >= MIN_TRADES_FOR_RECOMMENDATION
  const shownWindow = w90 && w90.trades >= 3 ? w90 : wAll

  return (
    <div className="card" style={{ position: 'relative' }}>
      {isRecommended && (
        <div
          className="badge badge-buy"
          style={{ position: 'absolute', top: '0.75rem', right: '0.75rem' }}
          title={recommendationReason ?? undefined}
        >
          Recommended
        </div>
      )}
      <div className="row" style={{ gap: '0.4rem', marginBottom: '0.4rem' }}>
        {tier && <TierBadge tier={tier} />}
        <span className={`badge ${RISK_BADGE_CLASS[risk.label]}`}>{risk.label}</span>
      </div>
      <h3 style={{ margin: '0 0 0.25rem' }}>{strategy.name}</h3>
      {tier && (
        <p className="muted" style={{ fontSize: '0.85rem', margin: '0 0 0.6rem' }}>
          {tier.description}
        </p>
      )}
      <div style={{ fontSize: '0.85rem', marginBottom: '0.6rem' }}>
        Watching <strong>{(performance?.universe_size ?? strategy.symbols.length) || '—'}</strong> stocks
        {performance ? `, ${performance.open_positions} held right now` : ''}.
      </div>
      <div style={{ fontSize: '0.85rem', marginBottom: '0.6rem' }}>
        {!shownWindow || shownWindow.trades === 0 ? (
          <span className="muted">No closed trades yet — check back after a few.</span>
        ) : hasEnoughData ? (
          <>
            Won <strong>{formatPercent(shownWindow.win_rate, 0)}</strong> of {shownWindow.trades} recent trades.
          </>
        ) : (
          <span className="muted">
            {wAll?.trades ?? 0} closed trade{(wAll?.trades ?? 0) === 1 ? '' : 's'} so far — needs{' '}
            {MIN_TRADES_FOR_RECOMMENDATION - (wAll?.trades ?? 0)} more before a reliable win rate shows.
          </span>
        )}
      </div>
      <button onClick={onToggle} disabled={toggling}>
        {strategy.is_active ? 'Deactivate' : 'Activate'}
      </button>
      <span className={`badge ${strategy.is_active ? 'badge-on' : 'badge-off'}`} style={{ marginLeft: '0.5rem' }}>
        {strategy.is_active ? 'active' : 'inactive'}
      </span>
    </div>
  )
}

export default function Strategies() {
  const queryClient = useQueryClient()
  const [showForm, setShowForm] = useState(false)
  const [symbols, setSymbols] = useState<string[]>([])

  const strategies = useQuery({ queryKey: ['strategies'], queryFn: api.strategies })
  const performance = useQuery({ queryKey: ['strategyPerformance'], queryFn: api.strategyPerformance })
  const types = useQuery({ queryKey: ['strategyTypes'], queryFn: api.strategyTypes })
  const positions = useQuery({ queryKey: ['positions'], queryFn: api.positions })

  const openCountByStrategy = useMemo(() => {
    const counts = new Map<number, number>()
    for (const p of positions.data ?? []) {
      if (p.strategy_id == null) continue
      counts.set(p.strategy_id, (counts.get(p.strategy_id) ?? 0) + 1)
    }
    return counts
  }, [positions.data])

  const performanceById = useMemo(
    () => new Map((performance.data?.strategies ?? []).map((p) => [p.id, p])),
    [performance.data],
  )

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['strategies'] })
    queryClient.invalidateQueries({ queryKey: ['strategyPerformance'] })
  }

  const toggle = useMutation({
    mutationFn: ({ id, active }: { id: number; active: boolean }) =>
      active ? api.deactivateStrategy(id) : api.activateStrategy(id),
    onSuccess: invalidate,
  })

  const remove = useMutation({
    mutationFn: (id: number) => api.deleteStrategy(id),
    onSuccess: invalidate,
  })

  const create = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.createStrategy(body),
    onSuccess: () => {
      invalidate()
      setShowForm(false)
      setSymbols([])
    },
  })

  const scan = useMutation({
    mutationFn: api.scanAll,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['signals'] })
      queryClient.invalidateQueries({ queryKey: ['positions'] })
      queryClient.invalidateQueries({ queryKey: ['summary'] })
    },
  })

  if (strategies.isLoading) return <Loading />
  if (strategies.error) return <ErrorBox error={strategies.error} />

  const rows = strategies.data ?? []
  const capTierRows = TIERS.map((tier) => rows.find((s) => s.name === tier.match)).filter(
    (s): s is Strategy => !!s,
  )
  const advancedRows = rows.filter((s) => !TIERS.some((t) => t.match === s.name))
  const recommendedId = performance.data?.recommended_strategy_id ?? null

  return (
    <>
      <div className="page-head">
        <h1>Strategies</h1>
        <div className="row">
          <button onClick={() => scan.mutate()} disabled={scan.isPending}>
            {scan.isPending ? 'Scanning…' : 'Run scan now'}
          </button>
          <button className="primary" onClick={() => setShowForm((v) => !v)}>
            {showForm ? 'Cancel' : 'New strategy'}
          </button>
        </div>
      </div>

      <p className="muted" style={{ marginTop: 0 }}>
        Each card below is a trading approach the bot can run. Activating one only affects new
        picks going forward — anything already bought keeps running under whatever strategy
        picked it.
      </p>

      {scan.data && (
        <div className="banner banner-info">
          Scan complete — {scan.data.instruments_evaluated} instruments evaluated,{' '}
          {scan.data.signals_generated} signals ({scan.data.buys} buys, {scan.data.exits} exits),{' '}
          {scan.data.executed} executed
          {scan.data.errors.length > 0 && `, ${scan.data.errors.length} errors`}.
        </div>
      )}
      {(create.error || toggle.error || remove.error || scan.error) && (
        <ErrorBox error={create.error ?? toggle.error ?? remove.error ?? scan.error} />
      )}

      {showForm && (
        <form
          className="card"
          style={{ marginBottom: '1.5rem' }}
          onSubmit={(event) => {
            event.preventDefault()
            const form = new FormData(event.currentTarget)
            create.mutate({
              name: String(form.get('name')),
              strategy_type: String(form.get('strategy_type')),
              description: String(form.get('description') || ''),
              symbols,
              params: {},
            })
          }}
        >
          <h2>New strategy</h2>
          <div className="grid" style={{ marginBottom: '0.8rem' }}>
            <label>
              <div className="stat-label">Name</div>
              <input name="name" required placeholder="ML Swing — large caps" />
            </label>
            <label>
              <div className="stat-label">Type</div>
              <select name="strategy_type" required>
                {types.data?.map((t) => (
                  <option key={t.strategy_type} value={t.strategy_type}>
                    {t.display_name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <div className="stat-label">Symbols (blank = whole watchlist)</div>
              <SymbolPicker
                value={symbols}
                onChange={setSymbols}
                placeholder="Search INFY, TCS, RELIANCE…"
              />
            </label>
            <label>
              <div className="stat-label">Description</div>
              <input name="description" placeholder="Optional" />
            </label>
          </div>
          <button className="primary" type="submit" disabled={create.isPending}>
            {create.isPending ? 'Creating…' : 'Create'}
          </button>
          <p className="muted" style={{ fontSize: '0.82rem' }}>
            New strategies start inactive. Review the parameters, then activate.
          </p>
        </form>
      )}

      {!capTierRows.length ? (
        <Empty label="No cap-tier strategies configured yet." />
      ) : (
        <div className="grid" style={{ gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', marginBottom: '1.5rem' }}>
          {capTierRows.map((s) => (
            <StrategyCard
              key={s.id}
              strategy={s}
              performance={performanceById.get(s.id)}
              isRecommended={recommendedId === s.id}
              recommendationReason={performance.data?.recommendation_reason ?? null}
              onToggle={() => toggle.mutate({ id: s.id, active: s.is_active })}
              toggling={toggle.isPending}
            />
          ))}
        </div>
      )}

      <details>
        <summary style={{ cursor: 'pointer', marginBottom: '0.75rem' }}>
          Advanced strategies ({advancedRows.length})
        </summary>
        <div className="table-wrap" style={{ marginBottom: '1.5rem' }}>
          {!advancedRows.length ? (
            <Empty label="No other strategies configured." />
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Type</th>
                  <th>Universe</th>
                  <th>Execution</th>
                  <th>Mode</th>
                  <th>Status</th>
                  <th className="num">Open</th>
                  <th>Created</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {advancedRows.map((s) => {
                  const openCount = openCountByStrategy.get(s.id) ?? 0
                  return (
                    <tr key={s.id}>
                      <td>
                        <strong>{s.name}</strong>
                        {s.description && (
                          <div className="muted" style={{ fontSize: '0.75rem' }}>
                            {s.description}
                          </div>
                        )}
                      </td>
                      <td className="muted">{s.strategy_type}</td>
                      <td className="muted" title={s.symbols.length ? s.symbols.join(', ') : undefined}>
                        {s.symbols.length ? `${s.symbols.length} symbols` : 'full watchlist'}
                      </td>
                      <td>
                        <span
                          className="row"
                          style={{ gap: '0.35rem', color: 'var(--text-dim)', fontSize: '0.85rem' }}
                          title={
                            s.execution_mode === 'auto'
                              ? 'Places real orders automatically on a signal'
                              : 'Only recommends — you record the fill yourself'
                          }
                        >
                          <ExecutionIcon auto={s.execution_mode === 'auto'} />
                          {s.execution_mode}
                        </span>
                      </td>
                      <td>
                        <span className={`badge ${s.mode === 'live' ? 'badge-live' : 'badge-paper'}`}>
                          {s.mode}
                        </span>
                      </td>
                      <td>
                        <span className={`badge ${s.is_active ? 'badge-on' : 'badge-off'}`}>
                          {s.is_active ? 'active' : 'inactive'}
                        </span>
                      </td>
                      <td className="num mono">{openCount}</td>
                      <td className="muted">{formatDate(s.created_at)}</td>
                      <td>
                        <div className="row">
                          <button
                            onClick={() => toggle.mutate({ id: s.id, active: s.is_active })}
                            disabled={toggle.isPending}
                          >
                            {s.is_active ? 'Deactivate' : 'Activate'}
                          </button>
                          {!s.is_active && (
                            <button
                              className="danger"
                              onClick={() => confirm(`Delete "${s.name}"?`) && remove.mutate(s.id)}
                            >
                              Delete
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>

        <h2>Available strategy types</h2>
        <div className="grid">
          {types.data?.map((t) => (
            <div className="card" key={t.strategy_type}>
              <div className="stat-label">{t.strategy_type}</div>
              <div style={{ fontWeight: 600, marginBottom: '0.35rem' }}>{t.display_name}</div>
              <p className="muted" style={{ fontSize: '0.82rem', margin: 0 }}>
                {t.description}
              </p>
            </div>
          ))}
        </div>
      </details>
    </>
  )
}
```

- [ ] **Step 3: Typecheck and lint**

Run: `cd frontend && npm run typecheck && npm run lint`
Expected: PASS

- [ ] **Step 4: Manual verification**

Run: `cd frontend && npm run dev` (and backend `cd backend && uvicorn swing_trade_ml.main:app --reload` if not already running), open `/strategies` in a browser. Confirm: three cap-tier cards render with tier badge, plain-English blurb, stock count, win-rate line (or the "needs N more trades" fallback), Activate/Deactivate button; "Advanced strategies" is collapsed by default and expands to the old table; "Strategies" appears in the left nav between Dashboard and My Holdings.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Strategies.tsx frontend/src/App.tsx
git commit -m "$(cat <<'EOF'
Redesign Strategies as a user-facing tab with cap-tier cards

Cards show tier, plain-English description, stock count, win rate
with a "Recommended" badge once a strategy has enough closed trades.
The old admin table (sma_crossover, long_term_value, real_trading,
create/delete) moves to a collapsed "Advanced strategies" section
instead of being deleted. Promoted to the main nav.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: Strategy column on the shared positions table

**Files:**
- Modify: `frontend/src/pages/Positions.tsx:122-174` (`PositionsTable`'s `<thead>`/row rendering)

**Interfaces:**
- Consumes: `DetailedPosition.strategy_name`/`cap_tier` (Task 7). No signature change to `PositionsTable`'s props — used by both `Positions.tsx` and `Holdings.tsx` already.

- [ ] **Step 1: Add the column header**

In `frontend/src/pages/Positions.tsx`, in `PositionsTable`'s `<thead>` (currently lines 124-174), add a new `<th>` right after the `Stock` column (after line 125's `<th className="sticky-col">Stock</th>`):

```tsx
          <th className="sticky-col">Stock</th>
          <th>Strategy</th>
```

- [ ] **Step 2: Add the cell**

In the `<tbody>` row rendering (the `sorted.map((p) => ...)` block), add a new `<td>` right after the closing `</td>` of the sticky Stock cell (after line 203's `</td>`, before `<td className="num">{p.quantity}</td>`):

```tsx
              <td>
                {p.strategy_name ? (
                  <span className="muted" style={{ fontSize: '0.8rem' }} title={p.cap_tier ?? undefined}>
                    {p.strategy_name}
                  </span>
                ) : (
                  <span className="muted">—</span>
                )}
              </td>
```

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: PASS

- [ ] **Step 4: Manual verification**

With the dev server running, open `/portfolio` and `/holdings`. Confirm every position row now shows a "Strategy" column with the strategy name (e.g. `real_trading` on Holdings rows, `ml_swing_main`/`_midcap`/`_smallcap` on paper positions).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Positions.tsx
git commit -m "$(cat <<'EOF'
Show which strategy opened each position, on Portfolio and Holdings

One shared change — PositionsTable backs both pages. Uses the
strategy_name field added to positions/detailed.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: Strategy performance strip on the Dashboard

**Files:**
- Modify: `frontend/src/pages/Dashboard.tsx` (imports near line 10; new query near line 203; new section rendered near line 339, right after the `page-head` banner block and before the tab bar)

**Interfaces:**
- Consumes: `api.strategyPerformance()` (Task 7), `TIERS`/`tierFor` (already imported).

- [ ] **Step 1: Add the import and query**

In `frontend/src/pages/Dashboard.tsx`, add to the existing `api` usage — no new import line needed since `api` is already imported; add the query next to the existing `strategies` query (after line 203's closing `})`):

```typescript
  const strategyPerformance = useQuery({
    queryKey: ['strategyPerformance'],
    queryFn: api.strategyPerformance,
    enabled: tab === 'buy',
  })
```

- [ ] **Step 2: Render a compact performance strip**

Insert a new block right before the existing `<details>` "Why isn't more showing up here?" section (before line 566's `<details ...>`), inside the same `tab === 'buy'` branch:

```tsx
          {strategyPerformance.data && (
            <div className="grid" style={{ gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', marginBottom: '1rem' }}>
              {TIERS.map((tier) => {
                const perf = strategyPerformance.data!.strategies.find((s) => s.name === tier.match)
                const isRecommended = strategyPerformance.data!.recommended_strategy_id === perf?.id
                const w = perf?.windows.last_90d
                return (
                  <div className="card" key={tier.match} style={{ position: 'relative' }}>
                    {isRecommended && (
                      <div
                        className="badge badge-buy"
                        style={{ position: 'absolute', top: '0.6rem', right: '0.6rem', fontSize: '0.7rem' }}
                        title={strategyPerformance.data!.recommendation_reason}
                      >
                        Recommended
                      </div>
                    )}
                    <div className="row" style={{ gap: '0.35rem', marginBottom: '0.3rem' }}>
                      <span style={{ color: tier.color, display: 'flex' }}>
                        <tier.Icon />
                      </span>
                      <span className="stat-label" style={{ margin: 0 }}>{tier.label}</span>
                    </div>
                    {!w || w.trades === 0 ? (
                      <div className="muted" style={{ fontSize: '0.82rem' }}>No closed trades yet</div>
                    ) : (
                      <div style={{ fontSize: '0.82rem' }}>
                        Won <strong>{formatPercent(w.win_rate, 0)}</strong> of {w.trades} in the last 90 days
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
```

`formatPercent` is already imported in `Dashboard.tsx` (part of the existing `formatCurrency, formatDateTime, ...` import block) — confirm and reuse rather than re-importing.

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: PASS

- [ ] **Step 4: Manual verification**

With the dev server running, open `/dashboard`, switch to the "Worth buying" tab. Confirm a three-card strip (Large/Mid/Small Cap) appears above the "Why isn't more showing up here?" details section, each showing 90-day win rate or "No closed trades yet", with a "Recommended" ribbon on the best-performing eligible one once real data exists.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Dashboard.tsx
git commit -m "$(cat <<'EOF'
Show per-tier win rate and the recommended strategy on the Dashboard

Reuses GET /strategies/performance rather than a second data source —
same TIERS/tierFor convention the existing tier-comparison block uses.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 11: Reports — drop the bar chart, add a by-strategy table

**Files:**
- Modify: `frontend/src/pages/Reports.tsx`

**Interfaces:**
- Consumes: `Trade.strategy_name`/`cap_tier` (Task 7).

- [ ] **Step 1: Remove the Recharts import and chart block**

In `frontend/src/pages/Reports.tsx`, delete the import line (line 3):

```typescript
import { Bar, BarChart, CartesianGrid, Cell, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
```

Delete the `chartData` memo (line 77):

```typescript
  const chartData = useMemo(() => [...rows].reverse(), [rows])
```

Delete the entire chart block (lines 165-190, the `<div className="card" style={{ height: 300, ... }}>...</div>` containing `<ResponsiveContainer>`).

- [ ] **Step 2: Add a by-strategy grouping function and table**

Add next to `groupTrades` (after its closing brace, before `const PERIODS = ...`):

```typescript
interface StrategyRow {
  key: string
  name: string
  capTier: string | null
  trades: number
  wins: number
  net: number
}

function groupByStrategy(rows: Trade[]): StrategyRow[] {
  const byStrategy = new Map<string, StrategyRow>()
  for (const t of rows) {
    const key = t.strategy_name ?? 'Unknown'
    const row = byStrategy.get(key) ?? { key, name: key, capTier: t.cap_tier, trades: 0, wins: 0, net: 0 }
    row.trades += 1
    row.wins += t.is_win ? 1 : 0
    row.net += t.net_pnl
    byStrategy.set(key, row)
  }
  return [...byStrategy.values()].sort((a, b) => b.net - a.net)
}
```

Add the computed rows next to `const rows = useMemo(...)` (after line 76):

```typescript
  const byStrategyRows = useMemo(() => groupByStrategy(trades.data ?? []), [trades.data])
```

- [ ] **Step 3: Render the by-strategy table**

Insert a new section right after the period summary table (`</div>` closing the `table-wrap` that ends around the former line 219) and before `<h2>Every trade</h2>`:

```tsx
          <h2>By strategy</h2>
          <div className="table-wrap" style={{ marginBottom: '1.5rem' }}>
            {!byStrategyRows.length ? (
              <Empty label="No closed trades yet." />
            ) : (
              <table>
                <thead>
                  <tr>
                    <th className="sticky-col">Strategy</th>
                    <th className="num">Trades</th>
                    <th className="num">Win rate</th>
                    <th className="num">Net P&amp;L</th>
                  </tr>
                </thead>
                <tbody>
                  {byStrategyRows.map((r) => (
                    <tr key={r.key}>
                      <td className="sticky-col">
                        <strong>{r.name}</strong>
                        {r.capTier && <span className="muted" style={{ marginLeft: '0.4rem', fontSize: '0.78rem' }}>{r.capTier}</span>}
                      </td>
                      <td className="num">{r.trades}</td>
                      <td className="num">{formatPercent(r.wins / r.trades, 0)}</td>
                      <td className={`num ${pnlClass(r.net)}`}>{formatCurrency(r.net)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
```

- [ ] **Step 4: Remove the now-unused `formatCompact` import if nothing else in the file uses it**

Check the rest of `Reports.tsx` for any remaining use of `formatCompact` (it was only used by the deleted chart's Y-axis tick formatter). If unused, remove it from the import on line 9:

```typescript
import { formatCurrency, formatDate, formatPercent, formatSignedPercent, pnlClass } from '../lib/format'
```

- [ ] **Step 5: Typecheck and lint**

Run: `cd frontend && npm run typecheck && npm run lint`
Expected: PASS

- [ ] **Step 6: Manual verification**

With the dev server running, open `/reports`. Confirm: no chart renders, the stat tiles and period table still work, a new "By strategy" table appears between the period table and "Every trade" showing each strategy's trade count/win rate/net P&L.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/Reports.tsx
git commit -m "$(cat <<'EOF'
Replace the Reports bar chart with a by-strategy breakdown table

The chart repeated what the period table already showed as numbers;
the by-strategy table is new information (which strategy is actually
making money) the chart never showed at all.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Post-plan check

After Task 11, run the full backend suite and frontend build once to confirm nothing regressed end-to-end:

Run: `cd backend && pytest -q`
Run: `cd frontend && npm run typecheck && npm run lint && npm run build`

Both should be clean. If `recharts` has no remaining importers anywhere in `frontend/src/`, it's fine to leave the dependency in `package.json` unused (per spec §6d — removing the package itself was explicitly out of scope) rather than doing a separate dependency-pruning pass.
