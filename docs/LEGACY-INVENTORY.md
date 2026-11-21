# Legacy Inventory: TradeMind / Swing Trade Bot

Feature: #392, Legacy Code Identification, Technical Debt Reduction and Safe Cleanup.
Snapshot: `origin/main` at `40bf4b0` (2026-11-20). Written 2026-11-21.
Phase: **Discovery (read-only).** No application code was changed or deleted.
Status: **Draft. Awaiting owner approval.** Cleanup starts only after approval, one story per worktree and PR, each with a Codex review.

---

## 0. Summary

| | |
|---|---|
| Code scanned | ~136,000 lines of app code (backend ~86K, frontend ~49.5K), 1,714 tracked files. Tests, migrations and docs were also scanned. |
| Candidates identified | **137** (after removing 2 duplicates found by two auditors) |
| VERIFIED UNUSED | **15**: about 470 lines of app code plus ~310 lines of tests, all low risk |
| LIKELY UNUSED | **19**: about 1,800 lines of code plus ~1,300 lines of stale docs |
| REQUIRES RUNTIME VERIFICATION | **31**: up to ~12,500 more lines, almost all in two parked areas (hidden Classic screens, parked Finance) |
| ACTIVE | **29**: looked suspicious but are in use. Keep. |
| PROTECTED | **43**: models, evidence, protocols, history, safety. Never removed without explicit owner approval. |
| Unused dependencies | Frontend: 3 truly unused (`eslint`, `@typescript-eslint/*` ×2), because there is no ESLint config. Python: none truly unused; 4 likely unused dev or extra items. |

**What this means**
- The codebase has **very little provably dead code**. The ML and Brain area has none: what looks orphaned is kept to reproduce signed evidence.
- The real size win (~12,500 lines, about 9% of app code) sits in two areas that need **your decision plus a production check**, not just a code search:
  1. the **hidden Classic look**: screens still in the code but never shown in production
  2. the **parked Finance/mutual-funds module**
- The biggest **AI-context** win is the docs: 288,625 lines across 367 files, including several stale files that contradict the current setup.

---

## 1. Scope, method and limits

- **Five parallel read-only auditors** (Agent Teams teammates on Sonnet) covered: backend APIs and services; frontend; ML, features, training and scoring; database tables, migrations and jobs; infra, config, dependencies and docs. The team lead (Opus) merged and spot-checked the results.
- **Evidence was static**: `git grep` over `src`, tests, scripts, workflows, infra and docs, plus an AST scan of top-level definitions (backend) and a resolved import graph from `main.tsx` (frontend). Dynamic references (scheduler ids, registries, `python -m` entry points, files loaded by path) were checked by hand.
- **No runtime evidence was collected.** There was no production access, no database access and no `.env` access. Anything that could be reached at runtime and couldn't be ruled out is classed REQUIRES RUNTIME VERIFICATION, with the read-only check needed (section 12).
- The team lead re-checked the 15 VERIFIED UNUSED items with independent greps. **Corrections to auditor findings** are in section 13.

### Classification key

| Class | Meaning |
|---|---|
| **VERIFIED UNUSED** | No importer, route, string or dynamic reference, script, workflow or documented entry point after an exhaustive search. Safe to remove with normal tests. |
| **LIKELY UNUSED** | Only tests, docs or a comment reference it, or it is one step from unused. Needs a small check or owner nod. |
| **REQUIRES RUNTIME VERIFICATION** | It could be reached at runtime: a direct URL, outside caller, setting, job or stored data. Needs the production check in section 12. |
| **ACTIVE** | In use. Keep. |
| **PROTECTED** | Historical models, evidence, protocols, scoring or prediction history, audit records, migrations, safety mechanisms, the v1 trading path. Never removed without explicit verification and owner approval. |

Risk scale: Low (no behaviour change), Medium (a route, setting or screen goes), High (data, money, auth or broker-adjacent), Protected.

---

## 2. Size scanned by module

| Module | Files | Lines |
|---|---:|---:|
| backend `brain/` | 132 | 28,014 |
| backend `services/` | 117 | 26,536 |
| backend `api/` | 50 | 10,178 |
| backend `ml/` | 24 | 6,871 |
| backend `db/` (models) | 30 | 3,148 |
| backend `core/` | 15 | 2,319 |
| backend `workers/` | 5 | 1,757 |
| backend `shadow_lanes/` | 7 | 1,522 |
| backend `brokers/` | 4 | 1,187 |
| backend `cli.py`, `schemas`, `main.py`, `notifications`, `strategies` | 7 | 3,791 |
| **Backend app code** | **~391** | **~85,300** |
| backend migrations (`alembic`) | 72 | 4,435 |
| backend `scripts/` | 15 | 3,479 |
| backend tests | 358 | 74,228 |
| **Frontend app code** (`src`, excl. tests) | **198** | **49,553** |
| frontend unit tests | 83 | 8,872 |
| frontend e2e | 47 | 3,013 |
| infra, compose, workflows, `render.yaml` | 30 | 2,516 |
| root `scripts/` | 11 | 642 |
| `docs/` | 367 | 288,625 |

Database: **84 tables** (counted from `__tablename__`; the "~75" in older notes is low), **70 migrations** with a single head `20261111_1200_watchlist_sales` (from a static parse), and **37 scheduled jobs at most** (28 core + 7 brain + 2 gated lanes; 35 typical). The "~32 jobs" figure in older notes is wrong.

---

## 3. Candidates by area and class

| Area | Total | Verified unused | Likely unused | Runtime check | Active | Protected |
|---|---:|---:|---:|---:|---:|---:|
| Backend APIs and services (BE) | 24 | 7 | 3 | 8 | 4 | 2 |
| Frontend (FE) | 25 | 6 | 4 | 12 | 2 | 1 |
| ML, features, scoring (ML) | 30 | 0 | 2 | 2 | 7 | 19 |
| Database and jobs (DB/JOB) | 25 | 0 | 0 | 7 | 6 | 12 |
| Infra, config, deps, docs (INF/CFG/DEP/DOC) | 33 | 2 | 10 | 2 | 10 | 9 |
| **Total** | **137** | **15** | **19** | **31** | **29** | **43** |

Two duplicates were merged: BE-11 = ML-03 (`sma_crossover`) and INF-09 = ML-21 (the sector scripts).

### Potential removable size

| Class | App code lines | Test lines | Docs lines | Whole files |
|---|---:|---:|---:|---:|
| Verified unused | ~470 | ~310 | 0 | 8 |
| Likely unused | ~1,800 | ~600 | ~1,300 + up to 37 plan files (archive) | ~10 |
| Runtime check (if confirmed unused) | ~12,500 | not measured | 0 | ~35 |

---

## 4. Inventory: backend APIs and services

| ID | Path :: component | Purpose / status | Class | Conf. | Evidence | Replacement | Risk | Action | Removable | Tests |
|---|---|---|---|---|---|---|---|---|---|---|
| BE-01 | `endpoints/orders.py` GET/cancel/sync | v1 order list and manual cancel/sync; `POST /orders` already removed (4961507) | PROTECTED | High | No frontend caller; 6 test files | none | Protected (order path) | INVESTIGATE (access logs only) | 0 | keep `test_orders_no_manual_placement` |
| BE-02 | `endpoints/backtest.py` `POST /backtest` | UI backtest; no frontend, scripts or workflows | RUNTIME | Med | CLI calls the service directly (`cli.py:484`) | CLI `backtest` | Med | REMOVE endpoint only | 54 + router line | `test_backtest.py` (service), route-absent check |
| BE-03 | `market_data.py` quote, ltp | Raw quote reads; frontend 0, tests 1 | LIKELY | Med | grep frontend/scripts/docs = 0 | `/market-data/snapshot` | Low | REMOVE after log check | ~40 | update `test_market_data` |
| BE-04 | `market_data.py` feeds/status, refresh, backfill, refresh-quotes | Manual triggers | RUNTIME | Med | frontend 0; scheduler jobs do the work | scheduler jobs | Low | INVESTIGATE → REMOVE | ~50 | job tests stay |
| BE-05 | `notifications.py` telegram/daily-summary | Manual summary send; frontend 0, tests 0 | RUNTIME | Med | only `job_daily_summary` uses the notifier | `job_daily_summary` | Low | REMOVE route | ~12 | job smoke check |
| BE-06 | `signals.py` `GET /signals/latest` | Only caller is unused `api.latestSignals` | LIKELY | Med | `client.ts:547` has 0 callers | `/signals/picks`, `/signals/buy-list` | Low | REMOVE with FE-21 | ~34 | none existing |
| BE-07 | `endpoints/release_switches.py` | Duplicate of `/admin/console/release-switches` | **VERIFIED** | High | UI calls only the console path (`AdminUsers.tsx:354`) | admin console route (audited, step-up) | Low | REMOVE | 15 + 2 router lines | update `test_admin_step_up_gate.py:122` list |
| BE-08 | `plans.py` `/admin/users`, `/admin/users/{id}/plan` | Old admin user list; used by `PlansManager.tsx:225,227` | ACTIVE | High | route `/plans` (`App.tsx:119`) | admin console (long term) | Med | KEEP (migrate later, story S10) | 0 | — |
| BE-09 | `billing.py` admin grants | Older grant routes | RUNTIME | Low | UI uses console grants | admin console grants | Med | INVESTIGATE, COORDINATE #379 | ~60 | `test_billing*` |
| BE-10 | `/ml/backup/models.zip` | Manual model pull (`scripts/backup-models-from-prod.ps1:47`) | RUNTIME | High (used) | script + 2 tests | offsite backup script | Protected-adjacent | KEEP | 0 | — |
| BE-12 | `services/price_change_detector.py` | Report-only historical price checker, run by hand (`python -m`, documented) | LIKELY | Med | 0 importers; test + doc only | none | Low | KEEP or ARCHIVE (owner) | 559 + test | — |
| BE-13 | `services/corporate_action_accounting.py` | **First step of corporate-action accounting** (PR #142, 4 Nov), not wired yet; board #247 | ACTIVE (staged) | High | migration + model + tests | none | — | KEEP, COORDINATE #381 | 0 | — |
| BE-14 | `ingestion.ensure_benchmark_index` | Dead helper | **VERIFIED** | High | src 1 (the def), tests 0, other 0 | none | Low | REMOVE | ~12 | full backend suite |
| BE-15 | `finance/mutual_funds.backfill_scheme_history` | Dead helper | **VERIFIED** | High | src 1, tests 0 | NAV sync job | Low | REMOVE | ~25 | suite |
| BE-16 | `watchlist_snapshots.latest_snapshot_date` | Dead helper (stock-tracking module) | **VERIFIED** | High | src 1, tests 0 | none | Low | REMOVE (separate commit) | ~10 | suite |
| BE-17 | `model_registry.all_slot_keys` | Dead helper | **VERIFIED** | High | src 1, tests 0 | none | Low | REMOVE | ~5 | suite |
| BE-18 | `core.enums.CandleInterval` | Dead enum (not an ORM type) | **VERIFIED** | High | src 1, tests 0 | none | Low | REMOVE | ~6 | suite |
| BE-19 | `schemas.OrderCreate` | Leftover from removed `POST /orders` | **VERIFIED** | High | src 1, tests 0 | M18 approvals, `/portfolio/real/*` | Low (order-adjacent) | REMOVE, mention in PR | ~12 | suite |
| BE-20 | `core.security.require_api_key` | Old auth helper; 0 references | PROTECTED | High | `deps.require_auth` is the live path | `deps.require_auth` | High (auth) | KEEP until a `security-review` | 0 | — |
| BE-21 | `require_release` + `customer_screens` switch | Release switch registry | ACTIVE | High | console reads `switch_states` | — | — | KEEP, COORDINATE #379 | 0 | — |
| BE-22 | `endpoints/finance.py` + `services/finance/` | Personal finance, **parked, not retired** (nav hidden 2026-09-28) | RUNTIME | High (parked) | `/finance` still routed | none | High (personal data) | Owner decision (S9) | ~3,240 incl. models | 5 test files |
| BE-23 | `endpoints/mutual_funds.py` + NAV job | Mutual-fund tracking; job `sync_mutual_fund_navs` is live | RUNTIME | High | scheduler registers the job | none | High | Owner decision (S9) | ~380 | — |
| BE-24 | `/instruments/watchlist` (global) | Drives scans; Settings uses it | ACTIVE | High | `client.ts:594-595` | `/me/watchlist` per user (long term) | Protected-adjacent | KEEP, COORDINATE #382 | 0 | — |
| BE-25 | `ops.py`, `server_watch.py`, `weekly_report.py` endpoints | ops = service-key caller; server_watch endpoint likely unused (the job is ACTIVE); weekly_report needs a check | RUNTIME | Med | nginx logs needed | — | Low | INVESTIGATE | ~83 | — |

Not proposed for removal (ACTIVE or PROTECTED by rule): all `/brain/*` and score-trail endpoints, trial journal, weekly health, daily checks, watchlist and score-history services, positions, `/safety/*`, `is_exits_disabled`, `trial_seal.proposal_evidence`, risk checks, limits, the deployable cap, order execution.

---

## 5. Inventory: frontend

Context: the Classic look is **hidden in code**. `trademind/look.ts:13` sets `CLASSIC_LOOK_IN_CODE = false` (owner, 2026-11-11). A production build always renders the new look, unless it is built with `VITE_CLASSIC_LOOK=on`. Vitest and Playwright turn Classic on so it stays tested. No deploy workflow, compose file or Dockerfile sets `VITE_CLASSIC_LOOK` (checked).

| ID | Path :: component | Purpose / status | Class | Conf. | Evidence | Replacement | Risk | Action | Removable | Tests |
|---|---|---|---|---|---|---|---|---|---|---|
| FE-01 | `trademind/pages/Home.tsx` | Old Today page; no importer except one test | **VERIFIED** | High | resolved import graph, lazy/string grep 0 | `Today` / `TodayNew` | Low | REMOVE (+ edit `todayDiscover.test.tsx`) | 203 | tsc, vitest, build |
| FE-02 | `trademind/pages/Dashboard.tsx` | Unrouted; `/trademind/dashboard` uses `Today` | **VERIFIED** | High | importers are 2 test files | `Today` | Low | REMOVE + its test | 33 + 98 test | tsc, vitest |
| FE-03 | `trademind/beginner/BottomBar.tsx` | Never wired ("not wired yet" comment) | **VERIFIED** | High | test-only importer | `NewLookShell` | Low | REMOVE + test | 28 + 36 test | tsc, vitest |
| FE-04 | `trademind/today/featureList.ts` | Orphan; mentioned only in a comment | **VERIFIED** | High | test-only importer | none | Low | REMOVE + test | 76 + 178 test | tsc, vitest |
| FE-05 | `stockParts` `MoneyMeter`, `SafetyInWords`, `PeekCard` | Unused exports in a live file | LIKELY | Med | no importer | none | Low (safety wording) | Owner eyeball, then remove | ~60 | tsc, vitest |
| FE-06 | small dead exports | Mostly test-only users | LIKELY | Med | per-name grep | none | Low | REFACTOR (drop `export`) | 0 | tsc |
| FE-07 | `trademind/pages/Market.tsx` | Classic only (`TradeMindApp.tsx:320`) | RUNTIME | Med | classic branch only | `MarketNew` | Med | REMOVE in S8 | 173 | classic-gated tests and e2e |
| FE-08 | `trademind/pages/Opportunities.tsx` | Classic only | RUNTIME | Med | same | `DiscoverNew` | Med | S8 | 150 | same |
| FE-09 | `trademind/pages/Watchlist.tsx` | Classic only | RUNTIME | Med | same | `WatchlistNew` | Med | S8, **COORDINATE #382** | 107 | same |
| FE-10 | `trademind/pages/StockDetail.tsx` | Classic only; `/trademind/stock/:symbol` links resolve to `StockNew` | RUNTIME | Med | same | `StockNew`, `StockAnalysis` | Med | S8 | 463 | `journeys.spec`, `score-trail-models.spec` |
| FE-11 | `trademind/pages/Portfolio.tsx` | Classic only | RUNTIME | Med | same | `PortfolioNew`, `PaperPositions` | Med | S8, **COORDINATE #381** | 356 | same |
| FE-12 | `trademind/pages/Learn.tsx`, `Records.tsx` | Classic only | RUNTIME | Med | same | `EvidenceNew`, `HistoryNew` (check data parity first) | Med | S8 | 853 | same |
| FE-13 | `ClassicShell` in `TradeMindApp.tsx:148-290` | Classic shell | RUNTIME | Med | — | `NewLookShell` | Med | S8, last step | ~140 (refactor) | `newLook`, `navigation`, `menu` tests |
| FE-14 | `beginner/InsightsPanel`, `EvidencePanel`, `StockBrief`, `StrategySignals.tsx`, `insights.ts` | Reachable only through Classic pages | LIKELY | Med | graph walk without Classic leaves these 5 unreachable | — | Low | S8; also decide backend `/beginner/evidence`, `/beginner/insights` | 536 + 281 test | vitest |
| FE-15 | Classic branch of `Today.tsx` | Used in both looks (`TradeMindApp.tsx:319`) | ACTIVE | High | route | — | — | KEEP | 0 | — |
| FE-16 | `pages/Brain.tsx` + `HoldingTracker`, `BrainGoLive` | Old owner brain page, shown only when `brain_enabled` is false | RUNTIME | Med | `App.tsx:422-428,668` | TradeMind Control, GoLive, Observatory | Med | S10 decision | 1,064+ | — |
| FE-17 | Classic v1 screens (Dashboard, Strategies, Capital, Reports, ScanResults, ModelLab, Holdings, PlanHome, Positions; **Safety = PROTECTED**) | Served when a plan lacks `trademind` (`App.tsx:400`) | RUNTIME | Low | `SCREENS` array; `classic-parity-allowlist.json` | TradeMind pages | High | S10 decision | ~3,300 | parity allowlist |
| FE-18 | `pages/Finance.tsx` | Parked Finance UI | RUNTIME | Med | routed `/finance` | none | High | S9 decision | 1,626 | — |
| FE-19a | `pages/Settings.tsx` | Change password, sign out everywhere (P0 security) | PROTECTED | High | allowlist `keep` | — | — | KEEP | 0 | — |
| FE-19b | `pages/Models.tsx` | Routed, out of nav | RUNTIME | Med | allowlist `decide` | — | Med | S10 decision | 360 | — |
| FE-20 | `HorizonPicks`, `HorizonReport`, `ModelRegistry` | Owner-only by design | ACTIVE | High | routed `App.tsx:337,361` | — | — | KEEP | 0 | — |
| FE-21 | 11 unused `api.*` members in `api/client.ts` (`health`, `snapshot`, `latestSignals`, `signalHistory`, `updateStrategy`, 6 finance members) | Client functions with no callers | **VERIFIED** | High | 0 callers across all files including tests (team lead re-checked 7) | — | Low | REMOVE (finance members wait for S9) | ~40 | tsc, `classic-parity --check` |
| FE-22 | `eslint`, `@typescript-eslint/eslint-plugin`, `@typescript-eslint/parser`, `lint` script | No ESLint config anywhere; `npm run lint` cannot work (`docs/DEPLOY.md:49`) | **VERIFIED** | High | no config, no CI step | — | Low | Owner choice: add a config **or** remove | 0 (3 devDeps) | `npm ci`, build |
| FE-23 | `playwright-core` | No direct use; possibly a version pin | LIKELY | Low | 0 refs | `@playwright/test` bundles it | Low | Check lockfile, then remove | 0 | e2e run |
| FE-24 | Capacitor (`@capacitor/*`, `android/`, `ios/`) | Native app shell, last touched 2026-09-08 | RUNTIME | Low | `cap:*` scripts | — | Low | **KEEP** (owner goal: prepare for Android) | — | — |

Also: `e2e/tsconfig.json` asks for `@types/node`, which is not declared in `package.json` (only available indirectly). Add it in S3.

---

## 6. Inventory: ML models, features, training, scoring

**Headline: no REMOVE candidates.** Code that looks orphaned is kept to reproduce signed evidence (protocol docs, the exposure ledger, freeze or hash tests). Reproducibility is a requirement.

| ID | Component | Class | Conf. | Key evidence | Action | Runtime check |
|---|---|---|---|---|---|---|
| ML-01 | `ml/real_question.py` + `ML_REAL_QUESTION_SUFFIX` (off by default) | PROTECTED | High | wired into live buy/exit thresholds: `predict.py:133`, `execution.py:817,937`, `exit_policy.py:65`, `score_history.py:34` | INVESTIGATE, never remove | prod value of the setting (name only); `SELECT name FROM ml_models WHERE name LIKE '%_barrier_cal'` |
| ML-02 | `train.py` random_forest / gradient_boosting / logistic_regression branches (~50 lines) | RUNTIME | Med | CLI + schema only; logistic used by 5 tests | INVESTIGATE; never drop while stored models use it | `SELECT DISTINCT algorithm FROM ml_models` |
| ML-03 | `strategies/sma_crossover.py` | ACTIVE | High | owner benchmark (2026-10-22), `rules_watch.py:44,126` | KEEP | — |
| ML-04 | `strategies/long_term_value.py` | ACTIVE | High | manual-only book; stale "Phase 2 fundamentals" docstring | KEEP; fix docstring; COORDINATE #381 | — |
| ML-05 | `ml/features.py::FEATURE_COLUMNS` (53) + `build_features` | PROTECTED | High | train/serve parity; saved models store their own column list; SX A_53 arm | KEEP | read each stored model's `feature_columns`, compare with `ml_models.n_features` |
| ML-06 | feature helper indicators | ACTIVE | High | all used by `build_features` | KEEP | — |
| ML-07 | `predict.py` grading helpers | PROTECTED | High | write prediction history; two graders on purpose | KEEP; COORDINATE #381, #382 | `/admin/jobs` evaluate runs |
| ML-08 | `predict.py::accuracy_at_horizon` | LIKELY | Med | single caller `api/v1/endpoints/ml.py` | INVESTIGATE | frontend + access log for that route |
| ML-09 | `ml/calibrated_model.CalibratedEstimator` | PROTECTED | High | **pickled inside saved models**; moving it breaks loading | KEEP, never rename | load every active model in a scratch process |
| ML-10 | `ml/backup.py`, `backup_manifest.py` | PROTECTED | High | loaded by file path from `scripts/verify_restore.py` | KEEP | — |
| ML-11 | `ml/registry.py` | PROTECTED | High | live model lifecycle, sha check, atomic publish (#383) | KEEP | — |
| ML-12 | `brain/modules/m06_reason/` (727 lines) | PROTECTED (shadow) | Med | registered module; barrier base model reportedly absent in prod | KEEP; INVESTIGATE whether M06 always says "no opinion" | `brain_meta_v*` presence; M06 mode |
| ML-13 | `brain/score_evidence.py` + JSON | PROTECTED | High | ties score evidence to its model (#377) | KEEP; COORDINATE #381 | — |
| ML-14 | `brain/five_day.py`, `five_day_train.py` | PROTECTED | High | `fd-protocol-v1` tag; must equal the tagged version | KEEP, no edits | — |
| ML-15 | `brain/ten_day.py` (866) | PROTECTED | High | 10D verdict FAILED; reproduces a signed record | KEEP (archive only with owner approval) | `LANE_SHADOW_MODELS`, slots view |
| ML-16 | `shadow_lanes/` (1,521) | ACTIVE (off by flag) | High | scheduler + live read-only endpoint | KEEP; COORDINATE #387 | `LANE_SHADOW_ENABLED` |
| ML-17 | `brain/lanes/h05_*` (12 files, 2,999) | PROTECTED | High | frozen 5-day lane; `h05_cli` is a documented `python -m` entry | KEEP | h05 flag, model sha vs freeze record |
| ML-18 | `brain/selection_lab*.py` (2,120) | PROTECTED | High | `sl-protocol-v1.1`, refuses before 5 Dec | KEEP | — |
| ML-19 | `brain/phase_b*.py` (2,489) | PROTECTED | High | Phase B result tag | KEEP | — |
| ML-20 | SX harness (`sector_walkforward`, `sx_recipe`, `sx_verdict`, `holdout_registry`, … 3,742 lines) | PROTECTED (research) | Med | hash-signed; a test forbids app imports | KEEP | `final_hash_sheet` vs signed hash (offline) |
| ML-21 | `backend/scripts/sector_coverage_report.py`, `sector_reconcile_report.py` (521) | LIKELY | Med | zero references outside scripts; output committed under `docs/brain/evidence/sector_prep/` | ARCHIVE after checking that no SX hash cites them | grep evidence and hash lists |
| ML-22 | `razorpay_create_test_plan.py`, `check_money_coverage.py`, `rehearse_p0_migration.py` | ACTIVE | High | CI and docs | KEEP | — |
| ML-23 | `brain/horizon_grid.py` | PROTECTED | High | private helpers imported across modules | KEEP | — |
| ML-24 | **7+ trade simulators** (five_day, ten_day, horizon_grid, replay_scoring, h05_rules, lane_service, experiments/rules, m09 outcomes) | PROTECTED | Med | each bound to its own protocol hash | INVESTIGATE only, after the freeze and the trial end (S12) | golden-output parity on committed evidence |
| ML-25 | brain replay tools (2,201) | PROTECTED | High | evidence | KEEP; COORDINATE #381 | — |
| ML-26 | evidence tools: bad_market, pause_check, wait_check, ranking_diagnostics, cost_stress, eligibility_report, prediction_reliability, trial_journal (3,762) | PROTECTED | High | each has a PROTOCOL.md or spec | KEEP | `/admin/jobs` weekly eligibility run |
| ML-27 | `brain/trial_constants.py` | ACTIVE | High | breaks import cycle #359 | KEEP | — |
| ML-28 | `brain/modules/m09_learn/` | ACTIVE | High | learning loop, writes outcomes | KEEP; COORDINATE #381 | — |
| ML-29 | CLI brain commands (meta-train, asof-train, strategy-create, shadow-scan, learn) | RUNTIME | Med | DECEMBER-RUNBOOK, replay docs | INVESTIGATE | — |
| ML-30 | `ml/asof.py` | PROTECTED | High | replay scoring | KEEP | — |

---

## 7. Inventory: database tables and jobs

**No table, column or job is VERIFIED UNUSED.** Data may exist in production, so every drop needs a read-only production query first, then a migration, a backup, and your approval.

| ID | Component | Class | Conf. | Evidence (writers / readers) | Action | Read-only check (owner) |
|---|---|---|---|---|---|---|
| DB-01 | `candle_arrivals` | PROTECTED | High | written `ingestion.py:338`; point-in-time evidence | KEEP; maybe add a reader (story S11) | `SELECT count(*), max(first_seen_at) FROM candle_arrivals` |
| DB-03 | `candle_corrections` | PROTECTED | High | audit trail, `ingestion.py:306` | KEEP | count, max |
| DB-04 | `billing_events` | RUNTIME | Med | webhook dedupe log, write-only by design | KEEP | count by provider |
| DB-05 | `admin_recovery_codes` | PROTECTED | High | admin MFA | KEEP | count only, never select hashes |
| DB-06 | `brain_experience` (M05) | RUNTIME | Med | rebuilt cache; M05 may be shadow-only | INVESTIGATE | count, max |
| DB-07 | `finance_*` (7 tables) | RUNTIME | Med | parked Finance; **personal records** | Owner decision S9 | counts and last dates per table |
| DB-09 | `mutual_fund*` (3) + job `sync_mutual_fund_navs` | RUNTIME | Med | parked; job live | Owner decision S9 | `max(nav_date)`, job last run |
| DB-10 | `subscription_plans`, `plan_settings` (old) vs `subscriptions`, `plan_grants` (billing) | RUNTIME | Low | **two plan systems** | Written decision (S10), COORDINATE #379 | `SELECT * FROM plan_settings` |
| DB-11 | `position_score_history`, `stock_score_history` | PROTECTED | High | score history | KEEP, COORDINATE #381 | — |
| DB-12 | `user_watchlist_items`, `user_watchlist_sales` | ACTIVE | High | `my_watchlist.py` | KEEP, COORDINATE #382 | — |
| DB-13 | v1 `Strategy`/`Signal`/`Order` columns | PROTECTED | Low (column audit not done) | v1 trading path | KEEP | per-column `count(col)` before any claim |
| DB-14 | `login_codes` vs `auth_tokens` | ACTIVE | Med | different purposes | KEEP; check expired-code retention | expired-row count |
| DB-15 | `experiment_*` (5) | PROTECTED | High | evidence | KEEP | — |
| DB-16 | `lane_*`, `h05_*` | PROTECTED | High | trial and seal records | KEEP | — |
| DB-17 | 70 migrations | PROTECTED | High | history; single head | KEEP (squash only as a separate study) | `alembic heads` / `current` |
| DB-18 | `capital_deposits` | PROTECTED | High | money ledger | KEEP | — |
| JOB-01 | `daily_market_feeds` ×3 + `company_filings` | ACTIVE | High | one function in 3 slots by design (the last is an alarm) | KEEP | `/admin/jobs` |
| JOB-02 | `check_kite_login` (every 60 s) | ACTIVE | Med | may poll more often than needed | REVIEW interval only | runs per day |
| JOB-03 | `kite_auto_login`, `nag_missing_session` | ACTIVE | Med | | KEEP | — |
| JOB-05 | `h05_daily` | PROTECTED | High | registered only when enabled and the hash is accepted | KEEP | — |
| JOB-06 | `lane_shadow_daily` | PROTECTED | High | gated by flag | KEEP | — |
| JOB-07 | `backup_models` | RUNTIME | Med | **silently does nothing unless `MODEL_BACKUP_DIR` is set** | KEEP; add a visible "skipped" log (S11) | setting present? (name only) |
| JOB-09 | `evaluate_signals`, `evaluate_predictions`, `daily_summary` | PROTECTED | High | prediction history | KEEP | — |
| JOB-10 | `job_brain_strategy` | ACTIVE | High | called inside the nightly path (`jobs.py:733`) | KEEP | — |
| JOB-11 | `sync_mutual_fund_navs` / `score_experiments` | RUNTIME / PROTECTED | Med | | S9 / KEEP | job last runs |

All risk, exit and order jobs are PROTECTED and outside this cleanup: `check_exits`, `reconcile_orders`, `refresh_quotes`, `capture_fills*`, `sync_real_holdings`, `daily_ingest`, `signal_scan`, `predict_watchlist`, `brain_*`, `weekly_paper_report`, `heartbeat`, `server_watch`, `flush_alerts`, `account_deletions`.

Not done by the DB auditor (open, low priority): a column-by-column written-vs-read audit; a review of ~20 raw-SQL files for references to dropped tables; a foreign-key map outside finance, mutual funds, market and billing.

---

## 8. Inventory: infra, config, dependencies, docs

| ID | Component | Class | Conf. | Evidence | Action | Removable |
|---|---|---|---|---|---|---|
| INF-01 | `render.yaml` | LIKELY | High | prod is the DigitalOcean droplet; no workflow uses it | ARCHIVE (owner confirms no Render service is billed) | 116 |
| INF-02 | compose frontend dev target | ACTIVE | High | local dev | KEEP | 0 |
| INF-03 | 204 remote branches | RUNTIME | Low | merge status per branch | Owner prune (separate from code cleanup) | 0 |
| INF-04 | `.github/agents/swing-trading-maintainer.agent.md` | LIKELY | Med | no references; overlaps `AGENTS.md` | ARCHIVE | 47 |
| INF-05/06 | `test.yml`, deploy, staging, secret-scan, dependency-audit, backup, restore-drill, uptime, h05, daily-check workflows | PROTECTED | High | safety and release controls | KEEP | 0 |
| INF-07 | staging seed and config | ACTIVE | Med | `.env.staging.example` says `RAZORPAY_PLAN_ID`; code reads `RAZORPAY_PLAN_ID_PRO_MONTHLY` | Fix the name, **COORDINATE #379** | 1 line |
| INF-08 | `infra/postgres/01-init.sql` | ACTIVE | High | compose mount | KEEP | 0 |
| INF-10 | `arm_row_counts_report.py`, `feature_availability_report.py` | PROTECTED | Med | cited by SX protocol docs | KEEP | 0 |
| INF-11 | `scripts/december/*.ps1` | PROTECTED | High | December runbook + tests | KEEP | 0 |
| CFG-01 | `API_HOST`, `API_PORT` | **VERIFIED** | High | read nowhere; the Dockerfile hard-codes host/port | REMOVE | 4 + `.env.example` |
| CFG-02 | `LIVE_CANDLE_INTERVAL` | **VERIFIED** | High | read nowhere | REMOVE | 2 + `.env.example` |
| CFG-03 | `MAX_OPEN_POSITIONS`, `MAX_POSITION_PCT` settings | LIKELY (corrected) | High | not read by app code (the limits ladder replaced them), **but `test_risk.py` uses `settings.MAX_POSITION_PCT` as its expected value 4 times** | REMOVE only with `review-risk`; rewrite the 4 test expectations to read the limits ladder | ~6 + README row |
| CFG-04 | 24 settings missing from `.env.example` | ACTIVE (docs gap) | High | set-diff | ADD with safe commented defaults + a CI check | 0 |
| CFG-05 | `.env.example` `DATABASE_URL_DOCKER`, `REDIS_URL_DOCKER`, `VITE_API_BASE_URL` | RUNTIME | Med | not checked in compose/vite | INVESTIGATE | — |
| CFG-06 | local default DB URL in `config.py:99` | PROTECTED | High | local dev default only | KEEP | 0 |
| DEP-01 | `backend/requirements-research.lock` | PROTECTED | High | sha256-bound (`sx5_run.py:61`) | KEEP, never regenerate | 0 |
| DEP-02 | `python-multipart` | ACTIVE | High | FastAPI form uploads | KEEP | 0 |
| DEP-03 | `python-dotenv` | LIKELY | Med | 0 imports; pydantic-settings pulls it anyway | optional drop of the explicit pin | 1 line |
| DEP-04 | `psycopg[pool]` extra | LIKELY | Med | 0 `psycopg_pool` imports | optional drop | extra only |
| DEP-05 | `tenacity` | ACTIVE | High | 1 import | KEEP | 0 |
| DEP-06 | `mypy`, `types-requests` | LIKELY | Med | configured, but CI never runs mypy | Owner: run mypy in CI **or** drop | 2 lines |
| DOC-01 | `docs/PROJECT_CONTEXT.md` | LIKELY | High | stale (2026-09-15), says Render | ARCHIVE | 182 |
| DOC-02 | `project_understanding.md` (root) | LIKELY | High | zero inbound links, stale limits | ARCHIVE | 565 |
| DOC-03 | `docs/ROADMAP_TRACKER.md` | LIKELY | Med | superseded by the completion matrix; **CLAUDE.md still points to it** | ARCHIVE + update the pointer (owner OK for CLAUDE.md) | 347 |
| DOC-04 | README "Path to cloud" (`:310-326`) | ACTIVE (stale) | High | recommends S3/GCS, against settled architecture | REFACTOR to a link to `docs/DEPLOY.md` | ~17 |
| DOC-05 | README limits row (`:255`) | ACTIVE (stale) | High | see CFG-03 | fix | 1 |
| DOC-06 | `docs/architecture/CURRENT-STATE.md` | ACTIVE (stale) | High | dated 2026-11-10 at `9deb26a` | refresh | 0 |
| DOC-07 | `docs/ops-digest-DRAFT.md` | ACTIVE (stale label) | High | endpoint is live | drop DRAFT label | 0 |
| DOC-08 | `docs/ai/deferred/*` | PROTECTED | High | owner-deferred items | KEEP | 0 |
| DOC-09 | `*-superseded.md`, `*-DRAFT.md` protocol docs | PROTECTED | High | signed or draft records | KEEP, never remove | 0 |
| DOC-10 | `docs/superpowers/plans/*` (37) | LIKELY | Low | finished vs open not checked | owner picks finished ones → ARCHIVE | up to 37 files |
| DOC-11 | `.codex/config.toml` | PROTECTED | High | Codex review setup | KEEP | 0 |

---

## 9. Duplicate implementations and the canonical one to keep

| # | Duplicate | Keep | Status |
|---|---|---|---|
| 1 | `/admin/release-switches` vs `/admin/console/release-switches` | console (audited, step-up) | remove old now (BE-07) |
| 2 | `/admin/users` + `/plan` (plans.py) vs `/admin/console/users` | console | old still used by PlansManager; migrate first (S10) |
| 3 | `billing.py` admin grants vs console grants | console | runtime check (BE-09) |
| 4 | `/signals/latest` vs `/signals/picks`, `/signals/buy-list` | picks, buy-list | S7 |
| 5 | `/market-data/quote`, `/ltp` vs `/market-data/snapshot` | snapshot | S7 |
| 6 | Manual triggers (`feeds/*`, `refresh-quotes`, `daily-summary`) vs scheduler jobs | jobs | S7 |
| 7 | `require_api_key` vs `deps.require_auth` | `require_auth` | needs `security-review` first |
| 8 | Classic TradeMind pages (Market, Opportunities, Watchlist, StockDetail, Portfolio, Learn, Records, ClassicShell) vs new look | new-look pages (`MarketNew`, `DiscoverNew`, `WatchlistNew`, `StockNew`, `PortfolioNew`, `EvidenceNew`, `HistoryNew`, `NewLookShell`) | S8 |
| 9 | Classic v1 app screens vs TradeMind | TradeMind | depends on Free/Pro plans (S10) |
| 10 | `/instruments/watchlist` (global) vs `/me/watchlist` (per user) | `/me/watchlist` long term | blocked on #382 |
| 11 | `/ml/score-trail` vs `/brain/score-trail` | **both kept**: two different score sources | product decision, not cleanup |
| 12 | Two plan systems (`subscription_plans`/`plan_settings` vs `subscriptions`/`plan_grants`) | billing + entitlement | written decision (S10) |
| 13 | 7+ trade simulators | `brain/replay_scoring.StrictOutcome` for the strict next-open rule | **PROTECTED**: no merge before the freeze ends; golden-output parity first (S12) |
| 14 | 4 scoring variants (`predict.py` prod, `h05_features` lane, `asof` replay, m06 dataset) | all intentional | not duplicates to remove |

---

## 10. Unused dependencies

**Frontend** (`frontend/package.json`, 7 dependencies + 16 devDependencies)

| Package | Verdict |
|---|---|
| `eslint`, `@typescript-eslint/eslint-plugin`, `@typescript-eslint/parser` | **Unused**: there is no ESLint config, so `npm run lint` cannot run. Add a config or remove all three (S3). |
| `playwright-core` | Likely unused (no direct use; `@playwright/test` includes it). Check the lockfile. |
| `@capacitor/core`, `@capacitor/android`, `@capacitor/ios`, `@capacitor/cli` | No imports, but needed by `cap:*` scripts. **Keep** (Android plan). |
| `@types/react`, `@types/react-dom`, `typescript`, `@vitejs/plugin-react`, `vite-plugin-pwa`, `@axe-core/playwright` | Used by tsc, config or e2e. Keep. |
| `@types/node` | **Missing**: needed by `e2e/tsconfig.json`, only present indirectly. Add it. |

**Python** (`backend/pyproject.toml`)

| Package | Verdict |
|---|---|
| `uvicorn`, `python-multipart`, `pytest-asyncio`, `pytest-cov`, `ruff`, `alembic` | 0 imports but used at runtime, as a plugin or by CI. Keep. |
| `python-dotenv` | Likely unused directly (pydantic-settings needs it anyway). Optional. |
| `psycopg[pool]` extra | Likely unused. Optional. |
| `mypy`, `types-requests` | Configured but never run in CI. Run in CI or drop. |
| `casparser`, `pdfplumber`, `python-dateutil` | Used only by the parked Finance module. They go with it if S9 archives Finance. |

---

## 11. Special-attention areas

- **Historical ML models.** No code path in the cleanup touches model files. Three things would silently break old models and are therefore off-limits: renaming or moving `CalibratedEstimator` (ML-09), reordering `FEATURE_COLUMNS` (ML-05), and changing the registry sha handling (ML-11).
- **Training-serving consistency.**
  - The known `obv_slope` skew (models 2/16/17, since 5 Oct) is **noted only; no fix proposed** (inside the sealed trial).
  - One unverified item: the ML auditor reads `predict.py` as picking inputs by each model's stored column list rather than `FEATURE_COLUMNS` order. That matters for the 37- and 46-input models. A read-only check is in section 12.
- **Brain scoring.** The live score is model 2 via `ml/predict.py`; the M06 combiner is shadow-only. The four scoring variants are intentional. Nothing here is removable. `ML_REAL_QUESTION_SUFFIX` (ML-01) is the one setting that could silently change what scores mean; it gets a parity test before anything nearby changes.
- **Stock tracking.** Watchlists, score history, positions and stock identity: all ACTIVE or PROTECTED. Only classic `Watchlist.tsx` (FE-09) and the tiny helper BE-16 are candidates, and both are tagged for coordination with #382.
- **Scheduler jobs.** No job is unused. One gap: `backup_models` silently does nothing when `MODEL_BACKUP_DIR` is unset (JOB-07). That should be made visible, not removed.
- **Safety mechanisms.** All PROTECTED and excluded from every story: risk checks, limits, deployable cap, drawdown halt, trial freeze and seal, paper-mode forcing, test-environment safety (`db_guard`, `_env_safety`), deploy window, secret scan, backup and restore drills, the real-orders badge, the Safety and Settings screens, and the `classic-parity` deletion gate.

---

## 12. Runtime verification checklist (owner-run, read-only)

Production access is your call (AGENTS.md); Codex never queries prod. Claude Code may run the read-only REST checks with your approval. SQL is for you to run on the droplet.

| # | Check | Closes |
|---|---|---|
| R1 | nginx/API access logs, 30–90 days, for: `POST /backtest`, `/market-data/quote`, `/ltp`, `/feeds/*`, `/refresh-quotes`, `/notifications/telegram/daily-summary`, `/signals/latest`, `/admin/users/*/grants`, `/server-watch`, `/research/weekly-report`, `/beginner/evidence`, `/beginner/insights`, `/finance/*`, `/orders*`, and the page paths `/trademind/stock/`, `/brain`, `/models`, `/dashboard`, `/strategies`, `/home` | BE-02..06, 09, 25, FE-14, 16–19 |
| R2 | Confirm the prod frontend build never sets `VITE_CLASSIC_LOOK=on` (repo check: no workflow, compose or Dockerfile sets it; confirm the droplet build env) | FE-07..13 |
| R3 | `/admin/jobs`: last run of every job, especially `sync_mutual_fund_navs`, `backup_models`, the eligibility report, h05, lanes | JOB-07, 11, ML-26 |
| R4 | `SELECT DISTINCT algorithm FROM ml_models`; `SELECT name FROM ml_models WHERE name LIKE '%_barrier_cal'`; whether `brain_meta_v*` model files exist | ML-01, 02, 12 |
| R5 | Setting names present in the droplet `.env` (names only): `ML_REAL_QUESTION_SUFFIX`, `LANE_SHADOW_ENABLED`, `LANE_SHADOW_MODELS`, `MODEL_BACKUP_DIR`, `API_HOST`, `API_PORT`, `LIVE_CANDLE_INTERVAL`, `MAX_OPEN_POSITIONS` | ML-01, 16, JOB-07, CFG-01..03 |
| R6 | Row counts and last dates for `finance_*`, `mutual_fund*`, `plan_settings`, `subscription_plans`, `brain_experience`, `billing_events` | DB-04, 06, 07, 09, 10 |
| R7 | Which plans have the `trademind` feature, and `/status` `brain_enabled` | FE-16, 17 |
| R8 | Offline: load every stored model in a scratch process and confirm inputs are picked by its stored column list | train/serve item, ML-05 |
| R9 | Render dashboard: no active service or billing | INF-01 |

---

## 13. Corrections made during verification

1. **`MAX_POSITION_PCT` was marked VERIFIED UNUSED; that's wrong.** `backend/tests/test_risk.py:29,49,102,150` uses `settings.MAX_POSITION_PCT` as the expected value, so it's now LIKELY UNUSED (test-only) and needs `review-risk`.
2. **BE-08 (`/admin/users`) was first proposed for removal; that's wrong.** `PlansManager.tsx:225,227` calls it, so it's ACTIVE.
3. **`corporate_action_accounting.py` is not legacy.** It's the merged first step of corporate-action accounting (PR #142), so it's ACTIVE (built in stages).
4. **Job count:** 37 max / 35 typical, not 38 or "~32". **Tables:** 84, not "~75".
5. **The `KITE_REDIRECT_URL` "dead code" note in project memory is out of date.** The setting is already gone (`config.py:185` comment).
6. A stale scratchpad merge folder from another session (`…/8a5699f3…/scratchpad/merge-wt`, 1,681 unsaved files, detached) shows up as touching every file. It was excluded from the branch-collision matrix.

---

## 14. Active branches: collision matrix

Checked: all **174 worktrees** (50 hold work not on `main`) and **20 remote branches** ahead of `main`. Every cleanup PR re-checks this list right before it starts.

| Cleanup target | In-progress branches touching it | Rule |
|---|---|---|
| `frontend/src/api/client.ts` (FE-21) | `feature/groww-sync`, `feature/groww-sync-ui`, `fix/353-session-candle`, `fix/ingest-failure-report`, `fix/google-oauth-browser-binding`, `change/account-deletion-ui`, `change/price-snapshot-main`, `change/score-history-brain` | Do last, rebase on `main` after those merge; small edits only |
| `stockParts.tsx` (FE-05) | `fix/5d-plan-honest-levels`, `feature/progress-chain`, `change/score-history-brain` | Wait for the 5D plan fix |
| `StockBrief.tsx` (FE-14) | `fix/5d-plan-honest-levels` | Wait |
| `App.tsx`, `TradeMindApp.tsx` (FE-13, 16–19) | `change/account-deletion-ui`, `change/closed-trades-pnl` | Wait |
| `market_data.py` (BE-03, 04) | `change/price-snapshot-main` | Wait or coordinate |
| `services/ingestion.py` (BE-14) | `fix/353-session-candle`, `fix/ingest-failure-report` (candle stack) | Do after the candle stack merges |
| `schemas/__init__.py` (BE-19) | `fix/353-session-candle`, `fix/353-stale-candle`, `fix/status-book-privacy`, `change/price-snapshot-main` | Do after those merge |
| `core/config.py`, `.env.example` (CFG-*) | `feature/groww-sync(-ui)`, `fix/353-session-candle`, `fix/candle-readiness-scan`, `fix/ingest-failure-report`, `change/brain-enabled-default-on` | Do after those merge |
| `README.md` (DOC-04, 05) | `check/sx-full-suite`, `rc/combined` | Low conflict; rebase |
| Docs to archive, orphan frontend files, `release_switches.py`, dead helpers in `finance/`, `model_registry.py`, `core/enums.py`, `watchlist_snapshots.py` | none | Free to start |

### Coordination with #379, #381, #382 (planned, not started)

| Feature | Cleanup items to hold back |
|---|---|
| #379 fictional trial identities | BE-09 billing grants, BE-21 release switches, DB-10 plan systems, INF-07 staging Razorpay name |
| #381 holding guidance | FE-11 classic Portfolio, BE-13 corporate actions, ML-04, 07, 13, 25, 28, DB-11 score history |
| #382 favourite-stock analysis | FE-09 classic Watchlist, BE-16, BE-24 global watchlist, DB-12, ML-07 |

---

## 15. Cleanup stories (proposed, under #392)

GitHub sub-issues of #392 (created 2026-11-21, all **proposed**): S0 #393 · S1 #394 · S2 #395 · S3 #396 · S4 #397 · S5 #398 · S6 #399 · S7 #400 · S8 #401 · S9 #402 · S10 #403 · S11 #404 · S12 #405.

Each story gets **one worktree, one branch, one PR**, a full regression run, a Codex review, and your approval before `main`. Rollback for every code story is `git revert` of its single PR; extra steps are listed where needed.

| Story | Scope | Risk | Owner | Ready? | Regression tests | Rollback |
|---|---|---|---|---|---|---|
| **S1** Backend dead helpers and duplicate route | BE-07, 14, 15, 16, 17, 18, 19 | Low | backend | BE-07/15/17/18 now; BE-14/19 after the candle stack merges | full backend suite; route-list test; `test_admin_step_up_gate` | revert |
| **S2** Frontend orphans and dead client functions | FE-01..04, FE-06, FE-21 (non-finance members) | Low | frontend | orphans now; `client.ts` trim last | `tsc --noEmit`, vitest, `npm run build`, e2e, `classic-parity --check` | revert |
| **S3** Frontend tooling | FE-22 (add ESLint config **or** remove 3 packages; your choice), FE-23, add `@types/node` | Low | frontend | after your choice | `npm ci`, build, e2e | revert + lockfile |
| **S4** Docs archive and accuracy | INF-01, INF-04, DOC-01..07, DOC-10 (your pick), ML-21 (after hash check), ML-04 docstring, `docs/brain/evidence/INDEX.md` mapping evidence-only modules to their protocols | Low | docs | now (CLAUDE.md pointer needs your OK) | `git diff --check`, CI; no protocol/evidence doc touched | revert (files move to `docs/archive/`, nothing deleted) |
| **S5** Dead settings and `.env.example` completeness | CFG-01, 02, 03, 04, DOC-05, INF-07 | Low–Med (CFG-03 sits next to risk limits → `review-risk`) | backend | after the config branches merge; INF-07 with #379 | settings tests, `test_risk.py` rewritten to use the limits ladder, docker build, new CI check that every setting is in `.env.example` | revert; droplet `.env` untouched |
| **S6** Python dev dependency tidy | DEP-03, 04, 06 (mypy decision) | Low | platform | after your mypy decision | `pip check`, docker build, DB tests | revert |
| **S7** Unused backend routes | BE-02..06 (+ FE `latestSignals`) | Med | backend | **after R1 access logs** | backend suite, route-absent tests, job tests | revert (routes return) |
| **S8** Retire the hidden Classic TradeMind look | FE-07..14, ClassicShell, then the `VITE_CLASSIC_LOOK` test switch; decide `/beginner/evidence`, `/beginner/insights` | Med | frontend + your sign-off | **after R1/R2, after #381, #382 and the 5D plan fix land** | `classic-parity --strict`, tsc, vitest, e2e (rewrite classic-gated specs), build, browser check | revert; or set `CLASSIC_LOOK_IN_CODE` back (until the shell is removed) |
| **S9** Parked Finance and mutual funds | BE-22, 23, DB-07, 09, FE-18, FE-21 finance members, job `sync_mutual_fund_navs`, `casparser`/`pdfplumber` | High (personal data) | **your decision first**: keep parked / archive / restore | decision + R1, R3, R6 | backend + frontend suites; if archiving: stop job → remove route → separate drop migration with a clean-upgrade and single-head drill | job/route: revert; tables: migration downgrade **plus restore from the pre-drop backup** (export taken before) |
| **S10** Classic v1 app and plan systems | FE-16, 17, 19b, BE-08 (move PlansManager to the admin console), DB-10 | High | **your decision**, linked to Free/Pro #335 | after R7 + #335 | parity allowlist, full suites | revert |
| **S11** Make silent gaps visible (no removals) | JOB-07 skipped-backup log line, JOB-02 interval review, reader/report for `candle_arrivals`, `candle_corrections`, `billing_events` | Low | ops | now | job tests | revert |
| **S12** Trade-simulator consolidation (design only) | ML-24 | Protected | design + Codex review | **not before the 4 Dec freeze lifts and the sealed trial ends** | golden-output parity on every protocol's committed evidence | n/a (design doc) |
| **S0** Runtime fact-finding (investigation) | the R1–R9 checklist | none | you + Claude (read-only, with approval) | when you approve production read access | — | — |

**Not scheduled:** every PROTECTED item (ML-05, 09, 11, 14, 17, 18, 19, 20, the evidence tables, migrations, safety mechanisms).

---

## 16. Expected benefits

- **Maintenance.**
  - S1–S5 remove about 2,300 lines of code that is certainly or very probably dead, plus ~1,300 lines of stale docs.
  - S8–S10, if approved, remove up to ~12,500 more and **end the double maintenance of Classic and new-look screens**. Today, display fixes such as the 5-day plan change have to touch both the classic Swing Picks screen and the new look.
- **Performance.**
  - No lazy loading is used, so every hidden Classic page and the parked Finance page (~9,000 lines of frontend) **ship in the production bundle**. S8–S10 would shrink it and speed up the first page load, especially on phones.
  - Backend gains are small: fewer routes and one fewer daily job (NAV sync) if Finance is archived.
- **AI context efficiency.**
  - Stale docs (`PROJECT_CONTEXT.md`, `project_understanding.md`, `ROADMAP_TRACKER.md`, README "Path to cloud", an outdated `CURRENT-STATE.md`) actively **contradict** the current setup: Render vs the droplet, old limits, S3. Agents that read them make wrong assumptions.
  - Duplicate page names (`Watchlist` vs `WatchlistNew`, two `Dashboard.tsx`, two `Positions.tsx`) cause agents to edit the wrong file.
  - The proposed `docs/brain/evidence/INDEX.md` lets agents see at once that an "unused" research module is protected evidence, which saves repeat audits like this one.
- **Safety.** No story touches risk limits, order placement, sizing, stops, the trial seal, evidence or model files. The one setting next to limits (CFG-03) goes through `review-risk`.

---

## 17. Related: the four idle Claude sessions (2026-11-21)

All four are idle because each finished its last reply and is **waiting for the owner**, not stuck. None was stopped and none of their changes were touched.

| Session | Folder / branch | Unfinished work |
|---|---|---|
| Local server (started ~18:29 IST) | main checkout; server runs `main` `40bf4b0` | Local site **:5174**, API **:8001**, DB `swing_trade_ml_view`. It also prepared a **worktree/branch cleanup script** (150 clean worktrees, ~174 merged branches). Auto-mode blocked it and it waits for the owner. It works from a fixed list made before `legacy-inventory-wt` existed, and keeps dirty worktrees and `feature/groww-sync`. |
| Codex setup (~18:35 IST) | main checkout | Done: Codex now uses `gpt-6.2-sol` (backup of the old config saved). |
| 5-day plan fix (~17:27 IST) | `five-day-plan-wt`, `fix/5d-plan-honest-levels` | Steps 1–2 built, **28 files not committed**; #391 opened; waiting for Codex review and owner approval. |
| Groww sync (started 20 Nov) | `.claude/worktrees/groww-sync`, `feature/groww-sync` | #388 phase 1, **12 commits only on this PC, never pushed**; waiting for the owner's local check. |

The disk-folder cleanup above is separate from #392. If the owner runs it, it should run **before** #392 cleanup worktrees are created.
