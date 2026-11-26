# Audit: model lifecycle records on `origin/main` (Feature 1, #218)

Date: 2026-11-25 (IST). This is a read-only audit of `origin/main` at `13b9c31b`. No code or data was changed, nothing was trained, there was no prod access, and `.env` was not read.
Paths are relative to `backend/src/swing_trade_ml/` unless they start with `backend/`, `infra/`, `scripts/`, `docs/` or `.github/`.
No issue was created. Every gap below is mapped to an existing issue. Proposed issue text appears only where no existing issue covers the gap.

## Plain-English summary

When a model is trained today through the main training path (`ml/train.py`), it leaves a good record:
* which inputs it used and a fingerprint of the input formulas
* the code commit (when one is known)
* the library versions and the random seed
* the data dates
* a hash of the training table
* a hash of the saved file
* its test scores

Database and model-file backups exist, and so does a way to switch back to an older model.

The weak spots are:

1. **The live models 2, 16 and 17 predate these records.** Most of their history is missing and cannot be recreated.
2. **The code that serves predictions does not check the file hash before using a model.** Only activation does.
3. **The production image does not pin library versions**, so a rebuild can quietly change a library.
4. **The drift check runs every week but never raises an alarm.** It cannot see an input formula change (the obv_slope case), and it only covers model 2.
5. **Some backups are not proven.** The restore drill is run by hand, the off-server copy of model files is off by default, and research model files sit only in local folders.

Open work already covers several of these: PRs #513 / #514, the promotion-safeguard branch, the card-integration branch, and issues #328, #256, #375 and #404. Two gaps have no issue yet. Proposed text for them is at the end.

## Work in progress (not duplicated here)

| Work | What it adds | State |
|---|---|---|
| PR #513 (`feat/328-card-slice2`) | `GIT_SHA` baked into the Docker image at build (Dockerfile, compose, `release.sh`, staging release), so cards made in production record a commit | Draft, open |
| PR #514 (`feat/328-card-slice2b`) | `brain/card_trainers.py`: sidecar `<artifact>.card.json` for the five-day and selection-lab trainers through wrappers. **Nothing calls the wrappers yet.** Test window and training-matrix hash are null there | Draft, open |
| Branch `feat/328-card-integration` (local worktree) | Switching callers to the #514 wrappers ("training integration") | In progress, no PR seen |
| Branch `feat/328-promote-safeguard` (local worktree, at `origin/main`) | The #328 `promote(model_id, approval)` wrapper: one activation path, recorded approver and evidence | In progress, no commits beyond main seen |
| Issue #328 (design) | Card at training, golden-output tests per formula version, one verified loader for every serving path, `promote()` with audit, champion / challenger report, card backfill for 2/16/17 | Open |

## Lifecycle table

| # | Item | Status | Evidence on `origin/main` | Gap | Mapped to |
|---|---|---|---|---|---|
| 1 | Training run ID | **INCOMPLETE** | `ml/registry.py:137-151` (`next_version`: a `vN` per name, never reused, "always identifies one training run"). The `ml_models` row is written in `ml/train.py:395-441`. Research runs carry an experiment id in their pre-registration (e.g. `r4-219-5d-largecap-v1`) | The card has no run-id field (`ml/model_card.py:193-229`). A failed training leaves no record: errors at `ml/train.py:332-362` raise before any row, and the failure goes only to logs and Telegram (`api/v1/endpoints/ml.py:169-173`). Walk-forward folds have no identity of their own. The fd / td / wf research rows use path-based names (catalogue doc, discrepancies 4-5) | #328 (card scope; a run id is not named in its acceptance criteria, so it should be added there) |
| 2 | Dataset fingerprint | **INCOMPLETE** | `ml/model_card.py:158-161` (`training_matrix_sha256`: training rows only), `:210-220` (data window, symbols plus `symbols_sha256`, row counts). Research path: `brain/lanes/r4_5d_run.py:364,438` add `data_snapshot_sha256` to research cards | Main path: no hash of the test matrix and no hash of the source data snapshot. Wrapped five-day and lab paths (PR #514): the matrix hash is null. Models 2/16/17: none (`docs/model-audit/2026-11-24-as-built-models-2-16-17.md`, D1/D3) | #328 (card fields; backfill for 2/16/17). #514 covers only the null-for-wrapped case |
| 3 | Feature schema version | **INCOMPLETE** | `ml/model_card.py:94-109` (names hash, golden-output hash on a fixed fixture, combined fingerprint), `:196-199` (`input_formula_version`, `feature_code_sha256`). The research feature set is pinned separately (`r4-fs53-obvvol-v1`). h05 lane checks `feature_code_sha256` (`brain/lanes/h05_models.py:94-96`) | Serving checks only the **names** (`ml/registry.py:129-130`), not the formula fingerprint. That is how the obv_slope formula change went unnoticed from 2026-10-06. Models 2/16/17 have no recorded formula version | #328 (golden tests per formula version, verified loader), #272 (input verification), #247 (train-to-scoring consistency) |
| 4 | Hyperparameters | **INCOMPLETE** | Defaults in `ml/train.py:58-102`. The card stores `train_args.hyperparameters` (`ml/train.py:382-389`) and the fitted class (`ml/model_card.py:205`). The registry row stores `hyperparameters` (`ml/train.py:421`) | Only caller **overrides** are stored (`hyperparameters or {}`). The defaults that were actually used are not recorded, so a later default change makes old rows ambiguous. They can be recovered from the pickled estimator (`get_params()`), but only while the file exists | #328 (the card should record the estimator's effective parameters; not named in #328 yet) |
| 5 | Dependency versions and random seeds | **INCOMPLETE** | Card: Python, lightgbm, scikit-learn, numpy, pandas (`ml/model_card.py:136-149`), seed (`:207`, `core/config.py:346` `ML_RANDOM_SEED = 42`). The h05 lane stops if sklearn or lightgbm versions change (`brain/lanes/h05_models.py:69-74`). Research lock file `backend/requirements-research.lock` (lightgbm 4.7.0, scikit-learn 1.9.1), used by the SX harness only (`backend/scripts/sx5_run.py:61`) | The **production image is unpinned**: `backend/pyproject.toml:44-45` use lower bounds (`>=`), and `backend/Dockerfile:21-22,44` builds wheels from them. A rebuild can change lightgbm or scikit-learn silently. The seed is recorded, but LightGBM runs with `n_jobs=-1` and no `deterministic` flag (`ml/train.py:58-74`), so two runs can differ (#219 had to pin this in research code). Only five libraries are recorded (not scipy or joblib) | Seeds / determinism: #328. **Prod dependency lock: no issue. Proposed new issue A below** (#399 covers only dev tools / mypy) |
| 6 | Code version | **INCOMPLETE** | `ml/model_card.py:112-133`: `GIT_SHA` env first, then `git rev-parse`, plus a tracked-files dirty flag | The code itself says that nothing in the repo sets `GIT_SHA` (`:115-116`), so cards made inside Docker have `sha = null`. The five-day and lab trainers write no card | **PR #513** (GIT_SHA at build), **PR #514** + card-integration branch (five-day / lab cards). No new issue |
| 7 | Artifact checksum | **INCOMPLETE** | Recorded after save (`ml/train.py:411-412`). Verified at activation (`ml/registry.py:98-131`, called at `:178`). Atomic, no-overwrite publish (`ml/registry.py:57-83`). h05 refuses a file whose hash differs from the frozen one (`brain/lanes/h05_models.py:123-125`). The backup manifest hashes every file (`ml/backup_manifest.py:38-95`) | Models trained before 2026-11-18 have no recorded hash and skip that check (`ml/registry.py:101-102`). **Serving paths load without verification**: `ml/predict.py:43-50`, `brain/reader.py:425-431`, `brain/modules/m06_reason/artifact.py:59-69` (keyed on mtime, no hash) | #328 (one verified loader for every serving path; `ml/predict.py` is trial-frozen, so this waits for the trial rules). #383 (safe version allocation and artifact publishing) |
| 8 | Evaluation metrics | **EXISTS** | `ml/train.py:180-193` (precision at the threshold, reliability table, calibration), `:369-373` (embargo, cut-off, walk-forward folds), `:430-436` (accuracy / precision / recall / F1 / AUC columns). Live outcome accuracy: `api/v1/endpoints/ml.py:302,381`. After-cost SELECTION / ECONOMIC verdicts: `brain/lanes/h05_verdict.py`, `brain/lanes/r4_5d_run.py`, evidence in `docs/model-audit/` | The training metrics are classification scores on one split, with no after-cost figure. After-cost verdicts exist only in the research lanes. Models 2/16/17: single unpurged split, no interval (as-built doc) | #328 (same-rows champion / challenger report). Nothing new |
| 9 | Model rollback | **INCOMPLETE** | `ml/registry.py:161-191`: activating an ARCHIVED version re-promotes it and archives the incumbent in one transaction, under a per-name lock, after the file check. API `api/v1/endpoints/ml.py:184-195`, gated by the release switch `core/release_switches.py:100-102`. Archived files are kept in backups on purpose (`ml/backup.py:15-17`). Code rollback on deploy: `infra/deploy/release.sh:22-52` | No record of who rolled back, why, or on what evidence (`ml/registry.py:186-190` sets only status and time). `activate_model` is still callable directly (CLI, `train_model(auto_activate=True)` at `ml/train.py:451-454`). Rollback works only while the old file is on disk or restorable | **Promotion-safeguard branch / #328** (`promote()` plus audit), #257 (verify rollback controls). No new issue |
| 10 | Model drift monitoring | **INCOMPLETE** | Feature-drift PSI per input, levels <0.10 / <0.25 / higher (`brain/modules/m09_learn/drift.py:67-135`). Run weekly on Saturday 10:00 IST (`workers/scheduler.py:370-374`, `brain/modules/m09_learn/learn.py:155-183`), stored, and shown in the weekly health check. Prediction reliability (Wilson, Brier, PSI flag, block bounds): `brain/prediction_reliability.py` | (a) **No alarm.** The weekly health check reports drift as `ok=True`, level "info", whatever the PSI (`services/brain_weekly_health.py:203-210`). (b) The **reference is rebuilt with today's feature builder** over the training dates (`drift.py:175-220`, build at `:206`), so a formula change is invisible to it. (c) It covers only `swing_classifier` (`drift.py:259`): models 16/17 are not checked. (d) It is skipped when M09 is off (`workers/jobs.py:831-855`). (e) **No scheduled outcome or performance drift**: `prediction_reliability.py` is a CLI (`main` at `:599`) and is not called from any scheduler or workflow | (b): #328 golden tests and #272. **(a), (c), (e): no issue. Proposed new issue B below** |
| 11 | Backup and restoration | **INCOMPLETE** | Database: nightly `pg_dumpall` with a 14-copy retention plus encrypted off-server copy (`infra/deploy/daily-backup.sh:1-60`, `.github/workflows/daily-backup.yml:9-10`, 23:00 IST). Models: daily copy at 16:30 IST (`workers/scheduler.py:222-228`, `ml/backup.py:74-129`, missing files alerted at `workers/jobs.py:586-600`) into its own volume (`docker-compose.prod.yml:45-50`). Encrypted, content-addressed off-server model copy plus manifest (`infra/deploy/backup-models-offsite.sh:1-25`). Restore checks: `infra/deploy/restore-drill.sh` (DB into a throwaway container) and `scripts/verify_restore.py` (DB plus every model file against the manifest) | The model copy is on the **same disk** (compose comment, `docker-compose.prod.yml:46-48`). The off-server model copy is **off by default** (`docs/BACKUP-OFFSITE.md:118`); whether it is on in production was not checked (no prod access). The restore drill is **manual only** (`.github/workflows/restore-drill.yml:12-13`, `workflow_dispatch`). `backup_models` is a silent no-op when `MODEL_BACKUP_DIR` is unset (`ml/backup.py:83-87`). Card sidecars from #514 are not in the backup (PR #514 note). **Research artifacts** (21 fd_h5, 21 td_h10, 20 wf_h15 files) live only in local worktree folders, and 130 wf_h15 registry paths are already dead (`2026-11-24-research-candidates-10d-15d.md`, discrepancies 4-5) | #256 (backup and restore readiness, incl. offsite recovery), #375 (alert when offsite becomes unavailable), #404 (visible skip when `MODEL_BACKUP_DIR` is unset). Research artifacts: covered by #256's scope ("model files"). Add a comment there rather than opening a new issue |

**Summary: 1 EXISTS (evaluation metrics), 10 INCOMPLETE, 0 MISSING.** Every item has some implementation. The gaps are coverage (legacy models, serving paths, the prod image, other trainers) and alerting, not the absence of a mechanism.

## Gaps by owner, without duplicating in-flight work

| Gap | Already handled by |
|---|---|
| Commit sha in Docker cards | PR #513 |
| Cards for the five-day and selection-lab trainers | PR #514 plus the card-integration branch |
| Single activation path with recorded approval (rollback audit) | Promotion-safeguard branch (#328) |
| Verified loader in serving, formula golden tests, card backfill for 2/16/17, champion / challenger | #328 (not yet started on main; `ml/predict.py` is trial-frozen) |
| Run id, effective hyperparameters, test-matrix and data-snapshot hashes, LightGBM determinism in the main trainer | #328: suggest adding these to its acceptance list (comment, not a new issue) |
| Backup proof, offsite state, silent skip, research artifacts | #256, #375, #404 |
| Prod Python dependency lock | **Proposed new issue A** |
| Drift alarm, coverage of models 16/17, scheduled outcome drift | **Proposed new issue B** |

## Proposed new issues (text only; not created)

### A. Pin production Python dependencies for reproducible model serving

> The production image builds from `backend/pyproject.toml` lower bounds (`scikit-learn>=1.5.2`, `lightgbm>=4.5.0`; `backend/Dockerfile:21-22,44`). Any rebuild can pick up new lightgbm, scikit-learn, numpy or pandas versions, which can change scores from the same model file. The h05 lane stops on such a change (`brain/lanes/h05_models.py:69-74`), but the v1 and brain serving paths do not notice.
> Scope: a hashed lock for the runtime image (or a constraints file), an image-build check that fails on drift, and the locked versions recorded in model cards. Do not regenerate the sha-bound `backend/requirements-research.lock` (PROTECTED, `docs/LEGACY-INVENTORY.md` DEP-01).
> Acceptance: two image builds from the same commit install identical versions (test). A test fails if a model-relevant library differs from the lock.
> Risk: a deploy-path change, so it needs a staging run and owner approval. Related: #328, #399.

### B. Model drift alarm, coverage of all live models, and scheduled outcome drift

> `brain/modules/m09_learn/drift.py` computes a weekly PSI, but the weekly health check always reports it as OK / info (`services/brain_weekly_health.py:203-210`). Only `swing_classifier` is checked (`drift.py:259`), so models 16 (mid) and 17 (small) are never checked. Outcome reliability (`brain/prediction_reliability.py`) exists only as a CLI.
> Scope: (1) a threshold (for example PSI ≥ 0.25 on an input the model relies on) that turns the check into a warning plus one Telegram line, never a trading action (decisions only move toward caution). (2) Run the drift check for every ACTIVE model. (3) A weekly scheduled run of the reliability report with its existing gates, written as a dated report.
> Formula-change detection stays with #328 (golden tests), because this check rebuilds its reference with today's builder.
> Acceptance: fixture tests for the threshold, multi-model coverage and the schedule. No change to trading, risk or the frozen files.
> Related: #328, #272, #387.

## Limits of this audit

* `origin/main` only. Production state (whether the off-server model copy is switched on, `MODEL_BACKUP_DIR` contents, actual library versions in the running image) was not checked.
* The open PRs and branches were read from PR bodies and branch heads, not reviewed line by line.
* Issue mapping used `gh issue list --search`. An issue with unrelated wording could have been missed.
