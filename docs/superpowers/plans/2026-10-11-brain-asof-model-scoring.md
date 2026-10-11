# As-of Model Scoring for Brain Replays Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `brain replay-score` score each past day with a model that had not seen that day, so replays produce real brain ideas.

**Architecture:** Train a model with a cutoff date (only rows whose outcome was known by the cutoff). Score any later day from features built from data up to that day. `DatedReader` hands those scores to the brain in replays only, and refuses any day on or before the cutoff. The live scoring path is not touched.

**Tech Stack:** Python 3.12, pandas, LightGBM via `ml/train.py`, SQLAlchemy, pytest. Run tests with `backend/.venv/Scripts/python.exe` and `env -u API_KEY -u DATABASE_URL -u JWT_SECRET_KEY -u TRADING_MODE` (Docker Postgres up).

**Spec:** `docs/superpowers/specs/2026-10-11-brain-asof-model-scoring-design.md`

## Global Constraints

- Local databases and research only. As-of models are registered `TRAINED` and never `ACTIVE`. Never call `activate_model` for them.
- The live path (`predict_instrument`, `predict_watchlist`, nightly runs, `live=True` readers) behaves exactly as before.
- No change to M08 rules, the risk gate, sizing, stops, limits, or `COUNT_BLOCKED_TOWARD_GATE`.
- The threshold used in replays is `settings.ML_MIN_CONFIDENCE`, never `accepted_buy_level` (it is learned from later outcomes).
- A replay day is scored only if it is strictly after the model's cutoff date (IST).
- Daily candles are stamped IST midnight: convert with `.astimezone(IST).date()`.
- Format only files you touched; never `ruff format` a whole package.

## Review Focus

- A window that starts on or before the cutoff: the command refuses with a clear message; `--allow-in-sample` runs it but the report says IN-SAMPLE on its first line.
- A stock with fewer than 220 bars before the day (the live path skips these): no score, never a guess.
- A feature that is NaN on the day (warming up): no score for that stock and day.
- The model file missing on disk: replay continues without scores and the report counts the days with no score.
- A model with no recorded cutoff (a normal, live-trained model): refused for replays unless `--allow-in-sample`.
- Two replays in one process with different models must not share cached scores.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/src/swing_trade_ml/ml/dataset.py` (modify) | `build_training_dataset(..., cutoff=)` drops rows whose label ended after the cutoff. |
| `backend/src/swing_trade_ml/ml/train.py` (modify) | `train_model(..., cutoff=)` passes it through and records it in `metrics["asof_cutoff"]`. |
| `backend/src/swing_trade_ml/ml/asof.py` (new) | `asof_cutoff(model)`, `score_series(...)`, `train_asof_model(...)`, cache. |
| `backend/src/swing_trade_ml/brain/reader.py` (modify) | `DatedReader(asof_model=)`; `model_probability` uses it in replays. |
| `backend/src/swing_trade_ml/brain/fallbacks.py` (modify) | The model opinion no longer skips replays that have an as-of model. |
| `backend/src/swing_trade_ml/brain/service.py`, `replay_week.py` (modify) | Pass `asof_model` through. |
| `backend/src/swing_trade_ml/brain/replay_score.py`, `replay_report.py` (modify) | Model guard, report fields, summary line. |
| `backend/src/swing_trade_ml/cli.py` (modify) | `brain asof-train`, `replay-score --asof-model/--allow-in-sample`. |
| `backend/tests/test_asof_*.py` (new) | Tests per task. |

---

### Task 1: Train with a cutoff

**Files:**
- Modify: `backend/src/swing_trade_ml/ml/dataset.py` (function `build_training_dataset`, add a parameter and a filter before the final `return dataset`)
- Modify: `backend/src/swing_trade_ml/ml/train.py` (function `train_model`)
- Create: `backend/src/swing_trade_ml/ml/asof.py`
- Test: `backend/tests/test_asof_training.py`

**Interfaces:**
- Produces:
  - `build_training_dataset(db, symbols=None, interval="day", horizon_days=15, target_return=0.08, stop_return=0.04, min_rows=300, cutoff: date | None = None) -> pd.DataFrame`
  - `train_model(..., cutoff: date | None = None) -> MLModel`; when `cutoff` is set `metrics["asof_cutoff"] == cutoff.isoformat()`
  - `cutoff_timestamp(cutoff: date) -> pd.Timestamp` (tz-aware, end of that IST day) in `ml/dataset.py`
  - `asof.asof_cutoff(model: MLModel) -> date | None`
  - `asof.train_asof_model(db, cutoff: date, symbols: list[str] | None = None, **kwargs) -> MLModel` (name `swing_classifier_asof_<YYYYMMDD>`, `auto_activate` always False)

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_asof_training.py
from __future__ import annotations

from datetime import date

import pandas as pd

from swing_trade_ml.ml import dataset as ds
from swing_trade_ml.ml.asof import asof_cutoff
from swing_trade_ml.ml.dataset import cutoff_timestamp


def test_cutoff_timestamp_is_the_end_of_that_ist_day():
    ts = cutoff_timestamp(date(2026, 7, 10))
    assert ts.tzinfo is not None
    assert ts == pd.Timestamp("2026-07-10 23:59:00", tz="Asia/Kolkata")


def test_apply_cutoff_drops_rows_whose_label_ended_after_it():
    frame = pd.DataFrame(
        {
            "ts": pd.to_datetime(["2026-07-01", "2026-07-08", "2026-07-09"], utc=True),
            "label_end_ts": pd.to_datetime(["2026-07-09", "2026-07-10", "2026-07-30"], utc=True),
            "target": [1, 0, 1],
        }
    )
    kept = ds.apply_cutoff(frame, date(2026, 7, 10))
    assert list(kept["target"]) == [1, 0]  # the row whose outcome landed on 30 July is gone


def test_apply_cutoff_without_a_cutoff_changes_nothing():
    frame = pd.DataFrame({"ts": pd.to_datetime(["2026-07-01"], utc=True), "label_end_ts": pd.to_datetime(["2030-01-01"], utc=True)})
    assert len(ds.apply_cutoff(frame, None)) == 1


class _Model:
    def __init__(self, metrics):
        self.metrics = metrics


def test_asof_cutoff_reads_the_recorded_date_or_none():
    assert asof_cutoff(_Model({"asof_cutoff": "2026-07-10"})) == date(2026, 7, 10)
    assert asof_cutoff(_Model({})) is None
    assert asof_cutoff(_Model(None)) is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && env -u API_KEY -u DATABASE_URL -u JWT_SECRET_KEY -u TRADING_MODE .venv/Scripts/python.exe -m pytest tests/test_asof_training.py -q -p no:cacheprovider`
Expected: FAIL (`cutoff_timestamp`, `apply_cutoff`, `ml.asof` do not exist).

- [ ] **Step 3: Implement**

In `ml/dataset.py` add near the top-level helpers (after `load_candles`):

```python
from datetime import date, time
from zoneinfo import ZoneInfo

_IST = ZoneInfo("Asia/Kolkata")


def cutoff_timestamp(cutoff: date) -> pd.Timestamp:
    """The end of `cutoff`'s IST day, as a timezone-aware timestamp."""
    return pd.Timestamp(datetime.combine(cutoff, time(23, 59), tzinfo=_IST))


def apply_cutoff(dataset: pd.DataFrame, cutoff: date | None) -> pd.DataFrame:
    """Keep only rows whose label window ended on or before the cutoff, so no
    training row's outcome was still unknown on that day."""
    if cutoff is None or dataset.empty:
        return dataset
    limit = cutoff_timestamp(cutoff)
    ends = pd.to_datetime(dataset["label_end_ts"], utc=True)
    return dataset[ends <= limit].reset_index(drop=True)
```

(Add `from datetime import date, datetime, time` to the existing imports if `datetime` is not already imported there; keep existing imports.)

Change `build_training_dataset`'s signature to add `cutoff: date | None = None` and, just before the `log.info("dataset.built", ...)` call, insert:

```python
    dataset = apply_cutoff(dataset, cutoff)
    if dataset.empty:
        log.warning("dataset.empty_after_cutoff", cutoff=str(cutoff))
        return dataset
```

In `ml/train.py` add `cutoff: date | None = None` to `train_model`'s parameters (import `date` from `datetime`), pass `cutoff=cutoff` to `build_training_dataset(...)`, and after `metrics["embargo_days"] = horizon_days` add:

```python
    if cutoff is not None:
        metrics["asof_cutoff"] = cutoff.isoformat()
```

Create `ml/asof.py`:

```python
"""Models and scores that are safe to use for a past day (brain replays).

A model trained with a cutoff only learned from rows whose outcome was known by that day,
and may only score days strictly after it.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from swing_trade_ml.db.models.ml import MLModel
from swing_trade_ml.ml.train import train_model


def asof_cutoff(model: Any) -> date | None:
    """The cutoff a model was trained with, or None for an ordinary (live) model."""
    raw = (getattr(model, "metrics", None) or {}).get("asof_cutoff")
    return date.fromisoformat(raw) if raw else None


def train_asof_model(db: Session, cutoff: date, symbols: list[str] | None = None, **kwargs) -> MLModel:
    """Train `swing_classifier_asof_<YYYYMMDD>` on data known by `cutoff`. Never activated."""
    kwargs.pop("auto_activate", None)
    return train_model(
        db,
        name=f"swing_classifier_asof_{cutoff:%Y%m%d}",
        symbols=symbols,
        cutoff=cutoff,
        auto_activate=False,
        **kwargs,
    )
```

- [ ] **Step 4: Run to verify they pass**

Run: same command as Step 2. Expected: `4 passed`. Then run `tests/test_walk_forward.py tests/test_correctness_release.py tests/test_real_question_label.py` to confirm training is unchanged without a cutoff (expected: all pass).

- [ ] **Step 5: Lint, format touched files, commit**

```bash
cd backend && .venv/Scripts/python.exe -m ruff format src/swing_trade_ml/ml/asof.py tests/test_asof_training.py && .venv/Scripts/python.exe -m ruff check src/swing_trade_ml/ml/asof.py src/swing_trade_ml/ml/dataset.py src/swing_trade_ml/ml/train.py tests/test_asof_training.py
git add backend/src/swing_trade_ml/ml/asof.py backend/src/swing_trade_ml/ml/dataset.py backend/src/swing_trade_ml/ml/train.py backend/tests/test_asof_training.py
git commit -m "Let a model be trained with a cutoff so no training row's outcome was unknown on that day."
```

(Check `git diff` on `dataset.py` and `train.py` shows only the lines above; do not reformat them.)

---

### Task 2: Score any past day, and prove the features are causal

**Files:**
- Modify: `backend/src/swing_trade_ml/ml/asof.py`
- Test: `backend/tests/test_asof_scoring.py`

**Interfaces:**
- Consumes: `build_features`, `FEATURE_COLUMNS` (`ml/features.py`); `load_candles` (`ml/dataset.py`); `load_index_candles`, `load_sector_candles`, `load_vix_candles`, `load_market_breadth` (`ml/market_context.py`); `get_sector_index` (`ml/sector_map.py`); `_get_bundle` (`ml/predict.py`).
- Produces:
  - `score_series(db, instrument: Instrument, model: MLModel, after: date) -> dict[date, float]` (IST day to probability, only days strictly after `after`, only where features are complete, at least 220 bars of history)
  - `clear_cache() -> None`
  - Module cache keyed `(model.id, instrument.id)`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_asof_scoring.py
"""As-of scoring needs features that only use data up to and including each day."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.ml import market_context
from swing_trade_ml.ml.dataset import load_candles
from swing_trade_ml.ml.features import FEATURE_COLUMNS, build_features
from swing_trade_ml.ml.market_context import (
    load_index_candles,
    load_market_breadth,
    load_sector_candles,
    load_vix_candles,
)
from swing_trade_ml.ml.sector_map import get_sector_index

IST = ZoneInfo("Asia/Kolkata")
LAST = date(2026, 9, 25)


def _ts(day: date) -> datetime:
    return datetime.combine(day, time(0, 0), tzinfo=IST).astimezone(UTC)


def _series(db, symbol, token, start_price, seed, *, watch=True, bars=420):
    inst = Instrument(instrument_token=token, tradingsymbol=symbol, exchange="NSE", is_watchlisted=watch, is_active=True)
    db.add(inst)
    db.flush()
    rng = np.random.default_rng(seed)
    price, day, n = start_price, LAST - timedelta(days=int(bars * 1.5)), 0
    out = []
    while day <= LAST:
        if day.weekday() < 5:
            price *= 1 + rng.normal(0.0005, 0.012)
            out.append((day, price))
            n += 1
        day += timedelta(days=1)
    for d, p in out:
        db.add(Candle(instrument_id=inst.id, interval="day", ts=_ts(d), open=p * 0.998, high=p * 1.01,
                      low=p * 0.99, close=p, volume=int(100000 + rng.integers(0, 50000))))
    db.commit()
    return inst, [d for d, _ in out]


@pytest.fixture()
def market(db_session):
    market_context.clear_cache() if hasattr(market_context, "clear_cache") else None
    inst, days = _series(db_session, "ASOFA", 996001, 100.0, 1)
    _series(db_session, "ASOFB", 996002, 250.0, 2)
    _series(db_session, settings.BENCHMARK_INDEX_SYMBOL, 996099, 20000.0, 3, watch=False)
    return inst, days


def _features(db, inst, upto: pd.Timestamp | None):
    raw = load_candles(db, inst.id, "day")
    if upto is not None:
        raw = raw[raw["ts"] <= upto].reset_index(drop=True)
    return build_features(
        raw,
        load_index_candles(db, "day", upto),
        load_sector_candles(db, get_sector_index(inst.tradingsymbol), "day", upto),
        load_vix_candles(db, "day", upto),
        load_market_breadth(db, "day", upto),
    )


def test_features_for_a_day_do_not_depend_on_later_data(db_session, market):
    """The row for day D built from everything must equal the row built from data cut at D."""
    inst, days = market
    full = _features(db_session, inst, None)
    for d in (days[-40], days[-25], days[-10]):
        cut_ts = pd.Timestamp(_ts(d))
        cut = _features(db_session, inst, cut_ts)
        a = full[full["ts"] == cut_ts][FEATURE_COLUMNS].to_numpy(dtype=float)
        b = cut.iloc[[-1]][FEATURE_COLUMNS].to_numpy(dtype=float)
        assert a.shape == b.shape == (1, len(FEATURE_COLUMNS))
        assert np.allclose(a, b, equal_nan=True), f"features for {d} changed when later bars were added"
```

(Further tests for `score_series` are added in Step 3b below once it exists.)

- [ ] **Step 2: Run to verify the causality test**

Run: `... pytest tests/test_asof_scoring.py -q -p no:cacheprovider`
Expected: this first test either PASSES (features are causal: good, continue) or FAILS. **If it fails, stop the whole plan and report which feature column differs**: as-of scoring cannot be trusted until that feature is fixed or excluded, and that is the owner's call. (If `market_context` has no `clear_cache`, remove that line; check with `grep -n "def clear" backend/src/swing_trade_ml/ml/market_context.py`.)

- [ ] **Step 3: Implement `score_series`**

Append to `ml/asof.py`:

```python
import numpy as np
import pandas as pd
from zoneinfo import ZoneInfo

from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.ml.dataset import load_candles
from swing_trade_ml.ml.features import build_features
from swing_trade_ml.ml.market_context import (
    load_index_candles,
    load_market_breadth,
    load_sector_candles,
    load_vix_candles,
)
from swing_trade_ml.ml.predict import _get_bundle
from swing_trade_ml.ml.sector_map import get_sector_index

_IST = ZoneInfo("Asia/Kolkata")
MIN_BARS = 220  # the live path needs the same warm-up
_cache: dict[tuple[int, int], dict[date, float]] = {}


def clear_cache() -> None:
    _cache.clear()


def score_series(db: Session, instrument: Instrument, model: MLModel, after: date) -> dict[date, float]:
    """Probability for every IST day strictly after `after` where the stock has at least
    MIN_BARS of history and a complete feature row. Features are built once from the full
    history; this is the same as cutting the data at each day only because the features
    are causal (tests/test_asof_scoring.py proves it)."""
    key = (model.id, instrument.id)
    if key not in _cache:
        _cache[key] = _score_all(db, instrument, model)
    return {d: p for d, p in _cache[key].items() if d > after}


def _score_all(db: Session, instrument: Instrument, model: MLModel) -> dict[date, float]:
    raw = load_candles(db, instrument.id, "day")
    if len(raw) < MIN_BARS:
        return {}
    bundle = _get_bundle(model)
    names: list[str] = bundle["feature_names"]
    featured = build_features(
        raw,
        load_index_candles(db, "day"),
        load_sector_candles(db, get_sector_index(instrument.tradingsymbol), "day"),
        load_vix_candles(db, "day"),
        load_market_breadth(db, "day"),
    )
    featured = featured.iloc[MIN_BARS - 1 :]
    x = featured[names]
    ok = ~x.isna().any(axis=1)
    if not ok.any():
        return {}
    scaled = bundle["scaler"].transform(x[ok].to_numpy(dtype=np.float64))
    est = bundle["estimator"]
    probs = est.predict_proba(scaled)[:, 1] if hasattr(est, "predict_proba") else est.predict(scaled)
    days = [pd.Timestamp(t).tz_convert(_IST).date() for t in featured.loc[ok, "ts"]]
    return {d: float(p) for d, p in zip(days, probs, strict=True)}
```

(Move the new imports to the top of the file with the others; keep the file import-sorted for ruff.)

- [ ] **Step 3b: Add `score_series` tests** to `tests/test_asof_scoring.py`:

```python
class _FakeEstimator:
    def predict_proba(self, x):
        p = np.clip(0.5 + x[:, 0] * 0.0, 0, 1)  # constant 0.5, shape-checked
        return np.column_stack([1 - p, p])


class _FakeScaler:
    def transform(self, x):
        return x


def _fake_model(monkeypatch, model_id=991):
    from swing_trade_ml.ml import asof

    class M:
        id = model_id
        name = "m"
        version = "1"
        metrics = {"asof_cutoff": "2026-01-01"}

    monkeypatch.setattr(asof, "_get_bundle", lambda m: {
        "feature_names": FEATURE_COLUMNS, "scaler": _FakeScaler(), "estimator": _FakeEstimator()})
    asof.clear_cache()
    return M()


def test_score_series_gives_one_score_per_day_after_the_cutoff_only(db_session, market, monkeypatch):
    from swing_trade_ml.ml.asof import score_series

    inst, days = market
    scores = score_series(db_session, inst, _fake_model(monkeypatch), after=days[-6])
    assert set(scores) <= set(days[-5:]) and days[-1] in scores
    assert all(d > days[-6] for d in scores) and all(0.0 <= p <= 1.0 for p in scores.values())


def test_a_stock_with_too_little_history_gets_no_score(db_session, monkeypatch):
    from swing_trade_ml.ml.asof import score_series

    inst, _ = _series(db_session, "ASOFSHORT", 996003, 50.0, 4, bars=120)
    assert score_series(db_session, inst, _fake_model(monkeypatch, 992), after=date(2026, 1, 1)) == {}


def test_scores_are_cached_per_model_and_stock(db_session, market, monkeypatch):
    from swing_trade_ml.ml import asof

    inst, days = market
    model = _fake_model(monkeypatch)
    asof.score_series(db_session, inst, model, after=days[-6])
    monkeypatch.setattr(asof, "load_candles", lambda *a, **k: (_ for _ in ()).throw(AssertionError("recomputed")))
    assert asof.score_series(db_session, inst, model, after=days[-6])  # served from the cache
    other = _fake_model(monkeypatch, 993)
    with pytest.raises(AssertionError):
        asof.score_series(db_session, inst, other, after=days[-6])  # a different model never shares it
```

- [ ] **Step 4: Run all tests in the file**

Run: `... pytest tests/test_asof_scoring.py -q -p no:cacheprovider`
Expected: all pass. If the causality test failed in Step 2, do not continue.

- [ ] **Step 5: Lint, format, commit**

```bash
cd backend && .venv/Scripts/python.exe -m ruff format src/swing_trade_ml/ml/asof.py tests/test_asof_scoring.py && .venv/Scripts/python.exe -m ruff check src/swing_trade_ml/ml/asof.py tests/test_asof_scoring.py
git add backend/src/swing_trade_ml/ml/asof.py backend/tests/test_asof_scoring.py
git commit -m "Score any past day from features that only use data up to it, with a causality test."
```

---

### Task 3: The reader hands the brain as-of scores in replays

**Files:**
- Modify: `backend/src/swing_trade_ml/brain/reader.py` (`DatedReader.__init__`, `model_probability`)
- Modify: `backend/src/swing_trade_ml/brain/fallbacks.py:85-90`
- Modify: `backend/src/swing_trade_ml/brain/service.py:86-108` (`run_brain`)
- Modify: `backend/src/swing_trade_ml/brain/replay_week.py` (`run_replay_week`)
- Test: `backend/tests/test_asof_reader.py`

**Interfaces:**
- Consumes: `asof.score_series`, `asof.asof_cutoff` (Task 2 and Task 1).
- Produces:
  - `DatedReader(db, as_of, live, asof_model: MLModel | None = None)`
  - `DatedReader.model_probability(symbol) -> tuple[float, float, str] | None` (replay path: only when `live` is False, `asof_model` is set, its cutoff exists and the run's IST day is strictly after it)
  - `service.run_brain(..., asof_model=None)`, `run_replay_week(..., asof_model=None)`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_asof_reader.py
from __future__ import annotations

from datetime import UTC, date, datetime, time
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from swing_trade_ml.brain.reader import DatedReader
from swing_trade_ml.core.config import settings
from swing_trade_ml.ml import asof

IST = ZoneInfo("Asia/Kolkata")


def _as_of(day: date) -> datetime:
    return datetime.combine(day, time(23, 59), tzinfo=IST).astimezone(UTC)


class _Instr:
    id = 1
    tradingsymbol = "AAA"


def _reader(db, day, model, live=False):
    r = DatedReader(db, _as_of(day), live=live, asof_model=model)
    r._instrument = lambda symbol: _Instr()  # noqa: SLF001 - the lookup is not under test
    return r


def _model(cutoff="2026-07-10"):
    return SimpleNamespace(id=1, name="swing_classifier_asof_20260710", version="1", metrics={"asof_cutoff": cutoff})


def test_after_the_cutoff_a_replay_gets_the_score_and_the_plain_threshold(db_session, monkeypatch):
    monkeypatch.setattr(asof, "score_series", lambda db, inst, model, after: {date(2026, 7, 14): 0.71})
    got = _reader(db_session, date(2026, 7, 14), _model()).model_probability("AAA")
    assert got == (0.71, settings.ML_MIN_CONFIDENCE, "swing_classifier_asof_20260710 1")


def test_on_or_before_the_cutoff_there_is_no_score(db_session, monkeypatch):
    monkeypatch.setattr(asof, "score_series", lambda *a, **k: {date(2026, 7, 10): 0.9})
    for day in (date(2026, 7, 10), date(2026, 7, 1)):
        assert _reader(db_session, day, _model()).model_probability("AAA") is None


def test_a_model_without_a_recorded_cutoff_is_never_used_in_a_replay(db_session, monkeypatch):
    monkeypatch.setattr(asof, "score_series", lambda *a, **k: {date(2026, 7, 14): 0.9})
    plain = SimpleNamespace(id=2, name="swing_classifier", version="3", metrics={})
    assert _reader(db_session, date(2026, 7, 14), plain).model_probability("AAA") is None


def test_no_model_given_means_no_score_as_before(db_session):
    assert _reader(db_session, date(2026, 7, 14), None).model_probability("AAA") is None


def test_a_day_with_no_score_is_none_not_a_guess(db_session, monkeypatch):
    monkeypatch.setattr(asof, "score_series", lambda *a, **k: {})
    assert _reader(db_session, date(2026, 7, 14), _model()).model_probability("AAA") is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `... pytest tests/test_asof_reader.py -q -p no:cacheprovider`
Expected: FAIL (`DatedReader` takes no `asof_model`).

- [ ] **Step 3: Implement**

`brain/reader.py`: change `__init__` to `def __init__(self, db: Session, as_of: datetime, live: bool, asof_model=None) -> None:` and add `self.asof_model = asof_model`. Replace the first lines of `model_probability` so it reads:

```python
    def model_probability(self, symbol: str) -> tuple[float, float, str] | None:
        """The active model's score for the latest bar, or None. Live only: the model
        always scores the newest bars. A replay may instead carry an as-of model
        (trained with a cutoff), which scores a day strictly after its cutoff."""
        if not self.live:
            return self._asof_probability(symbol)
```

(keep the rest of the live body unchanged) and add the method:

```python
    def _asof_probability(self, symbol: str) -> tuple[float, float, str] | None:
        from swing_trade_ml.ml import asof

        model = self.asof_model
        cutoff = asof.asof_cutoff(model) if model is not None else None
        if model is None or cutoff is None:
            return None
        day = self.as_of.astimezone(ZoneInfo("Asia/Kolkata")).date()
        if day <= cutoff:
            return None
        instrument = self._instrument(symbol)
        if instrument is None:
            return None
        try:
            score = asof.score_series(self.db, instrument, model, after=cutoff).get(day)
        except OSError as exc:  # the model file is unreachable: no score, never a failed run
            log.warning("brain.reader.asof_model_unavailable", model=model.name, error=str(exc))
            return None
        if score is None:
            return None
        return score, settings.ML_MIN_CONFIDENCE, f"{model.name} {model.version}"
```

(Check `ZoneInfo` is already imported in `reader.py`; add it if not.)

`brain/fallbacks.py`: replace

```python
    if not ctx.request.live:
        return c.Contribution()
```

with

```python
    if not ctx.request.live and getattr(ctx.reader, "asof_model", None) is None:
        return c.Contribution()
```

and update the docstring to say "Replays skip it unless they carry an as-of model."

`brain/service.py` `run_brain`: add `asof_model=None` to the keyword parameters and change the reader line to `reader = DatedReader(db, as_of=as_of, live=live, asof_model=asof_model)`.

`brain/replay_week.py` `run_replay_week`: add `asof_model=None` to the parameters and change the call to `service.run_brain(db, kind=kind, as_of=as_of, symbols=symbols, book=book, asof_model=asof_model)`.

- [ ] **Step 4: Run to verify**

Run: `... pytest tests/test_asof_reader.py tests/test_brain_replay_week.py tests/test_brain_golden_day.py tests/test_brain_no_lookahead.py tests/test_brain_runner.py tests/test_brain_service.py -q -p no:cacheprovider`
Expected: all pass (the golden-day fingerprint must be unchanged: no as-of model means nothing changes).

- [ ] **Step 5: Add one more no-look-ahead test**, extending `tests/test_brain_no_lookahead.py`: in a test with a fake as-of model whose `score_series` is real but whose bundle is the `_FakeEstimator` from Task 2, add the wild future bars and assert the as-of score for DAY is unchanged. Copy the `_FakeEstimator`/`_FakeScaler` helpers from `test_asof_scoring.py` into this file (do not import across test files). Expected: pass.

- [ ] **Step 6: Lint, format touched test files only, commit**

```bash
cd backend && .venv/Scripts/python.exe -m ruff format tests/test_asof_reader.py && .venv/Scripts/python.exe -m ruff check src/swing_trade_ml/brain/reader.py src/swing_trade_ml/brain/fallbacks.py src/swing_trade_ml/brain/service.py src/swing_trade_ml/brain/replay_week.py tests/test_asof_reader.py
git add backend/src/swing_trade_ml/brain/reader.py backend/src/swing_trade_ml/brain/fallbacks.py backend/src/swing_trade_ml/brain/service.py backend/src/swing_trade_ml/brain/replay_week.py backend/tests/test_asof_reader.py backend/tests/test_brain_no_lookahead.py
git commit -m "Let a replay carry an as-of model: scores only for days after its cutoff, plain buy level."
```

---

### Task 4: Guard, report and CLI

**Files:**
- Modify: `backend/src/swing_trade_ml/brain/replay_score.py` (`run_replay_score`)
- Modify: `backend/src/swing_trade_ml/brain/replay_report.py` (`plain_summary`)
- Modify: `backend/src/swing_trade_ml/cli.py` (`brain asof-train`, `replay-score` flags)
- Test: `backend/tests/test_asof_replay_score.py`

**Interfaces:**
- Produces:
  - `class ReplayWindowError(ValueError)` in `replay_score.py`
  - `run_replay_score(..., asof_model=None, allow_in_sample=False)`; raises `ReplayWindowError` if `asof_model` is set and `start <= cutoff` and not `allow_in_sample`, or if `asof_model` has no cutoff and not `allow_in_sample`
  - `report["model"] = {"name", "version", "cutoff", "in_sample": bool, "days_scored": int, "days_without_score": int} | None`
  - CLI: `swingtrade brain asof-train --cutoff D [--symbols A,B]`; `replay-score --asof-model NAME [--allow-in-sample]`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_asof_replay_score.py
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from swing_trade_ml.brain.replay_report import LIMITATIONS, plain_summary, track_stats
from swing_trade_ml.brain.replay_score import ReplayWindowError, run_replay_score

MODEL = SimpleNamespace(id=1, name="swing_classifier_asof_20260710", version="1", metrics={"asof_cutoff": "2026-07-10"})


def _stub(db, **kw):
    return []


def test_a_window_inside_the_training_period_is_refused(db_session):
    with pytest.raises(ReplayWindowError, match="2026-07-10"):
        run_replay_score(db_session, start=date(2026, 7, 8), end=date(2026, 7, 20), replay=_stub, asof_model=MODEL)


def test_the_first_day_after_the_cutoff_is_allowed(db_session):
    report = run_replay_score(
        db_session, start=date(2026, 7, 11), end=date(2026, 7, 11), replay=_stub, asof_model=MODEL, draws=5
    )
    assert report["model"]["cutoff"] == "2026-07-10" and report["model"]["in_sample"] is False


def test_in_sample_is_allowed_only_when_asked_and_is_labelled(db_session):
    report = run_replay_score(
        db_session, start=date(2026, 7, 8), end=date(2026, 7, 9), replay=_stub, asof_model=MODEL,
        allow_in_sample=True, draws=5,
    )
    assert report["model"]["in_sample"] is True
    assert plain_summary(report).splitlines()[0].startswith("IN-SAMPLE")


def test_a_model_without_a_cutoff_is_refused_for_replays(db_session):
    plain = SimpleNamespace(id=2, name="swing_classifier", version="3", metrics={})
    with pytest.raises(ReplayWindowError, match="cutoff"):
        run_replay_score(db_session, start=date(2026, 7, 11), end=date(2026, 7, 11), replay=_stub, asof_model=plain)


def test_the_summary_names_the_model_and_its_training_window():
    report = {
        "window": {"from": "2026-07-13", "to": "2026-08-14", "days_replayed": 25, "failed_days": []},
        "model": {"name": "swing_classifier_asof_20260710", "version": "1", "cutoff": "2026-07-10",
                  "in_sample": False, "days_scored": 24, "days_without_score": 1},
        "track_a": track_stats([]), "track_b": track_stats([]), "baselines": {}, "limitations": list(LIMITATIONS),
    }
    text = plain_summary(report)
    assert "swing_classifier_asof_20260710" in text and "2026-07-10" in text and "1 day" in text


def test_no_model_given_keeps_the_report_as_before(db_session):
    report = run_replay_score(db_session, start=date(2026, 7, 11), end=date(2026, 7, 11), replay=_stub, draws=5)
    assert report["model"] is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `... pytest tests/test_asof_replay_score.py -q -p no:cacheprovider`
Expected: FAIL (`ReplayWindowError` does not exist).

- [ ] **Step 3: Implement**

`replay_score.py`: add

```python
from swing_trade_ml.ml.asof import asof_cutoff


class ReplayWindowError(ValueError):
    """The requested replay would score days the model had already learned from."""
```

Add `asof_model=None, allow_in_sample: bool = False` to `run_replay_score`. At the top of the function, before calling `replay`:

```python
    model_info = None
    if asof_model is not None:
        cutoff = asof_cutoff(asof_model)
        in_sample = False
        if cutoff is None:
            if not allow_in_sample:
                raise ReplayWindowError(
                    f"{asof_model.name} has no cutoff date, so it has seen recent days. "
                    "Train one with `brain asof-train --cutoff D`, or pass --allow-in-sample."
                )
            in_sample = True
        elif start <= cutoff:
            if not allow_in_sample:
                raise ReplayWindowError(
                    f"The window starts {start.isoformat()} but {asof_model.name} was trained on data "
                    f"up to {cutoff.isoformat()}. Start after {cutoff.isoformat()}, or pass --allow-in-sample."
                )
            in_sample = True
        model_info = {
            "name": asof_model.name,
            "version": asof_model.version,
            "cutoff": cutoff.isoformat() if cutoff else None,
            "in_sample": in_sample,
        }
```

Call the replay with the model only when given (so existing stubs keep working):

```python
    extra = {} if asof_model is None else {"asof_model": asof_model}
    results = list(replay(db, start=start, end=end, book=book, symbols=symbols, **extra))
```

After `collect_ideas` runs, count days with and without a score: a day counts as scored if any decision of that run has `confidence is not None`. Add to the loop that builds `per_day`/`pool`:

```python
    scored_days = 0
    for r in results:
        rows, judged = collect_ideas(db, r.run_id, r.day)
        per_day[r.day] = rows
        pool[r.day] = judged
        if any(d.confidence is not None for d in service.decisions_for(db, r.run_id)):
            scored_days += 1
```

and in the returned report add `"model": None if model_info is None else {**model_info, "days_scored": scored_days, "days_without_score": len(results) - scored_days}`.

`replay_report.py` `plain_summary`: build `lines` so that, when `report.get("model")` is set, the first line is `IN-SAMPLE: ...` if `in_sample`, and a model line follows the window line:

```python
    m = report.get("model")
    if m:
        if m["in_sample"]:
            lines.insert(0, "IN-SAMPLE: the model had already seen some of these days, so the numbers are flattering and not evidence.")
        gap = m["days_without_score"]
        lines.append(
            f"Scored by {m['name']} {m['version']}, trained on data up to {m['cutoff'] or 'an unknown date'}."
            + (f" {gap} day{'s' if gap != 1 else ''} had no score." if gap else "")
        )
```

(Place this immediately after the first `lines = [...]` is built, before the track lines.)

`cli.py`: add parser entries — under the `replay-score` parser:

```python
    b.add_argument("--asof-model", default=None, help="Name of a model trained with `brain asof-train`")
    b.add_argument("--allow-in-sample", action="store_true", help="Allow days the model trained on (labelled IN-SAMPLE)")
```

and a new subcommand:

```python
    b = brain_sub.add_parser("asof-train", help="Train a research model on data known by a cutoff day (never activated)")
    b.add_argument("--cutoff", required=True, help="YYYY-MM-DD: the last day whose outcome may be used")
    b.add_argument("--symbols", default=None, help="Comma-separated (default: the watchlist)")
```

Handlers in `cmd_brain`: for `asof-train` call `train_asof_model(db, date.fromisoformat(args.cutoff), symbols)` and print name, version, `n_samples`, `roc_auc`; for `replay-score` look up the model with `select(MLModel).where(MLModel.name == args.asof_model).order_by(MLModel.id.desc()).limit(1)` (exit 1 with a clear message if missing), pass `asof_model=model, allow_in_sample=args.allow_in_sample` to `run_replay_score`, and catch `ReplayWindowError` printing `❌ {exc}` to stderr and returning 1.

- [ ] **Step 4: Run to verify**

Run: `... pytest tests/test_asof_replay_score.py tests/test_brain_replay_score.py tests/test_brain_replay_score_cli.py tests/test_brain_replay_report.py -q -p no:cacheprovider`
Expected: all pass.

- [ ] **Step 5: Lint, format touched test file, commit**

```bash
cd backend && .venv/Scripts/python.exe -m ruff format tests/test_asof_replay_score.py && .venv/Scripts/python.exe -m ruff check src/swing_trade_ml/brain/replay_score.py src/swing_trade_ml/brain/replay_report.py src/swing_trade_ml/cli.py tests/test_asof_replay_score.py
git add backend/src/swing_trade_ml/brain/replay_score.py backend/src/swing_trade_ml/brain/replay_report.py backend/src/swing_trade_ml/cli.py backend/tests/test_asof_replay_score.py
git commit -m "Guard replays against days the model trained on, name the model in the report, add asof-train."
```

---

### Task 5: The real run, and an honest reading

**Files:**
- Create (output): `docs/brain/evidence/asof_replay_<from>_<to>.json` and `.md`

- [ ] **Step 1: Train.** `swingtrade brain asof-train --cutoff 2026-07-10` on the local database. Record the time taken, `n_samples` and ROC AUC in the `.md`. If it takes more than 30 minutes, retrain with `--symbols` (about 60 liquid stocks) and say so.
- [ ] **Step 2: Time a small replay first.** `swingtrade brain replay-score --from 2026-07-13 --to 2026-07-15 --asof-model swing_classifier_asof_20260710 --symbols INFY,TCS,RELIANCE,HDFCBANK,ICICIBANK,SBIN,ITC,LT,AXISBANK,MARUTI --draws 20`. Expected: some days report scores; at least one TRADE or blocked idea across the three days is likely but not guaranteed. If there are none, check the model's buy level: scores may all sit under 60%, which is a real result, not a bug. Note the seconds per day.
- [ ] **Step 3: Run the window** `--from 2026-07-13 --to 2026-08-14` with the watchlist or a symbol subset sized to the measured speed.
- [ ] **Step 4: Read it with the owner.** Compare Track A against the random and all-stocks baselines. Record plainly what it does and does not show: one month, one model, survivor-biased watchlist.
- [ ] **Step 5: Commit the evidence** with a message stating the window and the result in one line.

---

## Self-Review

1. **Spec coverage:** cutoff training (Task 1), score any day with a causality proof (Task 2), reader and fallback wiring with plain buy level (Task 3), refusal of in-sample windows, `--allow-in-sample` label, report fields, CLI (Task 4), the first real run (Task 5). The spec's open risks (M05/M09 leakage, speed, training time) are Task 5 measurements and the Global Constraints.
2. **Placeholders:** none. Task 2 Step 2 names a decision point (stop if features are not causal) instead of a placeholder.
3. **Type consistency:** `asof_cutoff`, `score_series(db, instrument, model, after)`, `cutoff_timestamp`, `apply_cutoff`, `train_asof_model`, `DatedReader(asof_model=)`, `run_replay_score(asof_model=, allow_in_sample=)` and the `report["model"]` keys are the same in every task.
4. **Review Focus:** window before the cutoff (Task 4 tests 1-3), short history (Task 2), NaN features (`_score_all` drops incomplete rows, Task 2), missing model file (Task 3 `OSError` branch), model without a cutoff (Task 3 test 3 and Task 4 test 4), cache isolation between models (Task 2 test 3).
