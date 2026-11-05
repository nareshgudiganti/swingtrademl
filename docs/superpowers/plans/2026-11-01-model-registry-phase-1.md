# Model Registry, Phase 1: implementation plan (PLAN ONLY, nothing built)

Status: **plan for owner approval, 2026-11-01.** No code, migration or deployment until the owner approves this plan.
Owner direction: nine logical model slots (5D/10D/15D x large/mid/small), maximum capacity, not a target; prove one model before
expanding; the brain ignores the registry; no activation controls.

## 1. What Phase 1 is

A read-mostly, owner-only page that shows the nine slots, the facts about every model already in `ml_models`, where each one is
actually used, and the evidence we really have (with "Not measured" where we have none). The only thing the owner can change is a
slot's **research priority / research status / note**. Changing them starts nothing.

Out of Phase 1 (separate approvals): performance replay, training any model, 10D/15D research, activation or any gate that
activates, customer-facing screens, a menu entry, changes to the combined-universe baseline work.

## 2. Findings that shape the plan (verified in code on 2026-11-01)

| Question | Finding | Consequence |
|---|---|---|
| Is a second `model_provenance` table needed? | **No.** `ml_models` already stores version, algorithm, `feature_names`, `hyperparameters`, `training_symbols`, `train_start/end`, `n_samples`, `prediction_horizon_days`, `target_return_pct`, `stop_return_pct`, `label_kind`, `metrics` (incl. `metrics["calibration"]` when calibrated), `artifact_path`, `trained_at`, `activated_at`. | Compute cap group, calibration status and the feature-set / universe / artifact fingerprints **on read**. Nothing duplicated, nothing to drift. |
| Cap group | Not stored; `strategies/tier.py::cap_tier(name)` maps `*_smallcap`, `*_midcap`, else **"large"**. | Default "large" is wrong for e.g. `wf_h15_<date>` models. The registry must report **Unknown** for any name that does not match a known pattern, never "large". |
| Calibration status | `train.py` writes `metrics["calibration"]` only when `calibrate=True`. | Present = Calibrated, absent = Not calibrated, missing metrics = Unknown. |
| Deployment status | `ml_models.status` (TRAINING/TRAINED/ACTIVE/ARCHIVED) plus `strategies.params["model_name"]`, `is_active`, `mode`, `execution_mode`. | Derive: ACTIVE model + which active strategies use its name (and in which mode). Brain usage is **not** read (brain independence), so it is shown as "Not checked here". |
| Existing screens | `Models.tsx` has **train and activate buttons** (`api.activateModel`). `ModelLab.tsx` is read-only calibration. Both are routed but not in the menu. | Do **not** extend `Models.tsx` (reuse would drag activation into the page). Build a separate page; reuse its small parts (`Stat`, `TierBadge`, `lib/format`, `Loading`) and link to ModelLab for calibration detail. |
| Isolation of h05 | A test asserts only `api/v1/endpoints/h05.py` and `workers/scheduler.py` import the lane. | The registry backend must **not** import h05. The page gets forward evidence from the existing owner-only `GET /research/h05/report` in the browser. |
| Trial freeze | `tests/trial_freeze.py` fingerprints brain/modules, strategies, ml/features, ml/predict, services/risk and others. | New files go in `services/`, `api/v1/endpoints/`, `db/models/` (none frozen) and touch no frozen file. `test_trial_freeze.py` must stay green unchanged. |
| Owner gate | `api/deps.py::require_owner` (real account, never a preview). | Use it on every registry route, read and write. |
| Migration head | `h05l4n3e1a2b` (single head). | New migration chains from it. |

## 3. Design (smallest version)

### 3.1 Database: one small table, no change to existing tables

`model_research_slots` (9 rows seeded by the migration):

| Column | Type | Note |
|---|---|---|
| `slot_key` | text PK | `"5d-large"`, `"5d-mid"`, `"5d-small"`, `"10d-..."`, `"15d-..."` |
| `horizon_days` | int | 5, 10, 15 |
| `cap_tier` | text | `large` / `midcap` / `smallcap` (the existing vocabulary) |
| `research_status` | text | `not_started` / `researching` / `evidence_review` / `parked` (a label; drives nothing) |
| `priority` | int null | 1 = first; null = unranked |
| `note` | text null | owner's words |
| `updated_at`, `updated_by` | timestamptz, text | |

Deployment status is **not stored**; it is derived on every read (3.2). Seed priorities from the owner's list: 15d-large 1,
15d-mid 2, 10d-large 3, rest unranked; `5d-*` seeded `researching` ("evidence being collected", reflecting h05), the other six
`not_started`. Every change also writes one row to the existing `audit_log` through `services/audit.py` (no new audit table).

### 3.2 Backend

- `db/models/registry.py`: the one model above; imported in `db/models/__init__.py`.
- `services/model_registry.py` (pure read + one write function):
  - `slot_for(model)` -> `(horizon, cap_tier)` or Unknown (strict suffix match; never defaults to large).
  - `provenance(model)` -> model id, name, version, algorithm, cap group, horizon, target, stop, label kind, feature count + sha256 of
    `feature_names`, training-universe count + sha256 of sorted `training_symbols`, train window, `n_samples`, calibration status,
    artifact sha256 (computed from `artifact_path`, "Unknown" if the file cannot be read).
  - `deployment(model, strategies)` -> `{"model_status": ACTIVE|ARCHIVED|..., "used_by": [{strategy, mode, execution_mode}], "label"}`; label
    `Deployed`, `Active model, no active strategy`, `Not deployed` (only when status is TRAINED/ARCHIVED and no strategy uses it),
    `Unknown` if the strategy list cannot be read. **A model that is ACTIVE or used by an active strategy is never labelled Not deployed.**
  - `evidence(model)` -> blocks with fixed labels: **Held-out AUC (historical, one split)** from `roc_auc` / `metrics`;
    **Precision at threshold (historical)**; **Ranking performance (top 5)**, **Economic performance (after costs)** and
    **Drawdown**: `Not measured` (replay is out of Phase 1); **Forward evidence**: `Not measured here` (the page reads h05 itself).
    A missing value is `null` in the API and renders as "Not measured", never 0.
  - `update_slot(db, slot_key, priority, research_status, note, actor)` is the **only** write. It touches `model_research_slots` and
    `audit_log` only.
- It imports **nothing** from `brain/`, `ml/train.py`, `ml/registry.py` (activation) or `brain/lanes/`.

### 3.3 API (owner only; new file `api/v1/endpoints/model_registry.py`, router include in `router.py`)

| Route | Purpose |
|---|---|
| `GET /model-registry/slots` | the nine slots with research fields, the models mapped to each (provenance + derived deployment + evidence blocks) |
| `GET /model-registry/models/{id}` | one model's full provenance |
| `PATCH /model-registry/slots/{slot_key}` | body limited to `priority`, `research_status`, `note`; unknown fields rejected (422) |

No POST/DELETE, no train, no activate. The existing `/ml/models*` routes (including `POST /ml/models/{id}/activate`) are **not called,
wrapped or modified**.

### 3.4 UI (owner only)

- New `frontend/src/pages/ModelRegistry.tsx` at route `/model-registry`, `manage: true`, `inNav: false` (reachable by URL; a menu entry
  is a separate decision).
- 3x3 grid (horizon x cap). Each cell: research status, priority control, mapped model(s) with deployment label, and "no model yet"
  where empty.
- Detail panel per model: provenance, evidence blocks with the labels in 3.2, a link to ModelLab for calibration, and forward evidence
  fetched from the existing `GET /research/h05/report` (only for the three 5D slots; "Not measured yet" while the lane is empty).
- Priority/status/note controls call only the PATCH. No train, activate or "promote" control exists on the page.
- `frontend/src/api/client.ts`: three typed functions. No change to `Models.tsx` / `ModelLab.tsx`.

## 4. Exact files

New: `backend/src/swing_trade_ml/db/models/registry.py`, `backend/src/swing_trade_ml/services/model_registry.py`,
`backend/src/swing_trade_ml/api/v1/endpoints/model_registry.py`, `backend/alembic/versions/<date>_model_research_slots.py`,
`frontend/src/pages/ModelRegistry.tsx` (+ its test), `backend/tests/test_model_registry_*.py`.
Edited (additive): `api/v1/router.py`, `db/models/__init__.py`, `frontend/src/App.tsx` (one route), `frontend/src/api/client.ts`.
Untouched: every file in the trial-freeze manifest, `brain/`, `strategies/`, `ml/` (all), `workers/`, `Models.tsx`, `ModelLab.tsx`,
`api/v1/endpoints/ml.py`, h05 files.

## 5. Tests (must exist and pass before any merge)

Backend
- **Authorization**: unauthenticated 401; tester and member 403 on every route (read and PATCH); owner 200; owner preview mode
  cannot be used to reach it (`require_owner` checks the real account).
- **PATCH is narrow**: unknown field -> 422; row counts of `ml_models`, `strategies`, `predictions`, `signals`, `orders` and `positions`
  identical before/after; exactly one new `audit_log` row; `activate_model`, training functions and the scheduler are monkeypatched
  to fail the test if called.
- **Isolation**: a source-scan test that `services/model_registry.py` and the endpoint import nothing from `brain`, `ml.train`,
  `ml.registry`, `brain.lanes`; and a test that no module under `brain/`, `strategies/`, `ml/`, `workers/` imports the registry.
  The existing h05 import test still passes.
- **Provenance integrity**: cap group Unknown for `wf_h15_20260101` and any unmatched name (never "large"); known names map
  correctly; fingerprints stable across calls and change if a feature or symbol changes; calibration Calibrated/Not calibrated/Unknown;
  unreadable artifact -> Unknown, not an error.
- **Deployment derivation**: an ACTIVE model is never "Not deployed"; a model used by an active strategy shows that strategy and
  mode; no strategy -> "Active model, no active strategy"; failure to read strategies -> Unknown.
- **Metrics honesty**: missing AUC -> `null` (not 0); replay-only blocks are always "Not measured".
- **Migration**: upgrade from head on the test DB creates 9 seeded rows and touches no other table; downgrade drops only the new
  table; head remains single.
- **Freeze and regression**: `test_trial_freeze.py` green with no manifest change; full backend suite green; `ruff` on touched files only.
- **OpenAPI guard**: the `/ml/models/{id}/activate` route definition is unchanged.

Frontend
- Not-measured and Unknown render as text, never `0`/`0%`; the page contains no train/activate/promote buttons; the priority control
  calls only the PATCH and shows an "this does not start anything" note; non-owner sees no access; `npx tsc --noEmit -p .` and the
  existing tests green; Models.tsx and ModelLab.tsx tests unchanged.

## 6. Migration safety, rollback, deployment verification

- **Migration**: additive, one new table plus nine seed rows; no ALTER on existing tables; runs inside release.sh as today.
  Before merging: Actions -> **Restore drill** with `upgrade_check` ticked and `ref` = the branch (as was done for h05).
- **Rollback**: revert the PR (the table is then simply unused); optional `alembic downgrade` drops only `model_research_slots`.
  Nothing else changes, so no model, strategy, trial or lane is affected.
- **Deploy**: after 16:30 IST on a trading day (or any time at weekends). Verification after deploy, using the read-only API with the
  owner key (never printed): `GET /status` unchanged; `GET /ml/models` identical to before (same ids, statuses, ACTIVE models 2/16/17);
  `GET /model-registry/slots` returns 9 slots; a non-owner call returns 403; `h05_cli report` unchanged; scheduler job list unchanged;
  sealed-trial counts unchanged.

## 7. Effort (one developer, with tests)

| Piece | Estimate |
|---|---|
| Table + migration + seed + model | 0.5 day |
| Service (slot map, provenance, deployment, evidence labels) | 1 day |
| API + authorization tests | 0.5 day |
| UI page + tests | 1.5 days |
| Isolation/integrity tests, full-suite run, lint | 0.5 day |
| Restore drill, PR, deploy, verification | 0.5 day |
| **Total** | **about 4.5 days** (small to medium) |

## 8. Approval gates

1. **Approve this plan** -> I create a branch from `origin/main` (not the work-in-progress branch) and build.
2. **Approve the PR** after CI and the Restore drill with `upgrade_check` are green.
3. **Approve deploy** (merge to main).
4. Anything else is a later, separate approval: the historical replay (top-5, net after costs, drawdown), a menu entry, 10D/15D
   research and training, the combined-universe baseline, validation gates and anything that activates a model.

## 9. Open questions for the owner

1. Is the seeded priority order (15d-large, 15d-mid, 10d-large, rest unranked) right?
2. Should the 5D slots' research status start as `researching` (h05 collecting evidence) or `not_started`?
3. Should the page show models that map to no slot (for example `wf_h15_*` experiments) in an "Unassigned" list? Default: yes, read-only.
