# M05 Memory and Experience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** For every idea and holding, recall what happened after similar past stock-days — how often +8% came before −4% within 15 trading days, the return band, the typical days and the day-by-day path — using only outcomes known by the run's date, and prove on unseen months whether that recall predicts anything.

**Architecture:** Pure `cases.py` (bars + dated market labels → one case per stock-day: state key, outcome, the days it became known, the 15-day path), pure `recall.py` (cases + today's key + as_of → `Recall`, widening the key below 30 cases and recording which key was used), a `brain_experience` table rebuilt by `swingtrade brain memory-build` and after live nightly runs, and a REMEMBER step module. M08 already turns a `Recall` with ≥ 30 cases into evidence text and the negative-expected-result rule.

**Tech Stack:** Python 3.12, pandas, numpy, SQLAlchemy 2, Alembic.

**Spec:** `docs/superpowers/specs/2026-09-29-trademind-brain-build-book.html` — module sheet "M05 Memory and experience"; contract `Recall@1` (symbol, query, n_similar, hit_rate, median_return, p25, p75, median_days, typical_path[{day,p25,p50,p75}], examples).

## Global Constraints

- Step module, Wave 4, step 4 Remember. Reads Situation@1, StockState@1, MarketState@1, history via DatedReader. Writes Recall@1 per candidate and holding.
- State key: market label, stock label, trend bucket, volatility bucket. Outcome: +8% before −4% within 15 trading days (same conventions as `ml.features.build_label`: trading bars, a same-bar touch of both is a stop), plus the daily return path.
- Lookup: same state key; if fewer than 30 cases, widen by dropping the least important part (volatility, then market label); record which key was used.
- Return hit rate, median return, 25th–75th percentile band, median days to outcome, and the day-by-day band (for M15).
- Only outcomes fully known by as_of count (no look-ahead).
- If switched off: "No past experience"; M08 shows the model's record instead.
- Backfill command `swingtrade brain memory-build`; table `brain_experience`.
- Why output: "Similar cases: 124 · reached +8% first in 38% · middle half ended between −3% and +5% · median 9 trading days".
- Evidence first: walk-forward check on months the lookup could not see (docs/brain/evidence). Survivorship: the universe is today's watch list — say so.

## Review Focus

1. A case whose outcome resolves after as_of is excluded — Task 2 `test_cases_not_known_by_as_of_are_excluded`.
2. Widening happens below 30 cases and is recorded — Task 2 `test_widening_drops_volatility_then_market_and_says_so`.
3. Same-bar touch of +8% and −4% is a stop — Task 1 `test_a_day_touching_both_barriers_counts_as_a_stop`.
4. A stock's own future must not leak through its own past cases on the same day (the case for "today" is never in the table: its outcome is unknown) — covered by (1).
5. Holdings get a recall too (M15 needs the path) — Task 4 `test_holdings_get_a_recall`.

---

Tasks: (1) cases.py; (2) recall.py; (3) walk-forward evidence script and decision; (4) Recall contract fields, table + migration `3c9a7e1f5b28`, reader, module, M08 wording, CLI, nightly rebuild hook; (5) real check, notes, memory. Each: failing test → code → pass → commit.
