# TradeMind: Target Architecture and GitHub Alignment Proposal

Status: **Proposed. Steps 0-1 (section 11) approved by the owner on 2026-11-22; Steps 2-3 and database changes await the owner.** Several items have since been built (see the table below the header). Nothing in here is built unless it says "exists today". Decisions are recorded in ADR-002 to ADR-005 (index: `docs/decisions/README.md`); permanent rules are in `CLAUDE.md` and `AGENTS.md`.
Date: 2026-11-21. Code snapshot: `main` at `b9a92ea` (includes the #392 cleanup PRs #406, #408–#412).
Evidence: five read-only audits (frontend, backend, Brain/ML, data, GitHub board), with key claims re-checked by the lead against `main`. File:line references point at `backend/src/swing_trade_ml/` or `frontend/src/` unless written in full.

> **Where this stands on `main` (checked 2026-11-26 against `origin/main` `897da86`).** The text below is the proposal as
> it was written on 2026-11-21 and approved in part on 2026-11-22. Where the text says "planned" or "does not exist",
> this table wins. Verified facts only; each row names the file.
>
> | Item | State on `main` | Evidence |
> |---|---|---|
> | M1 import-direction and router-protection tests | **Built** (#413, PR #467) | `backend/tests/test_module_boundaries.py:1` (layering, product-to-product imports, every router classified) |
> | M2 module registry and lifecycle | **Built** (#291, PRs #453, #457, #460): 4 core and 4 optional modules; routes refused by `require_module`, jobs left out by `apply_to_scheduler`; durable owner-only switch `PUT /admin/modules/{id}`, audited | `core/modules.py:102` (`REGISTRY`), `core/modules.py:412` (`require_module`), `core/modules.py:430`, `api/v1/endpoints/brain.py:236`, migration `20261124_1400_module_switches.py` |
> | Plans reach modules (first slice of M3, #335, PR #458) | **Built**: a plan must hold every feature a module names in `Module.capabilities`; a module naming none is owner-only | `core/capabilities.py:20` (`plan_may_use_module`), `api/module_capability.py:20` |
> | M3 capability registry (`require_capability`, `/me/capabilities`, overrides, admin plan maps) | **Not built.** Today's switches stay five separate mechanisms (plan FEATURES and `ROUTE_RULES` in `core/plans.py`, release switches, environment flags, role checks) plus the module registry above | `core/plans.py:33`, `core/plans.py:118`, `core/release_switches.py:37` |
> | M4 stock identity (#389) | **Built, phase 1**: `securities`, `security_symbols`, `security_aliases` (alias history); one resolver `resolve(db, symbol=, isin=, token=, exchange=, on_date=)`; read contract pinned by a test | `db/models/identity.py:48`, `services/identity/__init__.py:166`, `docs/architecture/IDENTITY-READ-API.md`, `tests/test_identity_read_contract.py` |
> | M5 append-only `score_ledger` | **Built**: UPDATE, DELETE and TRUNCATE refused by database triggers; `horizon_records` also keys on `security_id` | `db/models/identity.py:96` (`ScoreLedger`), migration `20261123_1200_identity_phase1.py:25`, `db/models/horizon.py:45` |
> | M6 versioned research config | **Built as code, not as database rows**: immutable versions with a hash, `ACTIVE_VERSION`, no environment or database edit. The `research_config_versions` table and an Admin version selector do not exist | `core/research_config.py:75` |
> | M7 rule numbers from the backend | **Built** (#416): `GET /config/trading-rules`; the owner and shared key also get the research-only horizons | `api/v1/endpoints/system.py:236`, `services/trading_rules.py:24`, `frontend/src/trademind/noHardcodedRules.test.ts` |
> | M8 one metrics module, M9 audit on halt/resume, M10 tenant-isolation tests | Not checked for this update. Treat as **proposed** until a PR and test are named | none |
> | Owner-approval gate on sensitive files | **Built** (#527, #543): a PR touching a listed path gets an "Owner approval" box only the owner ticks | `.github/scripts/owner_gate.py:27` (`SENSITIVE`) |
> | Merge and deploy | **Separate**: merging never deploys; deploy is a manual workflow run (#439, #441) | `docs/DEPLOY.md` |
>
> **Name clash to resolve before M3 is built.** The proposal and ADR-003 name the future capability registry
> `core/capabilities.py`, but that file already exists and holds only `plan_may_use_module` (#335). The registry needs
> a different file name, or the existing function moves into it. This is a lead decision, not yet taken.
>
> **Where a new feature goes, and how it is switched on (today).** (1) Put its code under one module's packages and
> declare the module in `REGISTRY` (`core/modules.py`) with its route prefixes, job ids, `depends_on` and the plan
> features it needs in `capabilities`. (2) Mount its router in `api/v1/router.py` with `optional("<module id>")`
> (`api/v1/router.py:104`), or behind `protected` if it is core; `tests/test_module_boundaries.py` fails a router that is neither.
> (3) Its on/off state is the module switch (owner, Admin "Parts of the app"); who may use it is `core/plans.py`
> (Free/Pro features) checked twice, by the plan gate and by `module_capability`. (4) A customer-facing release gate
> that must start off uses a release switch (`core/release_switches.py`). (5) Rule numbers come from
> `/config/trading-rules`, never typed into the frontend. (6) A new table that names a stock stores `security_id`
> (`services/identity`), and a new score row is appended to the ledger, never updated. Risk, sizing, exits, live-trading
> guards and the trial freeze are protected: they have no switch and change only by code, test and owner sign-off.

---

## 0. The recommendation in ten lines

1. **Keep one application and evolve it in place.** It is a modular monolith today (one FastAPI app, Postgres/Timescale, Redis, APScheduler). That's the right shape for one owner and up to six agents. **No microservices, no event bus, no rewrite, no separate "v2".**
2. Make the module boundaries **real and enforced**: a small module registry plus automatic import-direction tests. Today the boundaries exist only by convention, and they are already broken in four places.
3. Replace the **five separate on/off mechanisms** with **one capability registry**: code-defined IDs; values from defaults, environment, admin overrides and plan entitlements; checked by the backend.
4. Give every stock **one ID** (#389). Give every score, signal and decision **its model, configuration and code version**. Stop overwriting score history.
5. Put trading-rule and research numbers in **one versioned place**. Today about 20 copies of +8%/−4% exist across the backend and about 8 in the frontend.
6. The frontend becomes **presentation only**: one set of colour tokens, rule numbers and totals served by the backend, a typed API layer, and lazy loading for owner and admin screens.
7. Portfolio becomes **one holdings view with a source column**, and Groww becomes the first provider behind a small adapter (the billing adapter is the model). No seventh portfolio schema.
8. Reports share **one metrics module** (today "P&L" is defined four ways).
9. Prove all of it on **Discover, Groww Tracker, Reports and Admin** before broad feature work resumes.
10. **Start with two or three developers on the core**, not five. Core work touches shared files; parallelism comes once boundaries exist.

The ~6-week dev freeze, the trial-frozen files (`backend/tests/trial_freeze.json`, 98 files) and the signed protocols are respected. Everything in "MUST HAVE NOW" is **additive** (new modules, nullable columns, tests) or touches non-frozen files. The three brain correctness fixes are flagged separately for owner approval.

---

## 1. Development clearance and handover status (2026-11-21, 22:00 IST)

| Item | State |
|---|---|
| #392 legacy cleanup | Inventory, S1, S2, S3 (ESLint), S4 and the worktree tool **merged** (PRs #406, #408–#412). The production deploy of `b9a92ea` was running at the time of writing. |
| S11 visible gaps (#404) | Built on `cleanup/s11-visible-gaps` (2 commits); suite and independent review pending; lands after the candle stack (shared `workers/jobs.py`). |
| Candle stack #316 → #357 → #353 | Codex-reviewed, uncommitted. Developer-1 is committing and rebasing. **#353 needs the owner to run `approve_trial_change.py` for `engine.py`.** |
| 5-day plan fix | 28 files, backed up and locked. Developer-2 is committing, rebasing and testing. |
| #387 three-horizon workflows | Pure package, unwired. Developer-4 is committing and rebasing. DB and nightly-job plan **not approved**. |
| #388 Groww sync | 12 commits **only on this PC**, owned by another active Claude session (browser testing now). Backed up as a bundle. **Not touched.** |
| #386 progress chain | Developer-5 is doing a read-only status check. |
| Worktrees | 180 audited (dry run): 115 eligible for quarantine. Merged ones (inventory, S1, S4) are quarantined, nothing deleted. |
| New feature work | **Stopped** when this was written (2026-11-21), until the owner decided on the proposal. Steps 0-1 were approved on 2026-11-22; Steps 2-3 and database changes await the owner. |

**Blockers for the owner:**
- the trial-freeze approval for #353
- Groww sync is local-only; push or land it soon
- developer sessions can't run `git commit` (the permission system blocks it), so every story needs the lead to commit

---

## 2. Current architecture (exists today, with evidence)

```
                 React/Vite SPA (frontend/src, ~50K lines, one bundle, no lazy loading)
                 ├─ New look /trademind/* (live)      ├─ Classic look (hidden but shipped)
                 ├─ legacy v1 shell App.tsx SCREENS   └─ api/client.ts: 1 object, ~216 methods; types.ts 2,128 lines hand-written
                                     │  HTTPS + JWT / X-API-Key / scoped service keys
┌────────────────────────── FastAPI app (one process; scheduler runs inside it) ──────────────────────────┐
│ api/v1/endpoints (46 routers; require_auth default-deny + owner prefixes, api/deps.py:200-336)            │
│ services/ (116 files): ingestion · scanning/engine · execution/risk/limits (frozen) · portfolio/real/     │
│   tester/watchlist-tracker · reports · brain support · admin/auth/billing/plans · finance (parked)        │
│ brain/ (131 files): modules M01–M18 pure run(view)->Contribution, contracts.py, fallbacks, lanes/h05,     │
│   research tools (five_day, ten_day, selection_lab, phase_b, replay…)                                     │
│ ml/ (features 53 inputs, train, predict, registry) · strategies/ (frozen) · shadow_lanes/ · brokers/      │
│ workers/scheduler.py + jobs.py (~35 jobs, 37 max) · core/ (config ~123 settings, release_switches, plans) │
└───────────────┬─────────────────────────────┬──────────────────────────────┬──────────────────────────┘
          PostgreSQL+Timescale (84 tables,  Redis (5 small uses: rate limits,   External: Kite (adapter),
          70 migrations, single head)       error watch, job runs; no cache)    NSE/AMFI scrapers, Telegram,
                                                                                Razorpay (adapter), Resend, Google
```

**What is already good and must be reused:**
- Brain modules have real contracts and run modes (`brain/contracts.py`, `brain/module.py`), with caution-only downgrades.
- Model registry with atomic publish, sha checks and advisory locks (`ml/registry.py`).
- Append-only evidence tables enforced by DB triggers (h05, shadow lanes).
- Server-side default-deny authorization, plus route-coverage tests. **The old note "owner-only not server-enforced" is out of date for the API.**
- Admin MFA with step-up; an `audit_log` with secret redaction.
- Billing's `Protocol` plus a fake adapter (the pattern for every integration).
- `PageState` loading/error/empty rules; `ui.tsx` shared primitives (~65 importers); react-query everywhere.
- Scheduler adders for optional modules (brain, h05, lanes) that disappear cleanly when off.
- The `classic-parity` deletion gate; the worktree lifecycle tool.

---

## 3. Architectural gaps and technical risks (verified)

| # | Gap | Evidence | Risk |
|---|---|---|---|
| G1 | **Boundaries not enforced**: `services` imports `api` in 4 places; `services` ↔ `brain` import cycle (45 / 34 statements) | `services/beginner_views.py:376`, `ops_digest.py:174`, `plans.py:27`, `tester_paper.py:265` | Every refactor can break unrelated modules; agents keep adding cross-links |
| G2 | **5+ on/off mechanisms, no registry**: env settings, 5 release switches (env-only, read-only), plan features (DB), billing entitlements (DB), per-lane settings | `core/config.py`, `core/release_switches.py`, `core/plans.py`, `services/billing/entitlement.py`, `brain/lanes/h05_protocol.py` | Can't answer "what is on, for whom" in one place; the `customer_screens` switch is enforced nowhere |
| G3 | **No authoritative security ID**: no ISIN anywhere; ~20 tables key on a bare symbol string | `brain_decisions.symbol`, `user_watchlist_items.symbol`, `broker_fills.symbol`, `lane_picks.symbol`… | A rename or merger orphans history; Groww, Discover and Reports can't be joined reliably |
| G4 | **Score and decision identity**: brain runs and decisions store no model, config or code version; `stock_score_history` keyed by model *name* and overwritten on same-day rescan; `predictions` upserted and CASCADE-deleted with the model | `db/models/brain.py:68`, `trading.py:445`, `services/score_history.py:205-218`, `db/models/ml.py:117` | "Historical scores never overwritten" is **false** for product tables; evidence can be lost |
| G5 | **Research and trading numbers scattered**: ~20 backend copies of +8%/−4%/15d, ~8 frontend copies; `SCORE_LINE` 0.80 defined twice | `brain/fallbacks.py:26`, `m08_decide/policy.py:15`, `positionLevels.ts:4`, `trackerRules.ts:93`… | A rule change silently leaves stale numbers; screens contradict each other |
| G6 | **Brain score vs plan mismatch**: the brain always scores with `swing_classifier` (5-day model) but states a +8%/−4%/15-day plan | `brain/reader.py:42,470`, `brain/fallbacks.py:26-27,225-231` (trial-frozen) | Honesty and trial meaning. Owner decision |
| G7 | **Feature identity is names-only**: the obv_slope formula changed under the same name; serving is skewed vs training for models 2/16/17 | `m02_perception/snapshot.py:35`, `ml/features.py:300` vs `lanes/h05_features.py:49` | The same class of silent bug can recur |
| G8 | **Artifact check only at activation**: serving loads unchecked and caches forever; `ALLOW_MODEL_PROMOTION` is checked at the API/CLI edge, not at `activate_model` | `ml/predict.py:44-51`, `brain/reader.py:431`, `ml/train.py:429` | A swapped file, or a new code path, bypasses the guard |
| G9 | **Frontend computes business numbers**: trading-day counter with a hand-written holiday list; money totals; stop/target states | `wave3Rules.ts:18-66`, `trackerRules.ts:262`, `pages/positionLevels.ts:28` | Screens disagree with the backend; calendar errors |
| G10 | **Design tokens in three overlapping sets**, 778 inline styles, 89 hex colours in `.tsx`, no dark mode for the new look | `styles.css:4-15`, `newlook.css:6-26`, `trademind.css` | Every restyle is a hunt across many files |
| G11 | **Portfolio: six concepts, no common holding model, no source column**; positions/orders/trades have no `user_id` | `db/models/trading.py`, `user_watchlist.py` | Groww sync would add a 7th schema; multi-user portfolios impossible without a decision |
| G12 | **"P&L" defined four ways**; some reports load whole tables into Python | `services/real_report.py:118`, `weekly_paper_report.py:69`, `api/v1/endpoints/portfolio.py:971`, observatory | Numbers disagree between screens; per-user reports won't scale |
| G13 | **Admin audit gaps**: `/safety/halt` and brain stage changes are not in `audit_log` | `api/v1/endpoints/safety.py`; `brain_stage_changes` table | No single admin trail |
| G14 | **Outbound HTTP resilience**: retries only in Kite; NSE feeds scrape unofficial endpoints | `brokers/kite.py:534`; `services/market_feeds.py:41-51` | Stale data |
| G15 | **Router protection is tested for classification only**: `test_every_route_is_classified` fails any mounted route that has no auth and is on no allow-list, but nothing calls each owner-only route as each kind of caller, so an owner-only route a non-owner can still reach is not caught | `backend/tests/test_plans_route_coverage.py:150` (classification); `api/v1/router.py` (mounting) | Security regression risk: a route's class is checked, not its behaviour per caller (#426) |

---

## 4. Alternatives considered

| Approach | Verdict | Why |
|---|---|---|
| Existing architecture + incremental improvements | **Selected as the base** | It already is a modular monolith with good pieces; the gaps are consistency and enforcement, not shape |
| **Modular monolith** (explicit modules, registry, enforced import rules) | **Selected** | Gives feature independence and safe removal with zero new infrastructure; fits one owner and ~6 agents |
| Domain-oriented structure | **Selected, lightly** | Group code by domain (market data, intelligence, portfolio, reports, accounts, admin) through the module registry and package ownership, **without** moving 400 files. Moves happen only when a file is touched anyway |
| Clean/Hexagonal | **Only at the edges** | Ports and adapters for brokers, holdings providers, billing, notifications and market feeds (the billing pattern). Not for internal services: it would double the code for no gain |
| Event-driven | **Not now** | APScheduler plus the existing DB outbox (`alert_outbox`) are enough. A bus adds infrastructure and ops for one owner. Revisit only if a real fan-out need appears |
| Microservices | **Not recommended** | Settled principle #1; ops cost, distributed transactions, and nothing in the workload needs it |
| Separate "v2" codebase | **Rejected** | Double maintenance; production and evidence live on `main`; the parked `v2` branch and the Classic/New split show the cost |

---

## 5. Target architecture

```
Frontend (presentation only)
  design tokens (1 file) → shared components (StockCard, ScoreChart, DataTable, FilterBar, PageState)
  → domain hooks (useDiscover, useHoldings, useReport…) → typed API client split by domain (query-key factory)
  → screens/layouts (restyle = change here only). No business numbers computed client-side.
                                   │  /api/v1 (versioned contracts; OpenAPI → generated TS types)
Backend: ONE FastAPI app, modules declared in core/modules.py
  ┌ Core (always on; never imports optional modules) ───────────────────────────────────────────────┐
  │ identity (securities/instruments, #389) · capabilities & entitlements · research config versions │
  │ market data & quality · scoring/registry/model cards · audit · scheduler · metrics (one P&L)    │
  └──────────────────────────────────────────────────────────────────────────────────────────────────┘
  ┌ Product modules (optional; each = routes + services + jobs + capabilities + tests; can be off) ┐
  │ discover · today · watchlist · groww-tracker · portfolio · reports · admin console · brain views │
  │ research lanes (h05, 10/15D) · experiments · finance (parked)                                   │
  └──────────────────────────────────────────────────────────────────────────────────────────────────┘
  ┌ Protected (code + owner sign-off only; never admin-editable) ┐  ┌ Adapters (ports) ───────────────┐
  │ risk/limits/exits/execution · trial freeze & seal ·          │  │ BrokerPort (Kite, Paper)          │
  │ paper-mode latches · live-trading guards · frozen protocols  │  │ HoldingsProvider (Groww, …)       │
  └──────────────────────────────────────────────────────────────┘  │ BillingProvider · Notifier · Feed │
                                                                    └───────────────────────────────────┘
PostgreSQL (authoritative) · Redis (rate limits, job runs, measured caches with namespaced keys) · APScheduler
```

**Dependency rules, enforced by tests:**
- `core` ← product modules ← `api`
- `brain` modules read only through `DatedReader`
- `services` never import `api`
- product modules never import each other's internals; they use core services or published functions
- adapters are reached only through their port

---

## 6. Module dependency and data/cache ownership

| Module (state) | Owns tables | Reads (through core) | Jobs | Capabilities | Redis |
|---|---|---|---|---|---|
| core.identity (active) | instruments, **securities (new, #389)**, aliases | — | sync_instruments | — | — |
| core.marketdata (active) | candles, quotes, feeds, corporate_actions | identity | daily_ingest, feeds | — | — |
| core.intelligence (active, partly frozen) | ml_models, predictions, signals, stock_score_history, **score_ledger (new)**, brain_* | identity, marketdata | signal_scan, predict, brain_* | `brain.view` | — |
| core.capabilities (new) | **capability_overrides, plan_capabilities (new)**, plan_settings, subscriptions, plan_grants | — | — | defines all | cached map, 60s, per role/plan |
| core.audit (active) | audit_log | — | — | — | — |
| discover / today (active) | none (read models) | intelligence, identity | — | `discover.view`, `today.view`, `history.scores` | optional report cache |
| watchlist / groww-tracker (active) | user_watchlist_items/sales (+ `security_id`), **holding_sources (new, #388)** | identity, intelligence | groww_sync (#388) | `watchlist.*`, `groww.*` | — |
| portfolio (active) | positions, orders, trades, snapshots, capital (frozen execution) | identity, metrics | check_exits… (protected) | `portfolio.view` | — |
| reports (active) | none, or summary tables only when measured | metrics, identity | weekly report | `reports.*`, `reports.export` | `rpt:{report}:{filters-hash}:{plan}` |
| research lanes (active / parked) | h05_*, lane_* (append-only) | intelligence | h05_daily, lane_shadow | owner only | — |
| finance (parked) | finance_*, mutual_fund_* | — | sync_mutual_fund_navs (still runs) | owner only | — |

**Redis conventions (new, small):**
- One helper `cache_key(namespace, *parts, user=None, plan=None)`.
- Prefix `stml:`.
- Every key carries a TTL.
- No per-user data without a user segment.
- On failure, fall back to Postgres.
- Cache only after measuring.

---

## 7. Admin configuration and entitlement design

**Three tiers. Never mixed:**

| Tier | Examples | Changed by | Storage | Audit / rollback |
|---|---|---|---|---|
| **Product config** | module on/off (optional modules), tab/section visibility, Free/Pro capability map, new plans, display filters, report options, stock-universe lists for display | Owner in Admin (MFA step-up) | `capability_overrides`, `plan_capabilities`, existing `subscription_plans`/`plan_grants` | `audit_log` row per change; previous value restorable |
| **Research config (versioned)** | horizons offered, simulation target/stop for research views, score lines, evaluation criteria | Owner approves a **new version**; active version selected in Admin | `research_config_versions` (immutable rows + hash) | Old versions never edited; every score row records the version it used |
| **Protected safeguards** | risk limits, sizing, exits, live-trading latches, trial freeze, frozen protocol constants, real-orders guards | **Code + test + owner sign-off only** (`review-risk`) | code / env | git history; never in Admin |

**One capability registry** (proposed; not built, and `core/capabilities.py` is already taken, see the name-clash note under the header):
- Stable IDs such as `discover.view`, `history.scores`, `reports.export`, `ai.analysis`, `groww.sync`.
- Each ID carries: module, default, `protected: bool`, the plans it is allowed for, and a description.
- The value is resolved in this order:
  1. code default
  2. environment value (deploy-level kill switch)
  3. admin override (global on/off)
  4. plan entitlement (Free/Pro/future)
  5. role (owner, tester, member)
- Layers 1 and 2 are the **deployment layer**: the environment value, when set, replaces the code default (the
  default is only the fallback). So a release switch that is off by default and enabled by the deployment
  environment (for example `ALLOW_MODEL_PROMOTION`) is on at this layer, exactly as today. From layer 3 on, each
  layer can only narrow: an admin override, plan or role never widens what the deployment layer denies, and a
  `protected` capability cannot be turned on by an override. Details in ADR-003.
- A module switch controls only the module's own routes, jobs and menu. **Protected jobs always stay
  scheduled** (`check_exits` and the other jobs the post-deploy check requires: `reconcile_orders`,
  `signal_scan`, `heartbeat`; see `infra/deploy/verify.py`). No module, capability or admin setting removes
  them, and the module lifecycle test asserts they are still scheduled with every optional module off.
- The backend checks it with `require_capability("…")` on routes, and in jobs where relevant.
- `/me/capabilities` returns the resolved map. The frontend only hides things; **the backend enforces them**.
- The existing `core/plans.py` FEATURES list, `ROUTE_RULES` and `release_switches` **become entries in this registry**. They are migrated, not deleted, so existing behaviour is preserved.

**Where the owner's requirements are challenged:**
- "Configure horizons and models from Admin": **only the choice between already validated, versioned options.** Changing a model's target or horizon means retraining plus evaluation under a protocol. It's a code and evidence change, not a toggle.
- "Admin configures everything": no. Safety and trading rules stay protected, by design.

---

## 8. Future-change stress test

Legend: **Code?** = code change needed · **Admin?** = an admin change is enough · **DB/Cache?** = schema/cache change needed.

| Scenario | Modules that change | Unaffected | Code? | Admin? | DB/Cache? | Reused | Verified by |
|---|---|---|---|---|---|---|---|
| 1. Redesign Discover | frontend Discover screen + shared components | all backend, other screens | Yes (frontend only) | No | No | domain hooks, tokens, StockCard | Playwright Discover journey, visual check, API contract test unchanged |
| 2. New dashboard / optional module | new module folder (routes, service, jobs, capability IDs), one registry entry, new screen | core, other modules | Yes | Then on/off via Admin | Only if it owns data (migration review) | core services, components | module boundary test, capability tests, module on/off test |
| 3. Disable a module | none | everything else | No | **Yes** (module off → routes 403/404, the module's own jobs not registered, menu hidden; **protected jobs always stay scheduled**) | No (data kept) | registry, scheduler adders | lifecycle test: off → routes refused, the module's own jobs absent, the protected jobs still scheduled, other suites green |
| 3b. Remove a module | module folder, registry entry | data stays (state `retired`) | Yes | — | No drops without a separate approved migration | dependency map | boundary test proves no importers; regression suite |
| 4. Change Free/Pro capabilities | none | — | No | **Yes** (plan_capabilities) | No | capability registry | entitlement matrix test (each plan × capability → allowed/denied, server-side) |
| 5. New subscription plan | none (if it only reuses existing capabilities) | — | No | **Yes** (new plan row + map) | No | billing, entitlements | same matrix test with the new plan |
| 6. Change research/simulation config | none for an existing option | protected trading rules | No (new **version** approved) | Select the active version | New version row | research config versions | version recorded on new scores; old reports still show old versions; never mixed |
| 7. Model or horizon performing badly | candidate model trained in a lane | product modules | Training code only if the recipe is new | Promotion is a recorded owner action | New registry row; lane rows | registry, model cards, h05/shadow lanes, challenger report | same-rows champion/challenger report; promotion audit row |
| 8. Add a research horizon | lane + slot config, model training | product screens (they read capabilities and registry) | Yes (lane, label recipe) | Show it when validated | Lane rows | lane infrastructure, `services/lane_slots.py` | lane tests, protocol hash, horizon capability test |
| 9. Replace a portfolio provider | new adapter behind `HoldingsProvider` | holdings view, reports, UI | Yes (adapter only) | Switch provider on/off | `holding_sources` rows only | port, idempotent sync, identity resolver | fake-provider contract test, duplicate-prevention test |
| 10. Consolidate holdings from many providers | holdings read model (union by `security_id`, source column) | providers | Small | Per-provider toggles | No (source column) | identity, metrics | consolidation test with 2 fake providers, no double counting |
| 11. New reports, charts, filters | report query service + screen | other reports | Yes | Entitlement via Admin | Index if measured slow; summary table only if justified | metrics module, FilterBar, DataTable, filter options from registries | metric-definition tests, pagination test, perf budget |
| 12. Change theme or layouts | tokens file + layouts | everything else | Yes (CSS/TSX) | (theme choice could be a setting later) | No | one token source | visual regression on 5 key screens |
| 13. Redis or provider failure | none | — | No | — | — | Postgres fallback; retries in the shared HTTP helper; stale-data banners (PageState) | failure-injection tests: Redis down, provider timeout → page still renders, data marked stale |
| 14. Five developers in parallel | separate modules / worktrees | — | — | — | Migrations serialized by the lead | module ownership map, boundary tests, lifecycle tool | CI: boundary + full suite per PR; merge order planned by the lead |
| 15. Failed deploy / feature rollback | none | — | No (revert PR or switch off) | Capability off | Every migration is forward-compatible (nullable columns first) AND has a tested downgrade | deploy workflow, worktree tool, module switch | rollback drill: switch off → green; revert → green; migration downgrade test |

---

## 9. Minimum sufficient core

**MUST HAVE NOW (before broad feature work):**

| # | Item | Reuses | Effort | Freeze-safe? |
|---|---|---|---|---|
| M1 | Import-direction + router-protection tests; move the 4 `services`→`api` helpers into services/core | existing boundary-test style | S | Yes |
| M2 | Module registry `core/modules.py` (id, state, packages, routes, jobs, capabilities, depends_on) + lifecycle test | scheduler adders, router | S–M | Yes |
| M3 | Capability registry + `require_capability` + `/me/capabilities`; migrate plan FEATURES, ROUTE_RULES and release switches into it; admin screen for overrides and plan maps with audit | core/plans.py, billing entitlement, admin console, audit | M | Yes |
| M4 | Stock identity #389 phase 1: `securities` table + alias history + nullable `security_id`; one resolver used by new code; `user_watchlist_items.security_id` | instruments, corporate actions | M (migration approval) | Yes (additive) |
| M5 | Score identity: append-only `score_ledger` (trigger, like h05); `brain_runs.provenance` JSON; `predictions` FK → RESTRICT | h05 trigger pattern, registry | M (migration approval) | Yes, if written beside frozen code (see note) |
| M6 | Research config v1: `research_params` (pure data + hash) + equality tests against existing copies (frozen copies untouched) | trial_constants pattern | S | Yes |
| M7 | Frontend rule numbers and calendar from the backend: `/config/trading-rules` + trial-journal API; delete `wave3Rules` day-counting and literal rule copies | /risk/limits, trial_journal | S–M | Yes |
| M8 | One metrics module (P&L, win rate, returns) used by the 4 report paths | real_report, weekly report | M | Yes (reports aren't frozen) |
| M9 | Audit on `/safety/halt` + `/resume` and brain stage changes | services/audit.py | S | **Trading-sensitive**: owner approval + review-risk |
| M10 | Tenant-isolation tests (user A can't see user B's watchlist/tracker/billing; members can't read owner-private books) | route coverage tests | S | Yes |

Note on M5: writing to `score_ledger` from `brain/service._store` touches a frozen file. Either it waits until after the freeze, or a freeze approval entry is recorded. The `predictions`/`score_history` writers in `services/score_history.py` aren't frozen.

**IMPROVE INCREMENTALLY (when a screen or module is touched anyway):**
- one token file; StockCard, ScoreChart, DataTable and FilterBar extracted on first restyle
- typed query-key factory, client split by domain, OpenAPI-generated types
- `React.lazy` for owner and admin route groups
- `HoldingsProvider` port (with #388); holdings read model with a source column
- shared HTTP helper (timeouts + retries) for feeds and Telegram
- model cards and a verified shared loader (G8); promotion moved into one `promote()` function
- Redis key helper; report query service; split `execution.py` / `jobs.py`
- retire the Classic look screen by screen (S8 #401: saves only ~1.8% of JS, so do it for maintenance, not speed)

**DEFER UNTIL REQUIRED:**
- per-customer portfolios (`user_id` on positions; needs a product decision)
- materialized/summary tables
- Redis report caching (measure first)
- multi-provider consent aggregation (Account Aggregator-style; regulatory)
- dark mode/theme switcher
- trade-simulator consolidation (#405, after the freeze and the trial)
- splitting the scheduler into a separate worker

**NOT RECOMMENDED:**
- microservices; an event bus; a generic "everything in JSON config" engine
- admin-editable risk, trading rules or live-model swaps
- a plugin framework
- a separate v2 codebase
- rewriting the frontend

---

## 10. Proving it on existing modules (smallest refactor)

| Module | Shared services it should consume | Smallest refactor |
|---|---|---|
| **Discover** | capability `discover.view` / `history.scores`; identity resolver; score ledger for history; `useDiscover` hook; StockCard | Add `require_capability`; move its queries into a hook; read rule numbers from `/config/trading-rules`; no visual change |
| **Groww Tracker** | `security_id` on tracker rows; `HoldingsProvider` (Groww) for #388; metrics module for totals | Move `portfolioSummary` and `soldSummary` maths to the backend (`trackerRules.ts` keeps formatting only); land #388 behind the port |
| **Reports** | metrics module; report query service; FilterBar/DataTable; capability `reports.export` | Point idea reports and the weekly report at the metrics module; date filters in SQL |
| **Admin** | module registry view; capability overrides and plan maps with audit; research config version selector (read-only until M6) | One "Control Center" page reading the registries; reuse admin console, MFA step-up, `audit_log` |

---

## 11. Incremental migration strategy

1. **Clearance**: land S11, the candle stack, the 5-day fix and #387; decide on Groww sync and the progress chain; quarantine merged worktrees.
2. **Guardrails first** (M1, M10): tests only, so later refactors can't regress silently.
3. **Registries** (M2, M3, M6): additive; existing mechanisms become registry entries, behaviour unchanged (snapshot tests prove it).
4. **Identity** (M4, M5): migrations with owner approval; dual-write; readers switch one at a time.
5. **Frontend truth** (M7, M8): remove client-side business numbers; one metrics module.
6. **Prove on the 4 modules** (section 10), then open daily feature work with the change template (section 14).

Each step: its own worktree and PR, full suite, Codex review, owner merge, and a rollback (revert, or switch off). Migrations are forward-compatible (nullable columns first) and have downgrades.

---

## 12. GitHub issue mapping (summary; no board changes made yet)

Board: 179 items, 176 open.
- **Status doesn't reflect reality:** 0 In Progress, 0 Review, while 6+ items are actually being worked on.
- **82 items have no Work type**, including the newest #383–#405.

**Retain (KEEP):**
- #377, #383, #379, #381, #345, #373, #374, #376, #375, #358, #344
- the F2–F12 umbrellas and their requirements
- the Verify chain #238–#259 and #267–#280
- #346–#352, #356, #386, #339, #326, #310

**Update or extend:**
- #389 → the core identity contract (absorbs #390)
- #335 → becomes the parent of the capability registry (absorbs #331, #332 as flags)
- #388 → map to `security_id` + the `HoldingsProvider` port
- #322 → owns the report query service (absorbs #330, #378 report side)
- #265 → depends on #322
- #337 → owns the Redis conventions
- #296 → owns design tokens and shared UI (absorbs #336); #320 shared layouts
- #291/#258/#259 → the module registry and connector contract
- #346 → owns the architecture tests
- #328 → link to the registry
- #340 → the architecture review gate (absorbs #323)

**Consolidate:**
- #390 → #389
- #331 → #335
- #324 → #308
- #330 → #322
- #378 → #380/#322
- #380 with #321 and #264 (one 100-portfolio contract)
- #311 and #334 → #304
- #329, #262, #302/#303 → one replay spec
- #336 → #296
- #323 → #340

Each is attached as a sub-issue, not closed blindly.

**Verify:**
- #385, #387 (built), #316, #357, #353 (fix branches)
- #325, #254, #256, #314–#318, #217

**Park:**
- #262, #312, #338, #298/#299 (real money)
- the S8, S9 and S10 decisions (#401–#403)

**Blocked:**
- #405 (freeze + trial)
- gated post-trial bugs #341–#343, #354, #355, #360
- #353 (freeze approval)

**Done (merged):**
- #394, #395, #396, #397 (and #407 via PR #411)
- #392 stays open, because S5–S12 remain

**Create (no existing issue covers them):**
1. Module registry + import-direction/router-protection tests (M1, M2), under #291
2. Capability registry + `require_capability` + Admin Control Center (M3), under #335
3. Versioned research configuration (M6)
4. Score ledger + run provenance + predictions RESTRICT (M5), under #389's identity epic
5. Frontend trading rules and calendar from the backend (M7)
6. One metrics module (M8), under #322
7. Safety/brain admin audit (M9), trading-sensitive
8. Tenant-isolation tests (M10), under #346
9. Design tokens consolidation, under #296 (incremental)
10. Typed API client/query keys + lazy owner routes (incremental)
11. Redis key helper (small, under #337)
12. Architecture docs/ADRs index + AGENTS/CLAUDE update after approval

**Board organization** (existing project, no new board):
- Add one single-select field, **Track** = Core / Product / Verification / Ops.
- Fill the blank Work types.
- Make Status reflect reality.
- Add 4 saved views:
  - Core by Release
  - R1 Verification gate
  - Gated/Blocked
  - Needs triage (Release or Work type blank)

---

## 13. Developer plan (after approval)

| Phase | Devs | Assignment (files don't overlap) |
|---|---|---|
| Clearance (now) | 4 + lead | D1 candle stack · D2 5-day fix · D3 S11 · D4 #387 · D5 progress-chain check |
| Core wave 1 | **3** | D1: M1 + M10 tests (tests + 4 small moves) · D2: M2 + M3 backend registries · D3: M7 frontend truth (rule numbers, calendar) |
| Core wave 2 | 3–4 | D1: M4 identity (after migration approval) · D2: M3 admin UI · D3: M8 metrics · D4: M6 research config |
| Core wave 3 | 4–5 | D1: M5 score ledger (after freeze or with approval) · D2: Groww #388 behind the port · D3: Discover/Reports adoption · D4: tokens + StockCard on first restyle · D5: verification chain |
| Daily features | 5 | one module per developer; the lead runs the impact check (reuse, module, capability, migration, tests) |

The lead owns: shared interfaces, the migration order, merge order, integration testing, the board status, and Codex review dispatch.

---

## 14. Core readiness acceptance criteria (evidence, not documents)

| Area | Criterion (must be demonstrated by a test or a run) |
|---|---|
| Feature isolation | Boundary test green: no `services`/`core`→`api`, no product→product internals; each module can be switched off and the full suite stays green |
| Configuration-driven | Entitlement matrix test: every plan × capability is enforced server-side; changing a plan map needs no deploy; every change writes an `audit_log` row and can be reverted |
| UI independence | Restyle drill: change tokens + one layout of Discover; zero backend diffs; Playwright journeys green |
| Shared data integrity | Same stock resolves to one `security_id` across Discover/Watchlist/Groww/Reports; score-ledger trigger rejects UPDATE/DELETE; every new score row carries model + config version |
| API compatibility | OpenAPI snapshot test fails on breaking changes; generated TS types compile |
| Security & isolation | Router-protection test; tenant-isolation tests; no secrets in logs/audit; owner-only prefixes enforced |
| DB & cache | Single alembic head; every new migration has a downgrade and a clean-upgrade drill; cache keys namespaced with TTL; Redis-down test passes |
| Parallel development | Two stories in separate modules merge without conflicts on shared files (measured on wave 2) |
| Regression protection | Full backend + vitest + Playwright green on `main`; existing journeys covered (Today, Discover, Watchlist, Groww, Portfolio, Reports, Admin) |
| Safe rollback | Rollback drill: capability off restores old behaviour; PR revert green; migration downgrade tested |

---

## 15. Risks, trade-offs and decisions for the owner

**Decisions needed:**
1. **Approve the approach**: modular monolith, evolved in place; no microservices or v2.
2. **Approve the MUST-HAVE-NOW list** (M1–M10) and the **3-developer start**.
3. **Migrations M4/M5** (securities table, score ledger, provenance column, predictions RESTRICT): approve in principle; each PR still gets your review.
4. **Brain correctness (frozen files), choose a timing:**
   - G6 score-vs-plan mismatch
   - G7 obv_slope skew
   - brain-row identity

   Fix after the trial/freeze, or record freeze approvals now. Until then, the UI text should say the score is a 5-day ranking (the 5-day plan fix partly does this).
5. **Per-customer portfolios**: confirm customers stay "readers of the shared book + own watchlist/tracker" for now (recommended).
6. **Board changes**: approve the Track field, the views, the consolidations (as sub-issues) and creating the 12 issues.
7. **Drawdown limit documentation**: README says 20%, `CLAUDE.md` says 15%. Which is right?
8. **Developer `git commit` permission** for the `cleanup-*`/feature worktrees (today every developer commit needs the lead).

**Trade-offs:**
- **Additive-first** (new tables beside old ones, dual-write) costs some temporary duplication but keeps production safe.
- **Leaving frozen files alone** means some known issues (G6, G7) stay visible until after the trial.
- **Not building a generic configuration engine** means a few things still need code.

**Main risks:**
- migration mistakes on identity → mitigated by nullable columns, dual-write and a clean-upgrade drill
- registry work changing behaviour unintentionally → snapshot tests of current access per route
- parallel work colliding → module ownership, a 3-developer start, and lead-planned merge order
