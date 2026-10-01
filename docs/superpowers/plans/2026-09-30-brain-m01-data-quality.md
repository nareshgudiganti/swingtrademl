# Brain M01 · Data Gateway and Quality Score Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Score every stock's price data (fresh, complete, believable) so the brain only trusts data it has checked; a stock with bad data can never be a TRADE, and bad market-wide data stops new trades.

**Architecture:** A pure assessor (`assess_bars`) turns a stock's recent bars, the expected bar day and its corporate-action dates into a `DataQuality@1` record with a 0–1 score and plain-English issues. A pure `summarise` builds the overall `"*"` record from the stock records, the benchmark's record and the feed freshness. Module `M01` fetches bars through the dated reader and writes both. The constitution gains one rule: overall data not fresh → NO NEW TRADES.

**Tech Stack:** Python 3.12, pandas, SQLAlchemy 2, pytest; existing `core/holidays.py`, `db/models/feeds.py`.

**Spec:** `docs/superpowers/specs/2026-09-29-trademind-brain-build-book.html` — module sheet M01; section 7.3 (NO NEW TRADES triggers include "overall data quality below floor"); constitution C5.

## Global Constraints

- Daily candles are stamped at IST midnight of their trading day (stored as 18:30 UTC the day before). Every bar date must be taken in IST.
- A day's bar is expected once ingest has run: 15:40 IST on a trading day; before that, the previous trading day's bar is the newest expected.
- Trading days = weekdays that are not in `core.holidays.NSE_HOLIDAYS`.
- Score = 1 − sum of penalties, floored at 0. Quality floor = 0.6. `fresh` = no missing trading days AND score ≥ floor.
- Penalties: 1 day behind 0.5; 2+ days behind 0.8; history < 220 bars 0.3; a gap > 3 trading days in the last 60 bars 0.2; a > 20% one-day move not on a corporate-action date 0.3; zero volume in the last 5 bars 0.2; impossible bar (high < low, or close outside low–high) in the last 20 bars 0.3.
- M01 id `"M01"`, step `perceive`, kind `step`, default mode ON, writes only `DataQuality@1`.
- Every issue is a plain-English sentence (NFR-14).

## Review Focus

1. A bar stamped 18:30 UTC is that IST day's bar (the bug in M00's reader). (Task 1 test)
2. A long weekend or holiday is not counted as missing days. (Task 2 test)
3. A stock split's ex-date shows a -50% move that must not be flagged as a spike. (Task 2 test)
4. A stock with no bars at all → score 0 with "No price data", not an exception. (Task 2 test)
5. Before 15:40 IST today's bar is not yet expected; yesterday's bar is fresh. (Task 2 test)

---

## File Structure

- Modify `backend/src/swing_trade_ml/brain/reader.py` — IST bar dates (`last_close`), plus `recent_bars(symbol, n)`, `action_dates(symbol)`, `feed_latest()`.
- Create `backend/src/swing_trade_ml/brain/modules/m01_quality/__init__.py`, `quality.py` (pure: `expected_bar_day`, `trading_days_between`, `assess_bars`, `summarise`), `module.py` (`DataGateway`), `connectors.py` (the feed list: name → latest-date query; the contract for a new source).
- Modify `backend/src/swing_trade_ml/brain/modules/__init__.py` — import m01.
- Modify `backend/src/swing_trade_ml/brain/constitution.py` — overall-quality rule.
- Tests: `test_brain_m01_quality.py` (pure), `test_brain_m01_module.py` (DB); extend `test_brain_service.py` (IST date), `test_brain_runner.py` (overall-quality rule).

### Task 1: Bar dates in IST

- [ ] Failing test in `test_brain_service.py`: a candle at `2026-09-24 18:30 UTC` is reported by `last_close` as `2026-09-25`.
- [ ] Fix `last_close` to convert `ts` to Asia/Kolkata before `.date()`.
- [ ] Full brain tests pass; commit `Read daily bar dates in IST`.

### Task 2: Pure assessor

**Interfaces (produced):**
- `expected_bar_day(as_of: datetime) -> date`
- `trading_days_between(earlier: date, later: date) -> int` — trading days strictly after `earlier` up to and including `later`.
- `assess_bars(symbol: str, bars: pd.DataFrame, expected_day: date, action_days: set[date], min_bars: int = 220) -> DataQuality` — `bars` columns: `day` (date, ascending), `open, high, low, close, volume`.
- `summarise(stock: list[DataQuality], benchmark: DataQuality | None, feeds_behind: dict[str, int]) -> DataQuality` (symbol `"*"`).

- [ ] Failing tests: fresh clean stock scores 1.0; one day behind → 0.5, not fresh, issue names the date; weekend/holiday not counted; split day not a spike; unexplained 25% jump flagged; zero volume flagged; high < low flagged; short history flagged; no bars → 0; before 15:40 yesterday is expected; summary not fresh when the benchmark is stale or fewer than 80% of stocks are fresh; feeds behind appear as issues but do not by themselves make the market unfresh.
- [ ] Implement `quality.py`; tests pass; commit `Add the data-quality assessor`.

### Task 3: M01 module, overall rule, local check

- [ ] Failing tests: M01 registered; with fresh bars M01 + M07 + a liked stock gives TRADE; stale bars → DATA refusal and WATCH; the `"*"` record exists; overall not fresh → banner NO NEW TRADES with the plain reason; replay uses bars up to `as_of` only.
- [ ] Implement reader methods, `connectors.py`, `module.py`, constitution rule; register M01.
- [ ] Full suite green, lint clean; commit `Add the brain's data gateway and quality score (M01)`.
- [ ] Local check on `brain_m00_check`: expect every stock flagged about 16 trading days old and NO NEW TRADES with "Market data is not reliable today"; then a replay `--as-of 2026-09-07` where data is fresh, to show the brain trusting it.
