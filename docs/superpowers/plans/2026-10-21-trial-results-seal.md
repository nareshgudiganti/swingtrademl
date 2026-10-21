# Trial Results Seal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The server never sends the blind forward trial's results (profit, hit rate, average result, any
baseline comparison, or splits of them) for brain ideas decided on or after 2026-10-14; counts and safety
information stay visible.

**Architecture:** One module, `services/trial_seal.py`, holds the switch (`SEALED = True`, a code constant)
and the first sealed day (`SEALED_FROM = brain.trial_journal.TRIAL_START`), plus small pure helpers
(`is_sealed_day`, `seal_journal`, `seal_daily_trial`, `sealed_gate`, `learning_report`, ...). Each serving
point (endpoint, report builder, CLI print) calls a helper on its way out. Nothing that decides a pick,
size, stop, order or the go-live gate's real answer changes; no frozen file (tests/trial_freeze.json) is
touched.

**Tech Stack:** FastAPI, SQLAlchemy, pytest (Docker Postgres), React + TypeScript, vitest.

**Spec:** `docs/superpowers/specs/2026-10-21-evidence-plan-amendment-1.md` section A4 and A11 decision 4
(branch docs/evidence-amendment-1).

## Global Constraints

- Sealed = brain ideas / brain strategy outcomes with an IST decision day >= 2026-10-14 (`TRIAL_START`).
- Never sent for sealed days: profit/loss, hit rate, average result (`avg_net`, `avg_outcome_pct`,
  `gross_return`, ...), best/worst move, edge vs every stock or any baseline, gate words that reveal them
  ("pass", "behind", `profit`, `beats_random`).
- Always visible: counts (ideas, finished, still open, blocked, sessions), safety checks, run errors,
  modules dropped, data freshness, halts, risk-rule checks.
- Days before 2026-10-14 and version 1's own (non-brain) results stay exactly as before.
- Unsealing = flip `SEALED` in its own recorded commit with owner approval (not an env var).
- No change to decision/order/sizing/stop/risk logic; trial freeze test must stay green.

## Review Focus

- A date range that straddles the trial start: the days before keep their figures, trial days are counts.
- Daily-check rows stored before the seal existed (they hold hit rate / avg_net / edge): stripped on read.
- The go-live gate: the page may not say "pass"/"behind", yet `set_stage` must still refuse/allow exactly
  as before.
- Learning proposals written during the trial quote results in their evidence text: sealed by creation day.
- Telegram texts (daily-check problem message, weekly health, daily summary): no result can appear.

---

### Task 1: The switch and helpers

**Files:** Create `backend/src/swing_trade_ml/services/trial_seal.py`.

- [x] `SEALED = True`, `SEALED_FROM = TRIAL_START`, `SEALED_TEXT`, helpers listed above.

### Task 2: The leak test (written first; fails with `SEALED = False`)

**Files:** Create `backend/tests/test_trial_seal_leaks.py`.

- [x] Seed a live nightly brain run on 2026-10-15 with a finished TRADE idea (return 0.0777, best
  **0.7316492** = the distinctive number, worst -0.0233), the brain strategy's Signal, a learning proposal,
  and a pre-seal stored daily-check row holding hit rate / avg_net / edge.
- [x] Call EVERY GET route of the app (enumerated from `app.openapi()`; outside-service routes skipped by
  name with a reason) plus extra query variants; assert no planted number appears in any body.
- [x] Same for `daily.compute`, the trial-journal report, the evidence pack (JSON + markdown).
- [x] Telegram builders: daily-check problem message, weekly health message, daily summary.
- [x] Counter-checks: the same seed on 2026-10-09 still shows the numbers; `SEALED = False` shows them;
  the go-live gate allows/refuses exactly as before.
- [x] Verify: with `SEALED = False` the route test fails (17 responses leak).

### Task 3: Seal each serving point

- [x] `/brain/observatory/outcomes` (outcomes.py `_build_sealed`), `/brain/observatory/runs/{id}/stocks/{id}`,
  `/brain/observatory/forward-gate`, `/brain/observatory/evidence-pack` (pack.py).
- [x] `/brain/daily-checks`, `/brain/daily-checks/latest`: counts only stored for trial days, and old rows
  stripped on read.
- [x] `/brain/compare` (compare.py, `brain_before_trial`), `/brain/stage` (stage.py, counts-only gate),
  `/brain/trial-journal` + its CLI/markdown, `/brain/learning` + CLI, `/brain/proposals` evidence,
  `/signals/track-record`, `/ml/calibration?source=signals`.

### Task 4: Frontend calm sealed state

- [x] Observatory results card, stock detail outcome, Go-live compare + stage cards, Records and
  ScanResults track record: show "Sealed until the trial's evaluation (blind test): counts only."
- [x] `npx tsc --noEmit -p .`, vitest on touched areas, e2e journey for the sealed go-live card.

### Task 5: Verify and ship

- [x] ruff check / format on touched files only; trial-freeze test; full backend suite.
- [ ] Commit, push `feature/trial-results-seal`, open PR against main. Do not merge or deploy.
