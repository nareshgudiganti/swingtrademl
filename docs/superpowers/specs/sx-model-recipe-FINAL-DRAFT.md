# SX model recipe — FINAL DRAFT (UNSIGNED)

Status: draft for owner review. Nothing here has been fitted, trained, calibrated, evaluated on the holdout, activated or
signed. Code: `backend/src/swing_trade_ml/ml/sx_recipe.py` (frozen dataclass, canonical JSON, sha256, `build_fit_fn`).
Tests: `backend/tests/test_sx_recipe.py` (random synthetic data only).

Tags: VERIFIED = read in code or measured on synthetic data in this session. PROPOSED = a choice made here for the
owner to accept. UNKNOWN = not established.

## 1. The recipe (one recipe, used by every arm: A_53, R_37, C_56)

| Item | Value | Status |
|---|---|---|
| Algorithm | `lightgbm.LGBMClassifier`, binary objective (the LightGBM default for a 2-class label) | VERIFIED: `ml/train._build_estimator("lightgbm")`; `brain/five_day_train.py` and `brain/ten_day._train` both reach it (`fit_and_score` / `train_model`, algorithm "lightgbm") |
| n_estimators | 400 | VERIFIED (train.py default) |
| learning_rate | 0.05 | VERIFIED |
| max_depth | 6 | VERIFIED |
| num_leaves | 31 | VERIFIED |
| subsample | 0.8 | VERIFIED value; see property P1: inactive |
| subsample_freq | 0 (not set; LightGBM default) | VERIFIED: train.py does not set it; installed default 0 |
| colsample_bytree | 0.8 | VERIFIED (active: changing the seed changes predictions) |
| min_child_samples | 50 | VERIFIED |
| reg_alpha / reg_lambda | 0.1 / 0.1 | VERIFIED |
| class_weight | "balanced" | VERIFIED |
| random_state | 42 | VERIFIED: `settings.ML_RANDOM_SEED` default 42; the harness pins seed 42 on a real run |
| n_jobs | 1 | PROPOSED. Production uses -1. The only deliberate departure from production, chosen for run-to-run determinism |
| verbose | -1 | VERIFIED (silences logging only) |
| Everything else | LightGBM 4.7.0 defaults (boosting gbdt, min_child_weight 0.001, min_split_gain 0, subsample_for_bin 200000, ...) | VERIFIED (read from the installed library) |

Verification: `test_recipe_values_match_the_production_defaults_in_ml_train` builds production's estimator and compares
every value (except the two intended or equal-by-default ones).

### Properties that are recorded, not changed

* **P1 — `subsample=0.8` does nothing.** LightGBM applies row bagging only when `subsample_freq` > 0. Production leaves it
  at 0, so row subsampling is inactive. VERIFIED on synthetic data: predictions with `subsample=0.8` are bit-identical to
  `subsample=1.0`, and differ once `subsample_freq=1`. The recipe keeps production's values on purpose so SX models are
  comparable to production-style ones. It is NOT silently fixed. (Open item O2.)
* **P2 — the scaler does not matter for trees** in principle (monotone per-column transform) but production applies it, so
  the recipe does too. Predictions can differ from an unscaled fit only through bin-boundary rounding.
* **P3 — seed matters.** `colsample_bytree=0.8` is active, so a different seed gives different predictions (VERIFIED). The
  seed is therefore part of the recipe (42) and the fit function refuses any other.

## 2. Preprocessing

* **StandardScaler**, fitted on the training rows passed to `fit` only, then applied to the test rows (VERIFIED: how
  `ml/train.fit_and_score` does it). Test: mutating test rows leaves scaler mean/scale and training predictions unchanged;
  a fit on the same training rows is unaffected by what the other rows hold.
* **Missing values.** LightGBM would route NaN natively, but the pipeline never gives it any: `ml/dataset` drops rows
  with a NaN feature or target (VERIFIED, `dropna(subset=[*FEATURE_COLUMNS, "target"])`), and the harness
  `_validate_matrix` refuses a matrix with any missing input, label or forward return (VERIFIED). `sx_recipe` additionally
  refuses NaN/inf in `X_train` or `X_test`. No imputation anywhere.
* **Class imbalance.** `class_weight="balanced"` is computed by scikit-learn from the labels of the rows given to `fit`, i.e.
  the training rows only (VERIFIED: a fit with explicit `compute_sample_weight("balanced", y_train)` and no class_weight
  gives bit-identical predictions).
* **Feature ordering and selection.** The exact ordered column list per arm comes from the arm manifests of the harness
  (`build_arms`); the recipe selects nothing and reorders nothing. The list hash is bound per arm in the holdout registry.

## 3. Training and validation windows

* **Harness (what SX uses).** Expanding window, retrained once per fold; training rows are those whose whole label window
  ends before the test window starts, and whose decision day is at least `embargo` sessions (= horizon) before the test
  start (VERIFIED, `sector_walkforward.split_for_fold`). ALL such rows are passed to `fit_fn`; **no inner validation split is
  used** (the harness helper `inner_chronological_split` exists but nothing calls it).
* **Production-style models (for reference).** `five_day_train` and `ten_day._train` split chronologically by DATE at 80% / 20%
  (`ML_TRAIN_TEST_SPLIT` code default 0.2, `ml.dataset.chronological_split` with label-window purge), fit on the 80% only, and
  score the 20% only to report metrics. The 20% is not used to choose anything and the model is not refit on all rows
  (VERIFIED). So production-style models train on 80% of the available history, whereas an SX fold model trains on 100% of
  the rows allowed by the purge/embargo rule. This is a real difference between SX and the production models (Open item O3).

## 4. Early stopping, tuning, calibration

* Early stopping: **none** (no eval set is passed; VERIFIED in `fit_and_score`'s `calibrate=False` path).
* Tuning: **none, of any kind.** Hyperparameters are fixed in advance by this document. No tuning on development folds, the
  holdout or the sealed trial; no seed shopping; no feature selection. Any change creates a new recipe hash and needs a new
  owner decision before the holdout authorisation, never after.
* Calibration: **none** (`calibrate=False`, as `five_day_train` records "calibrated": False). Scores are used for ranking only.

## 5. Determinism

* Same data, same seed, two fits: identical predictions (VERIFIED on synthetic data, `n_jobs=1`).
* `n_jobs=4` gave identical predictions in one synthetic check, but that is not guaranteed by LightGBM (floating-point
  summation order across threads); hence `n_jobs=1`. UNKNOWN whether other CPUs / OS / builds reproduce bit-identical
  results: predictions can differ across platforms, compilers and library versions. The recipe hash therefore includes the
  library versions, and `build_fit_fn` refuses to build when the installed versions differ.
* Versions recorded (VERIFIED, `pip list` of the project venv, Python 3.12.6, Windows 11): lightgbm 4.7.0, scikit-learn
  1.9.1, numpy 2.5.4, pandas 3.1.0, scipy 1.18.1.
* **Recipe sha256 (this machine, these versions): `fa6b3e974f62a20a8363e3ceef34105b728bcf1b3a0fe502e2aa05d00e501233`.**
  Any other version set gives a different hash by design; the real run must happen in the environment named in the signed
  protocol, and the hash be recomputed there.

## 6. Guards in the code

* `build_fit_fn(recipe, spec=, approval_path=)` refuses unless sector_research's approval file names this exact DatasetSpec
  (`ResearchApprovalRequired`), and refuses on a library-version mismatch. In this session no approval file exists and no
  real data is read.
* The returned function refuses a wrong seed, NaN/inf, a single-class label, and (unless `allow_real_data=True`) a matrix
  stamped `inputs_source == "database"`. The stamp is best effort; the harness approval gate and the holdout registry are
  the real guards.
* `fit_fn.recipe_sha256` is what the harness passes to the holdout registry as the per-arm fit-recipe hash.

## 7. Open items for the owner

* O1. Accept or amend the hyperparameters in section 1 (all equal production defaults). Any amendment must happen before
  signing and changes the hash.
* O2. P1: keep `subsample` inert exactly like production (recommended for comparability), or activate it (`subsample_freq=1`)
  as a new, different recipe. Do not change after seeing any result.
* O3. SX folds fit on 100% of purged training rows while production models fit on 80%. Accept (recommended: the 80% cut
  exists only to produce a held-back metric) or ask for an 80% rule for symmetry.
* O4. `n_jobs=1` (determinism) versus production's -1: accept.
* O5. Which environment (machine, Python and library versions) the real run uses; the recipe hash must be recomputed there.
* O6. Whether R_37's column list comes from the saved model-2 artifact (UNKNOWN today; the harness derives it) or the derived
  list; the arm manifest hash is what gets signed.
* O7. LightGBM `deterministic=True` / `force_row_wise=True` were NOT added (production does not use them). Add only if the
  owner wants stronger reproducibility guarantees, as a new recipe.
