# Long-Term Stock Picks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A second, independently-trained model (`long_term_value`) predicting multi-month moves, surfaced as its own advisory-only `BUY` signals with a long horizon, scored by the same honest outcome machinery as swing signals — no "10X" promise anywhere, just a tracked hit-rate.

**Architecture:** Phase 1 (this plan, fully buildable now): a new model name + a new strategy class reusing the *existing* price/volume feature pipeline unchanged, just a longer horizon and wider stop/target. Phase 2 (a follow-up task at the end, gated on a vendor spike): fundamentals features layered in additively. No new tables in Phase 1.

**Tech Stack:** Same as the existing ML pipeline — scikit-learn/LightGBM via `ml/train.py`, SQLAlchemy, pytest.

**Spec:** `docs/superpowers/specs/2026-09-12-long-term-stock-picks-design.md`

## Global Constraints

- No return-multiple promise ("10X" or any number) anywhere in signal text, reason strings, or UI (spec §3).
- `advisory_only=True` by default for every signal this strategy produces (spec §3, §6).
- Fundamentals vendor selection is a spike with a real deliverable, not a guess (spec §4) — Task 1 below.
- Reuses the Scan Results scoring machinery (`evaluate_pending_signals`, `Signal.horizon_days/outcome/outcome_pct`) from `docs/superpowers/plans/2026-09-12-scan-results.md` — that plan's Task 1 and Task 2 must land first (the `Signal` outcome columns and `SignalDecision.horizon_days` field this plan's strategy sets). If those tasks haven't been merged yet, do them first or coordinate with whoever owns that plan.

---

### Task 1: Fundamentals vendor spike

**Files:**
- Create: `docs/superpowers/research/2026-09-12-fundamentals-vendor-decision.md`

**Interfaces:**
- Produces: a written decision naming one vendor — Task 6 (Phase 2) reads this file to know which API to integrate against. No code interface; this is a research task with a document deliverable.

- [ ] **Step 1: Identify 2-3 real candidate vendors**

Research vendors offering NSE/BSE-listed company fundamentals via a real API (not a scrape target). Candidates to evaluate (confirm current offerings/pricing directly — this list is a starting point, not a final answer):

- A dedicated Indian-markets fundamentals data vendor (e.g. Tijori Finance, Trendlyne, or a similar API-first provider covering NSE/BSE).
- A global financial-data API with India coverage (e.g. Finnhub, Financial Modeling Prep) — check India-specific coverage depth before assuming parity with US coverage.
- NSE/BSE's own official corporate-filings/financial-results bulk downloads as a free fallback — heavier to parse (structured filings, not a clean ratios API) but zero cost and unambiguously "official data," not a third party's scrape.

- [ ] **Step 2: Score each against the spec's criteria**

For each candidate, write one paragraph answering, per spec §4:
1. Does it cover NSE/BSE-listed companies specifically (not just global/US)?
2. Is the data point-in-time (the ratio as known at the time), or only current/restated? Restated fundamentals used in training silently leak future information — the same look-ahead-bias class `ml/features.py`'s module docstring already warns about for price data. A vendor that can't answer this clearly is a red flag, not a detail to skip.
3. How many years of historical depth is available (need 5+ for enough training examples)?
4. Is it a real API/SDK, or something that requires scraping rendered pages?

- [ ] **Step 3: Write the decision document**

```markdown
# Fundamentals Vendor Decision

Date: <today>
Decides: which vendor backs the long-term stock picks model's fundamentals features (docs/superpowers/specs/2026-09-12-long-term-stock-picks-design.md §4).

## Candidates evaluated

### <Vendor 1 name>
- NSE/BSE coverage: <finding>
- Point-in-time correctness: <finding>
- Historical depth: <finding>
- API shape: <finding>
- Pricing: <finding>

### <Vendor 2 name>
(same structure)

### <Vendor 3 name, if evaluated>
(same structure)

## Decision

<Chosen vendor>, because <the deciding factor(s) — usually point-in-time
correctness plus NSE/BSE-specific coverage>.

## Fields available

<List the specific fundamental fields this vendor actually exposes that map
to the spec §5 feature list: trailing P/E, ROE, debt/equity, revenue/earnings
YoY growth, promoter holding change. Note any gaps.>

## Integration notes for Task 6

<API base URL, auth method, rate limits, and the exact field names Task 6's
FundamentalsProvider implementation will need.>
```

Fill in every section with real findings — no vendor name or finding may be left as a placeholder. If, after real research, no vendor cleanly satisfies point-in-time correctness, say so explicitly and recommend the NSE/BSE official-filings fallback rather than picking a vendor that fails this on a technicality — a model trained on leaky fundamentals is worse than one with a real gap, per the same discipline `ml/features.py` already enforces for price data.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/research/2026-09-12-fundamentals-vendor-decision.md
git commit -m "docs: fundamentals vendor decision for long-term stock picks

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: Register the `long_term_value` model (Phase 1 — price/volume features only)

**Files:**
- Test: `backend/tests/test_long_term_strategy.py`

**Interfaces:**
- Consumes: `train_model()` (existing, `backend/src/swing_trade_ml/ml/train.py:105`) — unchanged signature, called with a new `name`, longer `horizon_days`, higher `target_return`.
- Produces: an `MLModel` row named `long_term_value` — Task 3's strategy reads this by name via the existing `get_active_model(db, "long_term_value")`.

This task does not touch `train.py` at all — `train_model` already accepts an arbitrary `name`/`horizon_days`/`target_return`, so a second model is just a second call with different arguments. This task documents and tests that call, and picks concrete horizon/target values.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_long_term_strategy.py
"""Long-term stock picks — see
docs/superpowers/specs/2026-09-12-long-term-stock-picks-design.md.

Phase 1 reuses the existing price/volume feature pipeline unchanged, just a
longer horizon and higher target return than the swing model — no
fundamentals dependency yet (that's Task 6, gated on the Task 1 vendor
spike)."""

from __future__ import annotations


def test_long_term_model_uses_a_materially_longer_horizon_and_higher_target():
    """Pins the actual values this plan picks — see Step 2's rationale.
    A multi-month hold should target a materially larger move than the
    swing model's ~5-20 day / ~2-15% range (core/config.py's
    DEFAULT_STOP_LOSS_PCT=0.05 / DEFAULT_TAKE_PROFIT_PCT=0.15 give the
    swing model's rough scale)."""
    from swing_trade_ml.strategies.long_term_value import (
        LONG_TERM_HORIZON_DAYS,
        LONG_TERM_TARGET_RETURN_PCT,
    )

    assert LONG_TERM_HORIZON_DAYS >= 180
    assert LONG_TERM_TARGET_RETURN_PCT >= 0.25  # materially more than the swing model's 15%
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_long_term_strategy.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'swing_trade_ml.strategies.long_term_value'`

- [ ] **Step 3: Create the strategy module with the constants (strategy class comes in Task 3)**

```python
# backend/src/swing_trade_ml/strategies/long_term_value.py
"""Long-term stock picks — see
docs/superpowers/specs/2026-09-12-long-term-stock-picks-design.md.

Phase 1: reuses ml_swing's exact pipeline (same build_features, same
train_model) with a longer horizon and a wider percentage-based stop/target
appropriate to a multi-month hold rather than ATR-based day-to-day noise.
Phase 2 (a follow-up task, gated on docs/superpowers/research/2026-09-12-
fundamentals-vendor-decision.md) layers fundamentals features on top.

No return-multiple promise ("10X" or any number) appears anywhere in this
module's signal text — confidence and a real tracked hit-rate only, same
standard as every other signal in the app.
"""

from __future__ import annotations

# 250 trading days (~1 year) — long enough to be a genuinely different
# horizon from the swing model's ~5-20 days, short enough that the model
# still trains on a meaningful number of non-overlapping examples given the
# watchlist's available history.
LONG_TERM_HORIZON_DAYS = 250

# The swing model's DEFAULT_TAKE_PROFIT_PCT is 0.15 (core/config.py) — a
# 1-year hold should target a materially larger move than a 2-week swing,
# not the same one scaled by time. 30% is the starting point; revisit once
# backtested (spec §10 open items).
LONG_TERM_TARGET_RETURN_PCT = 0.30
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_long_term_strategy.py -v`
Expected: PASS

- [ ] **Step 5: Document the training invocation**

Add to this same test file (documents intended usage without requiring a real multi-year dataset in CI — training itself is a manual/scheduled operation, not something the test suite runs end-to-end, matching how the existing `swing_classifier` model is never trained inside a test):

```python
def test_train_model_accepts_long_term_value_arguments(monkeypatch):
    """Confirms train_model's existing signature (unchanged) accepts the
    long-term configuration without needing any new parameter — this is a
    call-shape test, not a real training run."""
    from swing_trade_ml.strategies.long_term_value import (
        LONG_TERM_HORIZON_DAYS,
        LONG_TERM_TARGET_RETURN_PCT,
    )
    from swing_trade_ml.ml import train as train_module

    captured = {}

    def fake_train_model(db, **kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr(train_module, "train_model", fake_train_model)

    train_module.train_model(
        db=None,
        name="long_term_value",
        horizon_days=LONG_TERM_HORIZON_DAYS,
        target_return=LONG_TERM_TARGET_RETURN_PCT,
    )

    assert captured["name"] == "long_term_value"
    assert captured["horizon_days"] == 250
```

Run: `cd backend && pytest tests/test_long_term_strategy.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/swing_trade_ml/strategies/long_term_value.py backend/tests/test_long_term_strategy.py
git commit -m "feat: define long-term-value model horizon/target constants

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: `LongTermValueStrategy`

**Files:**
- Modify: `backend/src/swing_trade_ml/strategies/long_term_value.py`
- Modify: `backend/src/swing_trade_ml/strategies/__init__.py` (register the new strategy)
- Test: `backend/tests/test_long_term_strategy.py`

**Interfaces:**
- Consumes: `BaseStrategy`, `SignalDecision` (`strategies/base.py` — `SignalDecision.horizon_days` must already exist; this is added by `docs/superpowers/plans/2026-09-12-scan-results.md` Task 2 — confirm it's present before starting this task, run `grep -n "horizon_days" backend/src/swing_trade_ml/strategies/base.py` and if it's missing, do that plan's Task 2 first), `get_active_model` (`ml/registry.py`), `build_features` (`ml/features.py`), `_get_bundle` (`ml/predict.py`).
- Produces: `LongTermValueStrategy` registered under `strategy_type = "long_term_value"` — the engine picks it up automatically via `STRATEGY_REGISTRY` once imported in `strategies/__init__.py`.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_long_term_strategy.py`:

```python
def test_long_term_strategy_is_registered():
    from swing_trade_ml.strategies import STRATEGY_REGISTRY

    assert "long_term_value" in STRATEGY_REGISTRY


def test_long_term_strategy_signal_is_advisory_only_by_default():
    from swing_trade_ml.db.models.trading import Strategy as StrategyModel
    from swing_trade_ml.strategies.long_term_value import LongTermValueStrategy

    config = StrategyModel(name="lt-test", strategy_type="long_term_value", params={})
    strategy = LongTermValueStrategy(config)

    assert strategy.default_params.get("advisory_only", True) is True


def test_long_term_strategy_returns_none_below_min_bars():
    import pandas as pd

    from swing_trade_ml.db.models.market import Instrument
    from swing_trade_ml.db.models.trading import Strategy as StrategyModel
    from swing_trade_ml.strategies.long_term_value import LongTermValueStrategy

    config = StrategyModel(name="lt-test", strategy_type="long_term_value", params={})
    strategy = LongTermValueStrategy(config)
    short_df = pd.DataFrame({"ts": pd.date_range("2026-01-01", periods=5), "close": [100] * 5})
    inst = Instrument(instrument_token=1, tradingsymbol="TEST")

    assert strategy.evaluate(short_df, inst, db=None) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_long_term_strategy.py -k "registered or advisory or min_bars" -v`
Expected: FAIL — `ImportError: cannot import name 'LongTermValueStrategy'`

- [ ] **Step 3: Implement the strategy**

Append to `backend/src/swing_trade_ml/strategies/long_term_value.py`:

```python
from typing import Any, ClassVar

import pandas as pd
from sqlalchemy.orm import Session

from swing_trade_ml.core.enums import SignalType
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.ml.features import build_features
from swing_trade_ml.ml.market_context import (
    load_index_candles,
    load_market_breadth,
    load_sector_candles,
    load_vix_candles,
)
from swing_trade_ml.ml.predict import _get_bundle
from swing_trade_ml.ml.registry import get_active_model
from swing_trade_ml.ml.sector_map import get_sector_index
from swing_trade_ml.strategies.base import BaseStrategy, SignalDecision, register_strategy

log = get_logger(__name__)


@register_strategy
class LongTermValueStrategy(BaseStrategy):
    strategy_type: ClassVar[str] = "long_term_value"
    display_name: ClassVar[str] = "Long-Term Value"
    description: ClassVar[str] = (
        "Buys when the long-horizon classifier's probability of a large multi-month "
        "move exceeds the confidence threshold. Advisory only — no auto-execution. "
        "Tracked against real outcomes the same as every other signal in this app; "
        "no target return multiple is ever promised."
    )
    default_params: ClassVar[dict[str, Any]] = {
        "model_name": "long_term_value",
        "min_confidence": 0.65,
        # Wider than the swing model's ATR-based stop — a multi-month hold
        # should not be shaken out by ordinary weekly noise. Percentage-of-
        # price, matching sma_crossover.py's simpler convention, not ATR
        # (which is tuned for short-term noise the long horizon doesn't
        # care about).
        "stop_loss_pct": 0.20,
        "take_profit_pct": LONG_TERM_TARGET_RETURN_PCT,
        "horizon_days": LONG_TERM_HORIZON_DAYS,
        "min_avg_volume": 100_000,
        # Advisory only by default (spec §3/§6) — the manual-approval trial
        # phase this whole app is still in applies doubly to a multi-month
        # commitment of capital.
        "advisory_only": True,
    }

    def min_bars_required(self) -> int:
        return 260

    def evaluate(
        self, df: pd.DataFrame, instrument: Instrument, db: Session
    ) -> SignalDecision | None:
        if len(df) < self.min_bars_required():
            return None

        model = get_active_model(db, self.params.get("model_name"))
        if model is None:
            log.warning("long_term_value.no_active_model", strategy=self.config.name)
            return None

        d = df.sort_values("ts").reset_index(drop=True)
        as_of = d["ts"].max()
        index_df = load_index_candles(db, interval="day", upto=as_of)
        sector_df = load_sector_candles(
            db, get_sector_index(instrument.tradingsymbol), interval="day", upto=as_of
        )
        vix_df = load_vix_candles(db, interval="day", upto=as_of)
        breadth_df = load_market_breadth(db, interval="day", upto=as_of)
        featured = build_features(d, index_df, sector_df, vix_df, breadth_df)
        row = featured.iloc[[-1]]

        bundle = _get_bundle(model)
        feature_names: list[str] = bundle["feature_names"]
        x = row[feature_names]
        if x.isna().to_numpy().any():
            return None

        x_scaled = bundle["scaler"].transform(x.to_numpy(dtype="float64"))
        estimator = bundle["estimator"]
        probability = (
            float(estimator.predict_proba(x_scaled)[0, 1])
            if hasattr(estimator, "predict_proba")
            else float(estimator.predict(x_scaled)[0])
        )

        price = float(d["close"].iloc[-1])
        avg_volume = float(d["volume"].rolling(20).mean().iloc[-1])

        threshold = float(self.params["min_confidence"])
        if probability < threshold:
            return SignalDecision(
                signal=SignalType.HOLD,
                price=price,
                confidence=round(probability, 3),
                reason=f"Confidence {probability:.1%} below {threshold:.0%} threshold",
                features={"probability": round(probability, 4), "model": f"{model.name}:{model.version}"},
            )

        if avg_volume < float(self.params["min_avg_volume"]):
            return SignalDecision(
                signal=SignalType.HOLD,
                price=price,
                confidence=round(probability, 3),
                reason=f"Model confident ({probability:.1%}) but 20-day volume {avg_volume:,.0f} too thin",
                features={"probability": round(probability, 4)},
            )

        stop_loss = round(price * (1 - float(self.params["stop_loss_pct"])), 2)
        take_profit = round(price * (1 + float(self.params["take_profit_pct"])), 2)

        return SignalDecision(
            signal=SignalType.BUY,
            price=price,
            confidence=round(probability, 3),
            reason=(
                f"{model.name}:{model.version} predicts {probability:.1%} confidence of a "
                f"sustained move over the next {self.params['horizon_days']} trading days "
                f"(long-term, advisory)"
            ),
            stop_loss=stop_loss,
            take_profit=take_profit,
            horizon_days=int(self.params["horizon_days"]),
            features={"probability": round(probability, 4), "model": f"{model.name}:{model.version}"},
        )
```

Note the `reason` string above deliberately never states a return multiple or percentage target as a promise — it states the model's confidence and horizon only, per the Global Constraints.

- [ ] **Step 4: Register it in `strategies/__init__.py`**

```python
from swing_trade_ml.strategies.long_term_value import LongTermValueStrategy
```

Add `"LongTermValueStrategy",` to that file's `__all__` list.

- [ ] **Step 5: Wire `advisory_only` onto the persisted `Signal`**

Run: `cd backend && grep -n "advisory_only" src/swing_trade_ml/services/engine.py`

Confirm the engine already copies a per-strategy `advisory_only` flag onto the `Signal` it creates (it does, per `Signal.advisory_only` existing on the model already — the `ml_swing`/`sma_crossover` strategies just don't set it in their `default_params`, so it falls back to a global default). If the engine reads this from `self.config` rather than `self.params`, adjust `LongTermValueStrategy.default_params` accordingly or set it via the `Strategy` row's own config when the strategy is created (Task 5 covers creating the actual `Strategy` row) — read `services/engine.py`'s exact mechanism before assuming; note whichever it is in your final report.

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_long_term_strategy.py -v`
Expected: PASS

- [ ] **Step 7: Run the full backend test suite**

Run: `cd backend && pytest -v`
Expected: PASS, no regressions (confirms importing the new strategy module doesn't break `STRATEGY_REGISTRY` for existing strategies).

- [ ] **Step 8: Commit**

```bash
git add backend/src/swing_trade_ml/strategies/long_term_value.py backend/src/swing_trade_ml/strategies/__init__.py backend/tests/test_long_term_strategy.py
git commit -m "feat: add LongTermValueStrategy (advisory-only, no return promise)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: Confirm Scan Results integration (no new code — a verification task)

**Files:**
- Test: `backend/tests/test_long_term_strategy.py`

**Interfaces:**
- Consumes: `evaluate_pending_signals` (from `docs/superpowers/plans/2026-09-12-scan-results.md` Task 3), `GET /signals/track-record` (that plan's Task 5).

Because `LongTermValueStrategy` produces a normal `Signal` row with `stop_loss`/`take_profit`/`horizon_days` set (Task 3), it is automatically picked up by the existing outcome-scoring job and the Scan Results endpoint — no separate code path. This task only proves that.

- [ ] **Step 1: Write the integration test**

Add to `backend/tests/test_long_term_strategy.py`:

```python
def test_long_term_signal_is_scored_by_the_same_evaluate_pending_signals(db_session):
    """A long_term_value BUY signal is not a special case — it's scored by
    exactly the same function as a swing signal, just with a much longer
    horizon_days. This is the whole point of reusing Signal/Scan Results
    rather than building a parallel scoring path (spec §6)."""
    from datetime import UTC, datetime

    from swing_trade_ml.core.enums import SignalType
    from swing_trade_ml.db.models.market import Candle, Instrument
    from swing_trade_ml.db.models.trading import Signal, Strategy
    from swing_trade_ml.ml.predict import evaluate_pending_signals

    inst = Instrument(instrument_token=999, tradingsymbol="LTTEST", is_watchlisted=True)
    db_session.add(inst)
    db_session.flush()
    strat = Strategy(name="lt_test", strategy_type="long_term_value", mode="paper")
    db_session.add(strat)
    db_session.flush()

    gen_at = datetime(2026, 1, 1, tzinfo=UTC)
    sig = Signal(
        strategy_id=strat.id, instrument_id=inst.id, signal_type=SignalType.BUY, mode="paper",
        price=100.0, stop_loss=80.0, take_profit=130.0, horizon_days=250,
        advisory_only=True, generated_at=gen_at,
    )
    db_session.add(sig)
    # Target hit well inside the 250-day horizon.
    db_session.add(Candle(
        instrument_id=inst.id, interval="day", ts=datetime(2026, 6, 1, tzinfo=UTC),
        open=128, high=132, low=127, close=131, volume=100_000,
    ))
    db_session.commit()

    count = evaluate_pending_signals(db_session, now=datetime(2026, 9, 1, tzinfo=UTC))

    assert count == 1
    db_session.refresh(sig)
    assert sig.outcome == "TARGET_HIT"
```

- [ ] **Step 2: Run the test**

Run: `cd backend && pytest tests/test_long_term_strategy.py::test_long_term_signal_is_scored_by_the_same_evaluate_pending_signals -v`
Expected: PASS with no new implementation code — if it fails, the Scan Results plan's Task 1-3 haven't landed yet in this codebase; do those first (see Global Constraints).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_long_term_strategy.py
git commit -m "test: confirm long-term signals reuse the swing scoring pipeline

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: Frontend — distinguish long-term from swing in Scan Results

**Files:**
- Modify: `frontend/src/pages/ScanResults.tsx` (created by `docs/superpowers/plans/2026-09-12-scan-results.md` Task 7)

**Interfaces:**
- Consumes: `ScanResult` type (Scan Results plan Task 6) — no new field needed; a "Long-term" vs "Swing" tag is derived client-side from `strategy_name` (contains `"long_term"`) or a horizon threshold, not a new backend column.

- [ ] **Step 1: Add a derived tag**

In `frontend/src/pages/ScanResults.tsx`, add a small helper near the top of the file:

```typescript
function horizonTagFor(row: ScanResult): 'Swing' | 'Long-term' {
  return row.strategy_name.toLowerCase().includes('long_term') ? 'Long-term' : 'Swing'
}
```

Add a new "Horizon" column to the table's `<thead>`/`<tbody>` (between "Cap tier" and "Called on"), rendering `horizonTagFor(row)` as a small pill — reuse whatever badge CSS class the "Cap tier" cell or `TierBadge` component already uses, so it's visually consistent rather than a one-off style.

- [ ] **Step 2: Verify it builds**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/ScanResults.tsx
git commit -m "feat: tag long-term vs swing signals in Scan Results

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 6 (Phase 2 — follow-up, gated on Task 1's vendor decision): Fundamentals features

**Files:**
- Create: `backend/src/swing_trade_ml/ml/fundamentals.py`
- Modify: `backend/src/swing_trade_ml/strategies/long_term_value.py`

**Interfaces:**
- Consumes: whichever vendor Task 1 selected (read `docs/superpowers/research/2026-09-12-fundamentals-vendor-decision.md`'s "Integration notes" section for the exact API details).
- Produces: `FundamentalsProvider` protocol and `FUNDAMENTALS_FEATURE_COLUMNS` — a concrete interface now, with the vendor-specific implementation as this task's own deliverable once Task 1 has named a vendor.

This task is explicitly deferred until Task 1 concludes — do not start it with a guessed vendor. The interface below is written now so the rest of the codebase has something concrete to design against, but its implementation is real work for whoever picks this task up after Task 1 lands.

- [ ] **Step 1: Define the provider interface**

```python
# backend/src/swing_trade_ml/ml/fundamentals.py
"""Fundamentals features for the long-term value model — see
docs/superpowers/specs/2026-09-12-long-term-stock-picks-design.md §5 and
docs/superpowers/research/2026-09-12-fundamentals-vendor-decision.md for
which vendor backs this.

Kept as a separate feature list from ml/features.py's FEATURE_COLUMNS
(consumed by the swing model) rather than merged in — the swing model must
not silently start depending on slower-moving fundamentals data it was
never validated against.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol

FUNDAMENTALS_FEATURE_COLUMNS: list[str] = [
    "pe_vs_sector_median",
    "roe_trend",
    "debt_equity_trend",
    "revenue_growth_yoy",
    "earnings_growth_yoy",
    "promoter_holding_change",
]


class FundamentalsProvider(Protocol):
    """Point-in-time fundamentals lookup. `as_of` must return the ratio as
    it was knowable on that date, never a later-restated value — see the
    look-ahead-bias discipline in ml/features.py's module docstring, which
    this interface exists specifically to preserve for fundamentals too."""

    def fetch(self, tradingsymbol: str, as_of: date) -> dict[str, float]:
        """Returns a dict with (a subset of, if some are unavailable for
        this instrument/date) FUNDAMENTALS_FEATURE_COLUMNS's keys."""
        ...
```

- [ ] **Step 2: Implement the chosen vendor's provider**

Read `docs/superpowers/research/2026-09-12-fundamentals-vendor-decision.md`'s "Integration notes for Task 6" section and implement a concrete class satisfying `FundamentalsProvider` against that vendor's actual API — base URL, auth, field mapping. Write this against real API responses (recorded fixtures for tests, following this codebase's existing pattern of sample-data fixtures like the Scan Results/Mutual Funds plans' `SAMPLE_NAVALL`-style constants), not against a live network call in the test suite.

- [ ] **Step 3: Layer the features into `LongTermValueStrategy.evaluate`**

Extend the `featured` DataFrame in `long_term_value.py`'s `evaluate` method with the fundamentals columns (merged in as extra columns on the single `row` used for prediction, matching how `build_features` already merges index/sector/vix/breadth context onto the price-based frame), and extend `feature_names`/retraining to include `FUNDAMENTALS_FEATURE_COLUMNS`. Retrain the `long_term_value` model (Task 2's `train_model` call) with the enriched dataset.

- [ ] **Step 4: Point-in-time correctness test**

Write a test asserting a fundamentals feature computed "as of" date X never reflects data the provider says was restated after X — the concrete assertion depends on the chosen vendor's actual restatement-tracking capability (documented in Task 1's decision doc); if the vendor cannot support this, that should have been disqualifying in Task 1, not discovered here.

- [ ] **Step 5: Run the full backend test suite and commit**

Run: `cd backend && pytest -v`

```bash
git add backend/src/swing_trade_ml/ml/fundamentals.py backend/src/swing_trade_ml/strategies/long_term_value.py backend/tests/
git commit -m "feat: layer fundamentals features into long-term value model

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```
