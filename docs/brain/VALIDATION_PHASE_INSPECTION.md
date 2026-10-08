# Validation phase inspection (read-only)

**Workspace baseline:** commit `0bdaa76` (HEAD at inspection time).  
**Owner freeze:** no new trading features; validation and evidence layer only.  
**Spec reference:** TradeMind Brain Build Book sections **4–18** (`docs/superpowers/specs/2026-09-29-trademind-brain-build-book.html`).

This document maps what already exists vs what a **validation phase** should add. It does not authorise implementation here.

---

## A. Current-state architecture (concise)

- **Runtime:** One FastAPI app + APScheduler **worker** + Postgres/TimescaleDB + Redis; production on a single droplet. No separate brain microservice.
- **Brain package:** `backend/src/swing_trade_ml/brain/` — eight-step pipeline (M01–M09 step modules + M10–M15 plug-ins), orchestrated by `runner.py` / `execute()`, constitution in `constitution.py`, all DB reads via `reader.py` (`DatedReader`, `as_of`-bounded; live-only paths for model score and holdings).
- **Persistence:** `brain/service.py` `_store()` writes `brain_runs` (trace, quality, `context` including **`data_manifest`**), `brain_decisions`, nightly **`feature_snapshots`**; M15 track rows via `m15_tracker/store.py`; M04 **`brain_episodes`**, M05 **`brain_experience`**, M09 **`brain_proposals`** + outcome columns on decisions.
- **Service 1 (data layer) at baseline:** PIT **`watchlist_snapshots`** + `brain/universe.py`; **`candle_corrections`** on ingest + **`feature_snapshots` invalidation** (`services/feature_snapshots.py`); **`data_manifest`** (`brain/data_manifest.py`); feed **`connector_status`** on `/brain/health` (`brain/connectors.py`); split-contamination CLI (`services/split_check.py`); provisional 2027 holidays.
- **M18 go-live (shadow only in prod practice):** `strategies/brain.py` → v1 `signals` (`is_shadow`); `services/brain_golive/` (`shadow.py`, `compare.py`, `stage.py`, `approvals.py`); API `api/v1/endpoints/brain_golive.py` (`/brain/stage`, `/brain/compare`, `/brain/approvals/*`). Orders only through approvals when stage ≠ shadow.
- **Surfaces:** Owner console `frontend/src/pages/Brain.tsx`; owner-facing TradeMind UI under `/trademind/*` (banner, cards, stage). Brain API `api/v1/endpoints/brain.py` gated by `BRAIN_ENABLED`.
- **Principles in code:** Monotonic downgrades (`contracts.downgrade`, constitution); **WAIT is valid**; M08 `evidence_text` from recall/calibration (no promise wording in tests); learning **proposes only** (M09 run step is empty; scoring/report off-run).

```mermaid
flowchart LR
  subgraph ingest [v1 ingest]
    Candles[candles]
    Feeds[side feeds]
    WL[watchlist_snapshots]
  end
  subgraph brain [brain run]
    DR[DatedReader]
    Run[runner + modules]
    Store[service._store]
  end
  subgraph evidence [evidence layer today]
    RW[replay-week CLI]
    SC[split-check CLI]
    RS[rescore-learning CLI]
    CMP[M18 compare API]
    HL[/brain/health]
  end
  Candles --> DR
  Feeds --> DR
  WL --> DR
  DR --> Run --> Store
  Store --> RW
  Store --> RS
  Candles --> SC
  Store --> CMP
  Store --> HL
```

---

## B. What `0bdaa76` already provides (concrete)

### Database (Alembic brain / Service 1 P0)

| Artifact | Purpose |
|----------|---------|
| `brain_runs` | Run audit: kind, `as_of`, `live`, status, trace JSON, quality, `context` (+ `data_manifest`) |
| `brain_decisions` | Per-symbol words, levels, `evidence_text`, reasons, overrules, M09 `outcome*` |
| `brain_modules` | Owner ON/SHADOW/OFF per module |
| `feature_snapshots` | M02 PIT feature store per symbol/bar_date |
| `watchlist_snapshots` | PIT universe (#4) |
| `candle_corrections` | Correction log + known_at lite (#1/#13) |
| `brain_episodes`, `brain_experience`, `brain_track`, `brain_proposals` | M04/M05/M15/M09 |
| `brain_stage_changes`, `brain_approvals` (golive models) | M18 stage + approval queue |

### Modules registered (M00 = runner/registry; no separate `M16`/`M17`/`M18` Python modules)

Installed: **M01–M15** in `brain/modules/__init__.py`. **M06** and **M05** default **SHADOW**; **M12** SHADOW. **M07** mandatory ON. Alerts/console behaviour split across `brain/alerts/`, `brain/service.py`, API, and frontend (build-book M16/M17 names, not separate module classes).

### CLI (`swingtrade brain …`)

| Command | Role |
|---------|------|
| `run`, `why`, `modules`, `set` | Live/replay runs and inspection |
| `replay-week` | Phase-1 gate: N IST trading days, historical `as_of` (`brain/replay_week.py`) |
| `rescore-learning` | M09 batch score on finished live nightly ideas (`m09_learn/scoring.py`) |
| `learn` | M09 report/proposals (read-only report path) |
| `split-check` | B0 split/bonus contamination scan |
| `memory-build`, `meta-train` | M05 backfill; M06 training evidence (heavy) |
| `strategy-create`, `shadow-scan` | M18 setup helpers (TESTING.md) |

### API (`/api/v1/brain/*` + golive)

**brain.py:** `modules`, `runs` (+ queue 202), `runs/latest`, `runs/{id}`, `runs/{id}/trace`, `health`, `why/{symbol}`, `decisions/{id}/overrule`, `learning`, `proposals`, `whatif`, `track/{symbol}`, `episodes`, alerts under run.  
**brain_golive.py:** `compare`, `stage` GET/PUT, `approvals` GET, approve/reject POST.

**Not present vs build-book §16:** dedicated `GET /brain/decisions` (list/filter), `GET /brain/banner`, `GET /brain/decisions/{id}` — clients use `runs/latest` or TradeMind aggregates.

### M18 at baseline

- Shadow strategy records ideas; **30 finished brain ideas** gate stage advance (`compare.NEEDED_FINISHED`, `stage.py`).
- Compare uses v1 **signal outcomes** (same scorer as v1), not a duplicate brain outcome engine.
- Production posture (docs): **practice (shadow)**; no auto brain orders.

### Evidence docs already under `docs/brain/evidence/`

- `PHASE2_EVIDENCE_TEMPLATE.md` (replay-week + rescore transcript 2026-10-05)
- `split_check_20261005.md`, `prod_deploy_20261005.md`, `model_artifact_backup.md`, `alembic_local_20261005.md`
- Ad-hoc scripts: `m04_labels_vs_outcomes.py`, `m05_memory_walk_forward.py`, `m12_*` (not wired to CI)

### Automated tests (representative)

45+ `test_brain_*.py` files including: runner monotonicity & PIT replay (`test_brain_runner.py`), API (`test_brain_api.py`), M18 shadow/stage/compare/approvals, `test_brain_replay_week.py`, `test_split_check.py`, `test_service1_gaps.py`, M08 engine evidence (`test_brain_m08_engine.py`), M09 learning (`test_brain_m09_learning.py`).

---

## C. Gap list for validation phase (sections 4–18)

Status key: **EXISTS** · **PARTIAL** · **MISSING** (for validation/evidence goals; not a full feature backlog).

| § | Title | Status | What exists | Validation-phase gap |
|---|--------|--------|-------------|----------------------|
| **4** | What exists today | **EXISTS** | Brain wraps v1 ML/feeds/risk; table in spec is largely true at `0bdaa76` | Keep inventory doc in sync after validation-only changes; no code required |
| **5** | Functional requirements | **PARTIAL** | BR-01–04, 06, 10–19, 30–34, 40–41, 46–48 largely implemented | **BR-05** full connector plug-in (only lite `connectors.py`). **BR-16** recall depends on M05 SHADOW + `memory-build`. **BR-20** M09 scoring works; weekly expected-vs-actual **evidence doc empty** (Phase 2). **BR-48** compare exists; **shadow comparison gate** (roadmap Phase 3) not a formal pass/fail artifact |
| **6** | Non-functional requirements | **PARTIAL** | NFR-02/03/06/07/08 covered in unit tests; timing stored on runs | **NFR-01** full per-module fault-injection matrix not one suite. **NFR-04/05** no CI gate on 60s/10s budgets. **NFR-06** no **golden-day** fixture in repo for replay regression. **NFR-10** contract major-version registry check not enforced. **NFR-14** partial (some card lint in M08 tests) |
| **7** | Decision vocabulary | **EXISTS** | `brain/contracts.py`, constitution, UI vocab | Validation: assert API/UI still use single vocabulary on sampled runs |
| **8** | Not planned | **N/A** | Explicitly out of scope | Do not expand validation into alt-data/scraping |
| **9** | How the brain thinks | **EXISTS** | Context flow, three run kinds, BrainStrategy shadow path | Validation: document **observe** path — replay reads stored snapshots + `DatedReader`, must not re-implement M08 |
| **10** | Module contract | **EXISTS** | `module.py`, runner budgets, `Contribution` merge | Validation harness should call **real** `execute()` / `run_brain()`, not duplicate rules |
| **11** | Running with modules off | **EXISTS** | Fallbacks + monotonic test in `test_brain_runner.py` | Add **stored-day** regression: replay same `as_of` with one module OFF, diff decisions JSON (M09 spec counterfactual — **MISSING** as CLI) |
| **12** | Data contracts | **EXISTS** | `contracts.py` dataclasses | Validation reports should snapshot contract fields from DB/trace, not reinterpret |
| **13** | Storage | **PARTIAL** | All core tables; manifest on runs | **§13.1 retention/housekeeping job MISSING** (intraday 90d, compression). Hypertable on `feature_snapshots` — verify ops assumption in validation runbook |
| **14** | Orchestration | **PARTIAL** | Scheduler jobs when `BRAIN_ENABLED`; queue + lock via `brain/queue.py` (not Redis `brain:lock` from spec) | Validation: document actual lock semantics; nightly retry/alert behaviour — verify in worker tests only partially |
| **15** | Safety constitution | **PARTIAL** | C1–C5, C8–C11 in code/tests | **C6–C7** property tests partial (M15). **C12** text lint only in M08 tests. Validation phase: **constitution checklist** run on replay-week output (banner, zero TRADE without M07, stale→WATCH) |
| **16** | API and screens | **PARTIAL** | Console + TradeMind; most endpoints | Missing list/banner endpoints; M16 = alerts service + frontend, not module. Validation via **TESTING.md** L1–L2 + API snapshots |
| **17** | Build order / milestones | **PARTIAL** | M00–M18 code on main; ops roadmap in `ROADMAP.md` | **Phase 2 gate:** M06 meta-train + M09 before/after table **empty**. **M18:** 0/30 finished shadow ideas in local evidence. Validation phase owns **filling evidence templates**, not new waves |
| **18** | How to ask / Definition of done | **PARTIAL** | D1–D8 practised in module tests | **D4** monotonicity on **production-like golden day** not checked in CI. **D9** traceability table in book not maintained in repo. Validation phase: **module-agnostic DoD** checklist below |

### Cross-cutting validation gaps (not a single §)

| Gap | Status | Notes |
|-----|--------|--------|
| Point-in-time replay gate | **PARTIAL** | `replay-week` + `DatedReader` + snapshots; no automated diff vs prior baseline commit |
| Learning evidence | **PARTIAL** | `rescore-learning` works; 0 finished ideas in recorded run |
| Data contamination | **PARTIAL** | `split-check` + deferred gap #3 adjusted prices |
| Shadow vs v1 gate | **PARTIAL** | `/brain/compare` + tests; no signed-off threshold document |
| “Fake WHY” guard | **MISSING** as product test | `why` runs full pipeline — validation should compare **trace** to stored nightly decision, not paraphrase engine |
| WATCH plan levels in UI | **UI gap** (backend OK) | Risk-blocked WATCH keeps levels in DB/API; Opportunities list hides them (TRADE-only columns). See [evidence/watch_levels_display_20261006.md](evidence/watch_levels_display_20261006.md) |
| Dedicated `validation/` package | **MISSING** | Today logic scattered: CLI, `replay_week.py`, `split_check.py`, evidence markdown |

---

## D. Exact files/modules likely to need modification (minimal)

**Prefer new code under validation/evidence paths; touch decision modules only for hooks/read APIs.**

### Suggested new (do not implement in freeze breach)

| Path | Purpose |
|------|---------|
| `backend/src/swing_trade_ml/brain/validation/` | PIT replay driver, golden-day diff, constitution smoke, report JSON |
| `backend/src/swing_trade_ml/services/brain_validation/` | Optional thin CLI adapters if keeping `brain/` import-pure |
| `backend/tests/test_brain_validation_*.py` | Golden replay, manifest presence, health schema |
| `docs/brain/evidence/VALIDATION_RUN_*.md` | Human-signed run outputs (like existing Phase 1 gate) |

### Likely touch (read-only or wiring only)

| Path | Why |
|------|-----|
| `backend/src/swing_trade_ml/brain/replay_week.py` | Extend reporting (manifest hash, constitution flags) without changing runs |
| `backend/src/swing_trade_ml/cli.py` | New subcommand e.g. `brain validate-week` delegating to validation package |
| `backend/src/swing_trade_ml/brain/service.py` | Read helpers: export run package, compare decisions (no store change) |
| `backend/src/swing_trade_ml/brain/data_manifest.py` | Assert fields in validation reports |
| `backend/src/swing_trade_ml/services/split_check.py` | Scheduled evidence hook |
| `backend/src/swing_trade_ml/brain/modules/m09_learn/report.py` | Already side-effect free — reuse for evidence CSV |
| `docs/brain/TESTING.md`, `docs/brain/evidence/PHASE2_EVIDENCE_TEMPLATE.md` | Link validation phase commands |

### Avoid for validation-only work

- `m08_decide/engine.py`, `m07_risk/*`, `strategies/brain.py`, `services/brain_golive/approvals.py` (trading path)
- Changing M06/M08 thresholds or M11 gate behaviour (roadmap Phase 3)

---

## E. Test plan

### Unit (fast, CI)

- Existing suite: `pytest tests/test_brain_*.py tests/test_split_check.py tests/test_service1_gaps.py` (Postgres Docker).
- Add: validation package tests that **load fixture DB slice** or use existing factories — assert `data_manifest` keys, `connector_status` shape, decision rows have `reasons` + trace ref (C11).

### Replay PIT

- `brain replay-week --days N` on fixed calendar window; archive counts + banner + `universe_count` vs `data_manifest.universe_snapshot_date`.
- **Golden day:** one `as_of` with frozen expected `brain_decisions` word histogram (store hash in `tests/fixtures/` or validation module); fail on unintended diff when runner unchanged.
- **Leak test:** seed future candle row; assert `DatedReader` / replay do not change decisions (extends `test_replay_does_not_use_live_only_inputs`).

### Shadow (M18)

- `test_brain_m18_shadow.py`, `test_brain_m18_compare.py`, stage gate tests — keep green.
- Ops: `/brain/compare` with `MIN_FINISHED_TO_COMPARE` — document “insufficient data” as pass for ops, not failure.

### Regression

- Monotonicity: keep `test_switching_any_module_off_never_makes_a_decision_bolder`; add one integration case with real module registry + DB if feasible.
- Service 1: `split-check` after deploy; snapshot invalidation test in `test_candle_corrections.py`.
- Frontend: `npx tsc --noEmit` if validation touches types only.

### Manual (owner)

- `docs/brain/TESTING.md` Level 1–2 after each deploy.
- `docs/brain/evidence/prod_deploy_20261005.md` checklist.

---

## F. Implementation sequence (phased, smallest safe steps)

1. **Evidence schema only** — Define validation report JSON (run ids, manifest, counts, constitution booleans, compare snapshot); no runner changes.
2. **CLI wrapper** — `brain validate-week` = `replay-week` + report file under `docs/brain/evidence/` (or stdout); reuse `replay_week.py`.
3. **Golden hash** — One trading day, commit expected decision hash; CI job on Postgres.
4. **WHY integrity check** — For one symbol, `GET /brain/why/{sym}` vs latest nightly decision: same word, trace contains module ids (no new narrative).
5. **M09 rescore watchdog** — Document exit codes; alert when `rescore-learning` errors (ops).
6. **Phase 2 evidence** — Owner-triggered `meta-train` + fill `PHASE2_EVIDENCE_TEMPLATE.md` (no auto-promote M06).
7. **Counterfactual OFF** (optional) — Read-only replay with modes dict; diff JSON (spec M09 item 5); do not auto-toggle modules in prod.
8. **Retention job** — Only if DB growth becomes validation blocker (§13.1); separate owner approval.

---

## G. Risks

| Risk | Mitigation |
|------|------------|
| **Behaviour change** | Validation code must not import `services.execution` or alter module modes in prod |
| **PIT leaks** | All historical checks through `DatedReader` + `watchlist_snapshots`; tests with future bars |
| **Scope creep** | Freeze: no playbook gate, M11 production gate, adjusted prices (#3), or stage → approval |
| **Fake WHY** | Reports cite `brain_runs.trace` and `brain_decisions` ids, not LLM summaries |
| **WAIT / NO_NEW_TRADES misread** | Sign-off checklist treats cautious output as healthy (TESTING.md) |
| **Evidence vacuity** | 0 finished shadow ideas → compare/rescore empty until time passes; state explicitly in reports |
| **Windows paths / models** | `MODEL_ARTIFACT_DIR` mismatch — validate in Docker worker path per TESTING.md |

---

## H. Manual actions for owner

1. **Prod deploy** — `docs/brain/evidence/prod_deploy_20261005.md`: rebuild api/worker, `alembic upgrade head`, split-check, watchlist snapshot hook.
2. **Kite** — Morning login on prod only; never from local automation (CLAUDE.md).
3. **M18** — Keep stage **shadow** until **30 finished** brain shadow ideas; track on Brain Trading stage card and `/brain/compare`.
4. **Strategy** — TradeMind brain strategy **active** or shadow ideas stop.
5. **Weekly** — `docs/brain/weekly_health_checklist.md` + TESTING Level 1–2.
6. **Backups** — `docs/brain/evidence/model_artifact_backup.md` off-droplet model copy.
7. **Phase 2** — When ready, run `brain meta-train` in controlled window; fill evidence template; do not set M06 ON without owner sign-off.

---

## Definition of done (validation phase)

Cross-reference: **E** = exists at baseline · **B** = build in validation phase only.

- [ ] **Replay gate:** `replay-week` for agreed N days produces archived report with manifest + counts (**E** CLI; **B** automated archive + hash).
- [ ] **PIT:** Leak test green on CI (**B** golden/future-bar fixture).
- [ ] **Constitution smoke:** No TRADE without M07 path; stale data caps — checked on replay output (**E** logic; **B** report flags).
- [ ] **Service 1 B0:** `split-check` clean or documented exceptions (**E**).
- [ ] **Health:** `/brain/health` documents `feeds` + `data.fresh` (**E**).
- [ ] **M09:** `rescore-learning` runs clean; when ideas exist, outcomes on `brain_decisions` (**E** scorer; **B** filled evidence table).
- [ ] **M18:** Shadow signals recording; compare endpoint returns JSON; stage remains shadow until 30 finished (**E**; **B** ops tracking).
- [ ] **WHY:** Trace-backed explanation matches stored decision word (**B** integrity script).
- [ ] **No trading changes:** No edits to approval/auto paths, limits, or live flags (**freeze**).
- [ ] **Docs:** `PHASE2_EVIDENCE_TEMPLATE.md` and validation run markdown updated with dates (**B**).
- [ ] **CI:** Brain + validation tests green on Docker Postgres (**E** partial; **B** golden hash job).

---

## Coordinator summary

At **`0bdaa76`**, the brain stack is **complete for M01–M15 + M18 wiring**: tables, `DatedReader` PIT universe, `data_manifest`, health feeds, `replay-week` / `rescore-learning` / `split-check`, rich pytest coverage, and prod **shadow** M18. Gaps for a **validation-only phase** are mainly **evidence automation** (golden replay hash, constitution report, WHY-vs-store check, Phase 2 M06/M09 doc), **M09 counterfactual replay CLI**, **retention job (§13.1)**, and **formal shadow comparison gate** — not new decision logic. Observe stored runs/traces; treat **WAIT** and **NO NEW TRADES** as valid safe outcomes.

**Deliverable path:** `docs/brain/VALIDATION_PHASE_INSPECTION.md`
