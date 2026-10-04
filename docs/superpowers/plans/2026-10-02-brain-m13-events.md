# M13 News and Events Brain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the brain away from new trades just before results and price-resetting corporate actions, mark exchange-restricted stocks, and put plain event lines ("Results on 14 Oct") on cards — from data we already store, never scraped.

**Architecture:** A pure `calendar.py` turns stored rows (results dates, corporate-action ex-dates, ASM/GSM rows) into stock `Situation`s, `StockState.restrictions` and `event` modifier opinions (card lines). M08 already has the rules that act on them (`event_window`, `exchange_watch_list`); M13 only supplies facts. A plug-in on the RECOGNISE step. The context merge for `StockState` becomes gap-filling (as the spec's merge rule says), so M13's restrictions land in M03's record.

**Tech Stack:** Python 3.12, SQLAlchemy 2, pytest.

**Spec:** `docs/superpowers/specs/2026-09-29-trademind-brain-build-book.html` — module sheet "M13 News and events brain".

## Global Constraints

- Plug-in, Wave 3, step 3 Recognise (+ risk windows). Reads events, corporate actions and ASM/GSM tables. Writes stock Situation@1 (events), StockState@1.restrictions, negative Opinion@1 near events.
- Results within the next 5 trading days → situation "results soon"; M08 makes it AVOID for new ideas and adds a note to holdings.
- Ex-date and split handling: never treat an ex-date drop as a breakdown.
- Restrictions: ASM/GSM membership → AVOID with the list name.
- Fresh filings listed as context, never as a buy reason by themselves. (No filings table exists yet → out of scope; noted.)
- Card line: "Results on 14 Oct". Expected why: "Results on <date>: the brain avoids new trades 5 trading days before results".
- If switched off: only v1's avoid list protects around events (M07 still calls v1 `check_entry`).
- Replays: only rows known by the run's `as_of` (event rows by `created_at`, restrictions by `as_of` date); IST dates.
- Fail-open like v1: a feed that has not loaded must not veto every trade.

## Review Focus

1. Results date falls on a weekend/holiday-heavy week — the 5-trading-day window counts trading days, not calendar days — Task 1 `test_the_window_counts_trading_days`.
2. A restriction row older than 4 days is not treated as current — Task 1 `test_old_restriction_lists_are_ignored`.
3. A replay must not see an event row stored after its date — Task 2 `test_replays_do_not_see_events_stored_later`.
4. A "breakdown" situation on an ex-date day is ignored by M08 — Task 3 `test_an_ex_date_drop_is_not_a_breakdown`.
5. M03's own StockState fields are never overwritten by a plug-in, only its empty ones filled — Task 3 `test_plugins_fill_only_empty_stock_fields`.

---

### Task 1: Pure event calendar (`m13_news/calendar.py`)

**Interfaces — Produces:** `RESULTS_WINDOW_TRADING_DAYS = 5`, `ACTION_WINDOW_TRADING_DAYS = 2`, `RESTRICTION_MAX_AGE_DAYS = 4`, `NOTE_AHEAD_DAYS = 21`, `trading_days_until(today, day) -> int`, `EventRow(symbol, kind, day, detail)`, `RestrictionRow(symbol, kind, stage, as_of)`, `read_calendar(symbol, today, events, restrictions) -> StockEvents(situations, restrictions, notes)`.

Labels: `results soon` (evidence "Results on 14 Oct: the brain avoids new trades 5 trading days before results"), `event blackout` (corporate action within 2 trading days), `price reset` (ex-date today or in the last 2 trading days; evidence names the action). Notes: next results date within 21 days ("Results on 14 Oct."), price-reset line.

- [ ] Tests (window counts trading days; blackout boundary 5 in / 6 out; past results ignored; corporate action 2-day window; price reset after ex-date; old restriction ignored; restriction names "ASM (Stage I)") → FAIL → implement → PASS → commit.

### Task 2: Reader access and the M13 module

**Files:** `brain/reader.py` (`event_rows(symbols) -> list[EventRow]` with `created_at <= as_of`, `restriction_rows(symbols) -> list[RestrictionRow]` with `as_of <= run date`), `brain_fakes.FakeReader` (both empty), `m13_news/module.py` (`EventsBrain`, id M13, Step.RECOGNISE, plugin, default ON, writes Situation@1, StockState@1, Opinion@1; skipped intraday? No — intraday holdings need the results note: keep budget small), `brain/opinions.py` (`MODIFIER_SOURCES` += "event").

- [ ] Tests (module writes situations/restrictions/notes for universe + holdings; DB test for replay bound on created_at) → FAIL → implement → PASS → commit.

### Task 3: Merge and M08 wiring

**Files:** `brain/context.py` (stocks merge = `_fill_gaps` per symbol), `m08_decide/rules.py` (`_event_window` ignores `breakdown` when a `price reset` situation exists; holdings get the results line via modifier notes already).

- [ ] Tests: full run M03-like stock state + M13 restrictions → AVOID "On the exchange's watch list (ASM …)"; results in 3 trading days → AVOID with the spec wording; holding with results soon → HOLD plus note; ex-date + breakdown → not AVOID → implement → PASS → commit.

### Task 4: Real-data check, notes, memory

- [ ] Run nightly on the check DB with M13 ON; list AVOIDs and event lines; full suite + lint; BUILD_NOTES + memory; restart :8001.
