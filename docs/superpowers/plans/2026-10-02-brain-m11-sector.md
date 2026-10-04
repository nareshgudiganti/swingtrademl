# M11 Sector Brain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rank NSE sector indices by strength against NIFTY, label each one's rotation (leading / improving / weakening / lagging), and use that as a small, never-deciding tilt and a card line for each stock.

**Architecture:** A pure `ranking.py` turns closing-price series into `SectorState`s. A plug-in module on the STATE step writes the sector table plus one `source="sector"` *modifier* opinion per stock. Modifier opinions never speak for a stock (`pick_opinion` skips them); they only nudge the risk gate's order (`rank_strength`) and add a line to cards (`modifier_notes`). The run stores its sector table in a new `brain_runs.context` JSON column, shown on the console.

**Tech Stack:** Python 3.12, pandas, SQLAlchemy 2, Alembic, FastAPI, React + TanStack Query.

**Spec:** `docs/superpowers/specs/2026-09-29-trademind-brain-build-book.html` — module sheet "M11 Sector brain"; contract `SectorState@1` (sector, rank, of_total, strength_20d, rotation).

## Global Constraints

- Plug-in, Wave 3, Brain step 2 State (+ opinions). Reads sector index candles and StockState@1. Writes SectorState@1 and a small sector Opinion@1 tilt.
- Relative strength of each sector index vs NIFTY over 20 and 60 days; rank.
- Rotation quadrant from 20-day vs 60-day relative strength (leading, improving, weakening, lagging).
- Map each stock to its sector with `ml/sector_map.py`.
- Tilt: leading +0.1, improving +0.05, weakening −0.05, lagging −0.1.
- If switched off: no sector ranking; no tilt. The 25% sector cap still applies inside M07.
- Card line: "Sector: IT, ranked 3 of 14, improving".
- Brain invariants: dates bounded by the run's `as_of` (reader), first-writer-wins merge, never bolder, plain English (owner has no finance background).
- Keep everything local; no push.

## Review Focus

1. A stock whose ONLY opinion is the sector tilt (model has no score) must not become liked/TRADE — Task 2 test `test_a_sector_tilt_alone_never_speaks_for_a_stock`.
2. A sector index with too little history (< 61 bars, e.g. a new index) is left out of the ranking rather than ranked on NaN — Task 1 test `test_short_history_sectors_are_left_out`.
3. Unmapped stocks (conglomerates, telecom) get no tilt and the line "Sector: not classified" is NOT invented — Task 3 test `test_unmapped_stocks_get_no_tilt`.
4. Two buckets sharing one index (CHEMICALS and COMMODITIES → NIFTY COMMODITIES) are ranked once, not twice — Task 1 test `test_each_index_is_ranked_once`.
5. Old runs stored before the `context` column exist show no sector table and do not crash the API — Task 4 test `test_runs_without_context_show_no_sectors`.

---

### Task 1: Pure sector ranking

**Files:**
- Create: `backend/src/swing_trade_ml/brain/modules/m11_sector/__init__.py` (empty docstring)
- Create: `backend/src/swing_trade_ml/brain/modules/m11_sector/ranking.py`
- Test: `backend/tests/test_brain_m11_sector.py`

**Interfaces:**
- Produces: `SECTOR_NAMES: dict[str, str]` (index symbol → plain name), `TILT: dict[str, float]`, `relative_strength(sector: pd.Series, nifty: pd.Series, days: int) -> float | None`, `rotation(rs20: float, rs60: float) -> str`, `rank_sectors(closes: dict[str, pd.Series], nifty: pd.Series) -> list[SectorState]` (sector = index symbol, sorted by rank), `sector_line(s: SectorState) -> str`.

- [ ] Step 1: tests — rising sector ranks above falling; quadrant mapping for the four sign combinations; short history left out; each index once; `sector_line` text "Sector: IT, ranked 1 of 2, leading".
- [ ] Step 2: run, expect ImportError.
- [ ] Step 3: implement. `relative_strength` = sector return over `days` − NIFTY return over `days` (None when either has ≤ days bars). Rotation: rs20>0 & rs60>0 leading; rs20>0 & rs60≤0 improving; rs20≤0 & rs60>0 weakening; else lagging. Rank by rs20 desc, then rs60 desc, then name.
- [ ] Step 4: run, expect PASS. Commit "Brain M11: rank sectors against NIFTY and label rotation".

### Task 2: Modifier opinions (shared rule in `brain/opinions.py`)

**Files:**
- Modify: `backend/src/swing_trade_ml/brain/opinions.py`
- Modify: `backend/src/swing_trade_ml/brain/modules/m07_risk/module.py` (use `rank_strength`)
- Modify: `backend/src/swing_trade_ml/brain/modules/m08_decide/engine.py`, `module.py` (notes on ideas and holdings)
- Test: `backend/tests/test_brain_opinions.py` (create)

**Interfaces:**
- Produces: `MODIFIER_SOURCES = frozenset({"sector"})` (M12/M13 add theirs), `TILT_WEIGHT = 0.25`, `pick_opinion` ignores modifiers, `rank_strength(opinions) -> float` = strength(primary) + TILT_WEIGHT × sum(modifier stances) (0 primary → only used for order), `modifier_notes(opinions) -> tuple[str, ...]`; `IdeaFacts.notes`, `HoldingFacts.notes` (tuple[str, ...], default ()), appended after rules.

- [ ] Step 1: tests — tilt alone never speaks (`pick_opinion` → None, so M08 says WAIT "No opinion"); tie broken by tilt in the M07 allocator order; notes appended to idea and holding reasons and never change the word.
- [ ] Step 2: run, expect FAIL.
- [ ] Step 3: implement.
- [ ] Step 4: full brain suite PASS. Commit.

### Task 3: The M11 module and reader access

**Files:**
- Create: `backend/src/swing_trade_ml/brain/modules/m11_sector/module.py`
- Modify: `backend/src/swing_trade_ml/brain/modules/__init__.py`, `backend/src/swing_trade_ml/brain/reader.py` (`sector_closes() -> dict[str, pd.Series]`, as_of-bounded, via `_closes`)
- Modify: `backend/tests/brain_fakes.py` (FakeReader.sector_closes)
- Test: `backend/tests/test_brain_m11_sector.py`

**Interfaces:**
- Consumes: Task 1 `rank_sectors`, `TILT`, `sector_line`; `ml.sector_map.get_sector_bucket(symbol)` and `_SECTOR_INDEX` (bucket → index).
- Produces: `SectorBrain` (id M11, Step.STATE, kind plugin, writes SectorState@1 + Opinion@1, default ON, intraday skipped); one `Opinion(source="sector", stance=TILT[rotation], confidence=0.3, reasons=(sector_line,))` per mapped stock in universe + holdings.

- [ ] Step 1: tests — registered as plug-in; writes ranked sectors; tilt values per rotation; unmapped stock → no opinion; reader returns nothing → no contribution; intraday → nothing.
- [ ] Step 2–4: implement, PASS, commit.

### Task 4: Store and show the sector table

**Files:**
- Create: `backend/alembic/versions/20261002_1000_brain_run_context.py` (revision `5b7e2d9c3a11`, down `2f8c1a7e5d40`): `brain_runs.context` JSON nullable.
- Modify: `backend/src/swing_trade_ml/db/models/brain.py`, `brain/service.py` (`_store` writes `{"sectors": [...]}`), `api/v1/endpoints/brain.py` (`_run_out` adds `sectors`), `frontend/src/api/types.ts`, `frontend/src/pages/Brain.tsx` (collapsible "Sectors" table: rank, plain name, rotation in words, 20-day vs NIFTY).
- Test: `backend/tests/test_brain_api.py`

- [ ] Steps: failing API test (sectors listed for a run with M11 output; empty list for a run without context) → migration + code → PASS → `npx tsc --noEmit` → commit.

### Task 5: Real-data check, notes, memory

- [ ] Upgrade the check DB (`alembic upgrade head`), run nightly with M11 ON, run `swingtrade brain why WIPRO`; expect "Sector: IT, ranked N of 15, <rotation>".
- [ ] Full suite + lint on brain paths; update `docs/brain/BUILD_NOTES.md` and memory; restart :8001.
