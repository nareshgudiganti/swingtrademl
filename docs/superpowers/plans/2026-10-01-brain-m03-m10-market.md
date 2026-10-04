# Brain M03 State Engine + M10 Market Brain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Describe the current state of market, stocks, portfolio and system in one place (M03), and decide the market mode — NORMAL, DEFENSIVE or NO NEW TRADES — from trend, volatility, breadth, India VIX and FII flows together, with plain reasons (M10).

**Architecture:** M03 (step module) writes market *facts* with `mode=None`, plus stock, portfolio and system state. M10 (plug-in, same step) fills the mode and reasons. Because merge is first-writer-wins and fills only empty fields, M10 can refine M03; when M10 is off, the state fallback (which always runs after the modules) fills the mode from the trend alone. M10 wraps v1's tested `deployable.classify_deployable` regime table and adds only what it lacks: FII flows, a crash-day rule and confirmation before relaxing.

**Tech Stack:** Python 3.12, pandas, SQLAlchemy 2, pytest; existing `ml/market_context.py`, `services/deployable.py`, `services/portfolio.py`, `services/limits.py`, `services/risk.py`.

**Spec:** `docs/superpowers/specs/2026-09-29-trademind-brain-build-book.html` — module sheets M03 and M10; section 7.3 (market modes); principle P5 (wrap, don't rewrite).

## Global Constraints

- `MarketState.mode` becomes optional (`None` = not decided yet); every reader of the mode treats `None` as DEFENSIVE.
- Regime → mode: `normal`, `strong`, `very_strong` → NORMAL; `weak`, `stressed`, `unknown` → DEFENSIVE.
- FII rule: FIIs net sellers on ≥ 4 of the last 5 sessions AND net negative over the last 20 → a `normal` regime becomes DEFENSIVE (`strong` and `very_strong` are not lowered: breadth confirms them).
- Crash rule (latest bar): NIFTY one-day change ≤ −4% or India VIX one-day change ≥ +30% → NO NEW TRADES.
- Confirmation: entering DEFENSIVE is immediate; returning to NORMAL needs the raw mode NORMAL on the latest bar AND the bar before.
- No new opinions from M10 yet (a market tilt would make every stock a candidate when no model score exists); deferred to M06.
- Portfolio state is "now" data: filled only for live runs.

## Review Focus

1. M03 runs before M10; M10 must still decide the mode. (Task 1 test)
2. A replay of a known bad week (June 2022) reads DEFENSIVE with reasons; a calm uptrend reads NORMAL. (Task 4 local check)
3. A single good day after a weak spell stays DEFENSIVE (confirmation). (Task 2 test)
4. No FII data at all → no flow rule, and the reasons say flows were not available. (Task 2 test)
5. With M10 off the brain still has a mode (fallback). (Task 1 test)

---

### Task 1: Optional market mode
Files: `brain/contracts.py`, `brain/fallbacks.py`, `brain/modules/m07_risk/module.py`; tests in `test_brain_runner.py`.
- [ ] Failing tests: a STATE module writing facts with `mode=None` + a plug-in writing the mode → plug-in's mode used; with only the facts module → fallback mode used; banner never None.
- [ ] Implement; full brain tests; commit.

### Task 2: Pure market judge (M10)
Files: `brain/modules/m10_market/__init__.py`, `judge.py`; test `test_brain_m10_judge.py`.
Interfaces: `MarketInputs(index_close: Series, vix_close: Series, breadth: Series, fii_net: list[float])`; `judge(inputs) -> MarketState`.
- [ ] Failing tests: uptrend with broad breadth → NORMAL; downtrend → DEFENSIVE with a trend reason; NIFTY −5% day → NO_NEW_TRADES; VIX +35% day → NO_NEW_TRADES; normal regime + FII selling → DEFENSIVE; strong regime + FII selling stays NORMAL; one good day after DEFENSIVE stays DEFENSIVE; no FII data → reason says so; not enough index history → DEFENSIVE "cannot judge".
- [ ] Implement; commit.

### Task 3: M10 module + reader series
Files: `m10_market/module.py`, `brain/reader.py` (`vix_closes`, `breadth_series`, `fii_net`), `brain/modules/__init__.py`; tests `test_brain_m03_m10_module.py`.
- [ ] Failing tests (DB): registered as plug-in in STATE; series end at `as_of`; mode and reasons appear on the run banner.
- [ ] Implement; commit.

### Task 4: M03 state engine
Files: `brain/modules/m03_state/__init__.py`, `state.py` (pure `stock_state`), `module.py`, reader `portfolio_numbers`; tests in the same DB test file + pure tests.
- [ ] Failing tests: stock trend / relative strength / distance from 52-week high; portfolio numbers for live runs only; system halt carried; market facts with `mode=None`.
- [ ] Implement; full suite; lint; commit.
- [ ] Local check on `brain_m00_check`: replays of 2022-06-17, 2024-07-01, 2026-09-07; restart the console API.
