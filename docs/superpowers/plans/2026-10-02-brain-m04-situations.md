# M04 Situation Recognition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Name what the market is doing (up-trend, sideways, correction, bear phase, crash, recovery, or never seen before), suggest going careful when it is a crash, bear phase or unknown, label each stock, and keep a history of market episodes for the memory module.

**Architecture:** Pure `rules.py` (dated NIFTY + VIX closes → label per day, with evidence), pure `novelty.py` (standardised market-state vectors → nearest-neighbour distance vs the 99th percentile of history), pure `episodes.py` (labels per day → episodes, a new label must hold 3 days except a crash). A RECOGNISE **step** module writes the market `Situation` and one per stock. A shared `brain/market_mode.py::effective_mode` turns a defensive suggestion into DEFENSIVE (never bolder) and is used by M07, M08 and the constitution. New table `brain_episodes`; live nightly runs sync it; `swingtrade brain episodes-backfill` fills the last 5 years.

**Tech Stack:** Python 3.12, pandas, numpy, SQLAlchemy 2, Alembic.

**Spec:** `docs/superpowers/specs/2026-09-29-trademind-brain-build-book.html` — module sheet "M04 Situation recognition"; contract `Situation@1`; table `brain_episodes` (id · scope · label · start end · state_key · stats).

## Global Constraints

- Step module, Wave 3, step 3 Recognise. Reads MarketState@1, StockState@1, Snapshot@1. Writes Situation@1 for the market and each stock.
- Market labels: up-trend, sideways, correction (NIFTY −5% to −10% from its high), bear phase (below −10% and below the 200-day), crash (−4% in a day or VIX jump > 30%), recovery.
- Stock labels from the snapshot: pullback in up-trend, breakout, base, breakdown, extended. (M12 already labels setups with tested rules; M04 labels each stock's trend and "extended" so every stock has one label.)
- Unknown: nearest-neighbour distance of today's standardised market state beyond the 99th percentile of historical distances → is_unknown.
- Suggest defensive when crash, bear phase or unknown; M10 or the constitution turns the suggestion into a mode.
- Market episodes: open/close a `brain_episodes` row when the market label changes. One-off backfill labels the last 5 years.
- If switched off: situation "unlabelled", confidence 0, no defensive suggestion (the recognise fallback).
- Evidence first: measure the +8%-before-−4% hit rate under each label on history before claiming anything (docs/brain/evidence).

## Review Focus

1. Local NIFTY history starts Aug 2021 — the spec's 23 Mar 2020 replay cannot run on real data; a synthetic crash fixture stands in — Task 1 `test_a_march_2020_style_fall_reads_crash_then_bear_then_recovery`.
2. Label flicker at a −5% boundary must not create dozens of one-day episodes — Task 3 `test_a_label_must_hold_three_days_except_a_crash`.
3. Too little history (< 250 days) → no unknown verdict, not a false alarm — Task 2 `test_short_history_is_never_unknown`.
4. Replays and why-runs must not write episodes — Task 5 `test_only_live_nightly_runs_sync_episodes`.
5. A defensive suggestion can never make a mode bolder (NO NEW TRADES stays) — Task 4 `test_effective_mode_never_gets_bolder`.

---

Tasks: (1) rules.py; (2) novelty.py; (3) episodes.py; (4) market_mode.effective_mode + M07/M08/constitution wiring; (5) reader dated closes, module, migration `8d3f6a2b9e47` (`brain_episodes`), service sync, CLI backfill; (6) evidence by label, real check, notes, memory. Each: failing test → code → pass → commit.
