# Brain M02 · Perception Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Each nightly run, turn every stock's prices into the same 53 features the model uses, plus a few convenience facts (close, ATR, average traded value), and keep a dated copy so any past day can be replayed exactly.

**Architecture:** A pure `snapshot_from(symbol, bars, frames, version)` wraps v1's `ml.features.latest_feature_row` and returns a `Snapshot@1` (or None when indicators have not warmed up, leaving the step's price-only fallback to answer). Module `M02` reads bars and market-context frames through the dated reader, so nothing after `as_of` is ever seen. The service stores nightly snapshots in a new `feature_snapshots` table (one row per stock, bar day and feature-set version; a re-run replaces it). Intraday runs skip M02: a tenth of the time budget is not enough for features, and the price-only fallback answers.

**Tech Stack:** Python 3.12, pandas, SQLAlchemy 2, Alembic, pytest; existing `ml/features.py`, `ml/market_context.py`, `ml/sector_map.py`.

**Spec:** `docs/superpowers/specs/2026-09-29-trademind-brain-build-book.html` — module sheet M02; principle P8 (only data known at the time); NFR-06 (reproducibility), NFR-07 (no look-ahead).

## Global Constraints

- Features are exactly `ml.features.FEATURE_COLUMNS` computed by `build_features`; M02 never defines its own indicators.
- `feature_set_version` = first 12 hex chars of SHA-1 over the comma-joined `FEATURE_COLUMNS`.
- Every input frame is bounded to `ts <= as_of` (stock bars via the dated reader; context frames via the loaders' `upto`).
- Convenience fields from the same bounded bars: `close` (last), `atr_14` (last of `features.atr(..., 14)`), `adv_inr_20` (mean of close × volume over the last 20 bars).
- M02 id `"M02"`, step `perceive`, kind `step`, default mode ON, writes only `Snapshot@1`; `run()` has no side effects (storage is the service's job).
- `feature_snapshots` is a plain table (about 50 rows a day); TimescaleDB is not needed at this size.

## Review Focus

1. A replay of an earlier date must not use bars after it, even though newer bars exist. (Task 2 test)
2. A stock with too little history returns no feature snapshot, and the price-only fallback still gives it a price. (Task 1 + Task 2 tests)
3. Running the same night twice replaces that night's snapshot instead of duplicating it. (Task 3 test)
4. The market-context caches are module-level and would serve yesterday's frames to a long-running worker; M02 clears them at the start of its run. (Task 2 test)
5. Intraday runs do not spend their 1-second budget on features. (Task 2 test)

---

### Task 1: Pure snapshot builder

**Files:** create `brain/modules/m02_perception/__init__.py`, `snapshot.py`; test `tests/test_brain_m02_snapshot.py`.

**Interfaces (produced):**
- `@dataclass ContextFrames(index: DataFrame, sector: DataFrame, vix: DataFrame, breadth: DataFrame)`
- `feature_set_version() -> str`
- `snapshot_from(symbol: str, bars: DataFrame, frames: ContextFrames, version: str) -> Snapshot | None` — `bars` columns `ts, open, high, low, close, volume`, ascending.

- [ ] Failing tests: full features on a 400-bar synthetic market; close/ATR/ADV values; version stable and 12 chars; too few bars → None.
- [ ] Implement; pass; commit.

### Task 2: M02 module through the dated reader

**Files:** create `m02_perception/module.py`; modify `brain/reader.py` (`ohlcv`, `context_frames`), `brain/modules/__init__.py`; test `tests/test_brain_m02_module.py`.

- [ ] Failing tests: registered; nightly run gives a feature snapshot whose `as_of` is the last bar day; replay of an earlier date stops at that date; intraday writes nothing and the fallback snapshot exists; the context cache is cleared.
- [ ] Implement; pass; commit.

### Task 3: Store nightly snapshots

**Files:** `db/models/brain.py` (`FeatureSnapshot`), migration `20261001_0900_feature_snapshots.py`, `brain/service.py`; test in `tests/test_brain_m02_module.py`.

- [ ] Failing tests: a nightly run stores one row per stock with features; running again replaces, not duplicates; `why` runs do not store.
- [ ] Implement; migration up/down/up on a scratch DB and the check DB; full suite; lint; commit.
- [ ] Local check on `brain_m00_check`: replay `--as-of 2026-09-07`, then count stored rows and show one stock's snapshot.
