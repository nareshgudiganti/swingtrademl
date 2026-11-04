# SX10 research protocol — DRAFT FOR OWNER APPROVAL (unsigned, untagged)

Date: 2026-11-05. Status: **DRAFT. Not signed, not tagged, no model trained, no model fitted, nothing activated.**
Labels in this file: **VERIFIED** = read from code, data or a signed/published document in this session; **PROPOSED** = my suggestion for the owner to accept or change; **UNVERIFIED** = not checked.

## Update 2026-11-06 (owner decisions): the challenger becomes C_56, and R_37 is verified and labelled

**What changed.**
1. **C_56 replaces the 57-input challenger (renamed from C_57).** `sector_ret_20d_vs_nifty` is removed from the challenger (53 + 3 = 56 inputs). It equals `relative_strength_20d - sector_relative_strength_20d` (two existing inputs) on 45,917 of the 45,930 audited rows. The other 13 rows (all APOLLOHOSP, 2022-09-26 to 2022-10-31, max difference 0.0316) differ only because the NIFTY HEALTHCARE index has no close on seven trading days (2022-09-26, 09-27, 09-29, 09-30, 10-03, 10-04, 10-06) while NIFTY 50 and the stock traded: the existing inputs take a 20-ROW return of that index, the sector input a 20-SESSION return of the shared calendar. Same closes, different window: a definition difference, no new information (`c56_decision_v3.json`). A_53 and R_37 are NOT changed.
2. **Rows: +5 per candidate.** In the earlier lists five APOLLOHOSP rows (2022-10-27, 11-01, 11-02, 11-03, 11-04) were dropped only because `sector_ret_20d_vs_nifty` was missing across that same gap. Without that input they are eligible, so the eligible rows are **45,935 (SX5) and 45,700 (SX10)** instead of 45,930 and 45,695; sector-gap removals fall from 15 to 10 (APOLLOHOSP). All five new rows are in 2022, so every fold's test rows are unchanged; only training rows grow by 5. Nothing else in the reconciliation changed (HUL event-window rows, existing-input gaps, full-49 lists). The arms still get identical rows. New files: `reconciliation_v3.*`, `*_rows_v3.txt.gz`, `sector_coverage_sx_v3.json`, `arm_row_counts_v3.json`, `sx*_fold_coverage_v3.csv`, `feature_overlap_v3.json` (the v1/v2 files are untouched).
3. **New row-list sha256 (this candidate):** `d10ef048f52a7bfe377472ff51814f8f3710998a5847f3159e7ae66fe359b444` (was `e5faf7950d9e8bb25f65ba9a3a6a18703e4499ec4333a1901a5d38560c2ce2f5`).
4. **Configuration hash.** `DatasetSpec.config_sha256` includes the column list, so it changes when 57 columns become 56. For the real specification (47 mapped stocks, `excluded_rows_h*_v2.csv`, cut-off 2026-12-31, protocol label) the hash prefix is now `3c1507a9324b9341` (the former 57-column challenger gave `0bc871cf132265fd`). No approved configuration exists, so no approval is invalidated; the owner's approval file (A9) must name the new hash.
5. **Overlap of the remaining three new inputs with the 53** (`feature_overlap_v3.json`, in-sample linear R-squared on all 53): `stock_vs_sector_10d` 0.83, `sector_ret_10d_vs_nifty` 0.74, `sector_rank_10d` 0.50 (unchanged to the printed precision). Against the five relative-strength / sector-regime inputs only: 0.64, 0.67, 0.43.
6. **R_37.** Verified against the saved list of production model 2: 37 names, same order, no difference. Labelled `R_37: a 37-feature RESEARCH REFERENCE, not an exact production replay` because `obv_slope` is built differently now than at training. Models 16 and 17 both save 46 names (the 53 minus `sector_relative_strength_5d`, `sector_relative_strength_20d`, `sector_trend_regime`, `vix_change_5d`, `vix_percentile_rank`, `breadth_pct_above_sma50`, `breadth_advance_pct`), in the order of the 53. Hyper-parameters are `{{}}` in the registry rows for all three. Evidence: `model2_saved_features_v1.json`.

**Where the numbers below still show the earlier values** (counts of 45930 / 45695, hash `a862...` / `e5fa...`, "four inputs", "57"), they are the earlier v2 figures; the numbers in this update replace them.

## Update 2026-11-07 (owner decisions, verification and limitations; UNSIGNED)

**Owner decisions (2026-11-07).** C_56 is accepted. The eligible population is **45,700 rows** for SX10: no artificial exclusion rule is added to preserve the old count (45,695). The new configuration hash (`3c1507a9324b93417f3f9000e431778da944eb817a7631070112a96455842be5`) and row-list hash (`d10ef048f52a7bfe377472ff51814f8f3710998a5847f3159e7ae66fe359b444`) are accepted **subject to the complete hashes and dataset manifests being verified before signing**. That verification was run on 2026-11-07 (read-only, nothing trained): `docs/brain/evidence/sector_prep/final_verification_v3.md` and `final_hashes_v3.json`. R_37 stays a 37-feature **research reference, not an exact production replay**. The current `obv_slope` implementation is NOT changed.

**Superseded text.** Wherever this file still uses the old 57-input arm name, "four inputs", "57", 45,695, or the older hashes (`a862...`, `e5fa...`), that is the earlier v2 text and the numbers in this update replace it.

**Limitation L1: breadth survivorship (proposed text for section 4 caveat (a)).** "Market breadth (`breadth_pct_above_sma50`, `breadth_advance_pct`) is computed over today's 49 watchlist stocks for every past date. It is present in A_53 and C_56 identically and absent from R_37. Point-in-time index membership is not available locally. The comparison C_56 minus A_53 is unaffected by this construction. Comparisons involving R_37 are confounded by it and by VIX, and are descriptive only." (Measured in `2026-11-06-sx-presigning-findings.md` section 1: breadth over the 49 against all 306 stocks has correlation 0.895 for above-SMA50 and 0.876 for advance; production breadth uses the same watchlist, so this is about backtest realism, not train/serve skew.)

**Limitation L2: input-gap rows are a selection (proposed text for section 3).** "The 1,103 rows are 1,081 rows of one window (2022-08-11 to 2022-09-14, all 47 stocks, no VIX rank yet) and 22 rows where MFI is undefined after 14 straight up days. They are removed for all arms. 1,088 are before the first test fold and 15 are in test folds. The removal does not enter any comparison, but it removes one specific five-week rally window (breadth 0.87 against 0.60 for all development rows) from every arm's training data." (Findings section 2: identical across arms, no sector concentration.)

**Limitation L3: `obv_slope` and what R_37 is.** Training-era formula (models 2, 16, 17, trained 2026-08-05 to 08-20): `obv.diff(10) / obv.rolling(20).mean().abs()`, i.e. the 10-day change in on-balance volume divided by the absolute 20-day mean of the OBV LEVEL. Current builder since commit `fcaef35` (2026-10-05, first confirmed deployed 2026-10-06): `obv.diff(10) / volume.rolling(20).mean()`, i.e. divided by the 20-day mean VOLUME. Effects:
- Every research arm (A_53, R_37, C_56) is built with the CURRENT formula on the FULL stored history, so the three arms are consistent with each other and the paired comparison C_56 minus A_53 is not affected.
- The OBV level depends on how much history was loaded (it is a running sum), so the old denominator was not stable across history lengths; the new one is. The numerator `obv.diff(10)` does not depend on the starting level.
- R_37 therefore has the right 37 names in the right order (checked against the list saved in production model 2) but its `obv_slope` VALUES are not what model 2 was trained on. In addition R_37 is **retrained** under the SX recipe on the research rows, so it is not model 2's weights, scaler, hyper-parameters (the registry row holds `{}`) or training stocks. Conclusion: R_37 measures "the 37-input configuration under this recipe", never "production model 2"; no result may be described as production performance.
- Production serving uses the newest 400 bars (`ml/predict.py`), the research path and training use the full history, so the smoothed inputs (rsi_14, macd*, ema_*, atr_14_pct, adx_14, trend_strength) differ slightly early in the 400-bar window. This is a train/serve difference of production, not of this research.
- An exact comparison with production, if ever needed, is a **separate read-only audit** from a trusted source, in an isolated environment. The production joblib is not loaded here. Incident note: `docs/superpowers/specs/2026-10-30-obv-slope-incident.md`; evidence: `r37_semantic_drift_v1.json`.

## 0. The short version (plain English)

1. **The question.** Does adding the same three sector-strength numbers to the 10-day model help it rank the large stocks better than the 10-day model that failed in td-protocol-v1? The three numbers: the stock's sector-index return minus NIFTY 50's over 10 days, the sector's rank among 15 sector indices, and the stock's 10-day return minus its sector's. (A fourth, the same sector-minus-NIFTY return over 20 days, was dropped on 2026-11-06: it is the difference of two inputs that already exist.)
2. **How it is tested.** Three versions of the same model are trained on exactly the same rows, dates and folds: **A_53** (the 53 existing inputs; the primary baseline), **R_37** (the 37 inputs production model 2 uses; a separate reference benchmark) and **C_56** (the 53 plus three sector numbers; the challenger). Nothing else differs. All are scored on later days, one fold at a time (the model never sees the future).
3. **What it is not.** It does not change the live 5-day models, the h05 lane, the sealed 15-day trial, any signed protocol, or any order. No new algorithm, no new input family, no new trading rule, no tuning.
4. **What a good result means.** At most "worth a proper forward test", never proof: these stocks and this history have been looked at before (section 9).
5. **The stocks.** 47 of the 49 large stocks. ASIANPAINT and BHARTIARTL have no verified official sector index, so their sector numbers would be missing and they are left out (owner decision 2026-11-05). All three arms use exactly the same 47 stocks and rows, so the comparison is fair. What is lost versus the full 49 is reported in section 3.
6. **What you must still decide before anything is trained** is in section 12.

## 1. Question (one sentence)

Using only information known at the close of each trading day, does arm C_56 (the 53 existing inputs + three official-sector-index inputs) rank the 47 mapped large stocks better than arm A_53 (the 53 existing inputs), on identical rows and identical walk-forward folds (arm R_37, production model 2's 37 inputs, runs on the same rows and folds as a separate reference benchmark), for the 10-day question of td-protocol-v1 (reach +6% before -3.5% within 10 trading days)?

## 2. What stays unchanged (VERIFIED boundaries)

- The official h05 lane (disabled, protocol unaccepted), prod models 2, 16, 17 (ACTIVE), the sealed 15-day trial, `wf-protocol-v1`, `fd-protocol-v1`, `td-protocol-v1` (signed), the unsigned `td-protocol-v2` draft, Phase B and the selection lab.
- `ml/features.py`, `ml/predict.py`, `ml/sector_map.py`, `ml/dataset.py`, `ml/train.py` are read only. Nothing fingerprinted in `backend/tests/trial_freeze.json` is edited (that test passes).
- The 129 held-back stocks are not used. The Phase B reject set is not used. The v1 data and trading path are untouched.

## Isolation (VERIFIED in code, tested)
- The research models never enter `ml_models`, the production model directory, the model registry (`ml_models` table), production scoring (`ml/predict.py`), the h05 lane, the brain, strategies or orders.
- Code: `backend/src/swing_trade_ml/ml/sector_research.py` (dataset and approval mechanism), `ml/sector_walkforward.py` (the walk-forward harness: folds, purge, three arms, metrics, immutable records; it contains NO model recipe, the fit function is injected) and `ml/feature_audit.py` (read-only audit helpers). Nothing in the app imports them; a test enforces that. It reads the existing feature code (`ml/features.py`, read-only) and the one sector builder (`ml/sector_features.py`).
- Output goes only under `backend/data/research_models/<candidate>/<version>_<artifact sha>/` (gitignored) with a `manifest.json`. The writer refuses the production model directory and any path containing `ml_models`. Nothing is written to the database.
- ASIANPAINT and BHARTIARTL stay UNMAPPED: their three sector inputs are missing (never 0), and `include_unverified` is not exposed by the research path at all.
- Training requires an **approval file** (JSON; path in `SECTOR_RESEARCH_APPROVAL_FILE` or the `approval_path` argument) with `protocol_id`, `approved_by`, `candidate`, `config_sha256`. `config_sha256` must equal the hash of the exact `DatasetSpec` (symbols, horizon, label rule, cut-off, the exact exclusion list, columns, version). Any change to rows or settings changes the hash and the approval stops matching. Without a matching file the function only returns a dry-run plan. The model recipe is NOT in the module: the signed protocol supplies it as `fit_fn`.

## 3. The data (VERIFIED, reproducible; reports in `docs/brain/evidence/sector_prep/` with `_v2` names, v1 files kept)

Universe: the 49 model stocks (`stock_split_ev15.json`, `used_49`), local daily candles 2021-08 to 2026-09-07 (indices run to 2026-09-09). Sector rule: the stock's official NSE sector index from `ml/sector_map.py`. Unmapped: ASIANPAINT, BHARTIARTL. APOLLOHOSP loses 15 rows because NIFTY HEALTHCARE history is missing for a few sessions.

**Corporate-action policy (owner decisions 2026-11-05).** RELIANCE 2023-07-20 and ITC 2025-01-06: histories verified adjusted, rows RETAINED (category `RETAIN_VERIFIED_ADJUSTED`, flagged in the report). HINDUNILVR 2025-12-05: pending fresh fetch; its feature window (253 rows, both ends included) and label window are removed. BAJAJELEC 2023-09-14 is not in the 49. Genuine and provisional events stay retained.

**Row reconciliation, 10-session horizon** (each row counted once, first reason wins, in the order of the columns; overlaps in `reconciliation_v2.md`):

| Set | Raw rows | Warm-up | Label unknown | HUL event window | Existing-input gap | Sector gap | **Final** | sha256 |
|---|---|---|---|---|---|---|---|---|
| (i) SX universe, 47 mapped | 59314 | 11844 | 470 | 187 | 1103 | 10 | **45700** | `d10ef048f52a7bfe377472ff51814f8f3710998a5847f3159e7ae66fe359b444` |
| (ii) full-49 baseline (existing inputs only) | 61838 | 12348 | 490 | 187 | 1149 | 0 | **47664** | `2a4cf9e4b4dd1b0a8a0a90a14b9ee6f83b82d7296c67376b32b9c22d78a5f852` |
| (iii) matched baseline (existing inputs on exactly the rows of (i)) | - | - | - | - | - | - | **45700** | `d10ef048f52a7bfe377472ff51814f8f3710998a5847f3159e7ae66fe359b444` (same row list as (i)) |

- The 187 removed HINDUNILVR rows split as {'label': 10, 'feature': 177} (feature and label windows). The earlier review's prediction is reproduced exactly: buildable 49000, excluded 187, retained 48813, sha256 `5bd1c1884a727fe036e3f05bdd39c793450cb7db1d50daf6da7d985316d0f842` (49 stocks, before the existing-input and sector stages).
- The "existing-input gap" (1103 rows in the 47) is a stage the earlier prediction did not have: the first ~23 sessions after the 252-session warm-up lack a VIX percentile rank (INDIA VIX starts 2021-09-13), plus a few missing MFI values (checked on two stocks, MARUTI and HINDUNILVR; full per-column counts are in the JSON). Removed for both arms.
- Event windows that also have a sector gap: 0 rows. Event versus event: none.
- **Coverage loss of the SX universe versus the full-49 baseline:** 1964 rows (4.121%): {'APOLLOHOSP': 10, 'ASIANPAINT': 977, 'BHARTIARTL': 977}. The full-49 baseline (ii) is a SEPARATE reference; no A-versus-B comparison uses it.
- **Matched baseline (iii):** model A's rows are exactly (i)'s rows, and (iii) is a subset of (ii) (checked). A and B have identical eligible universes by construction (the reconciliation script checks that the matched rows are a subset of the full-49 rows; the row lists are the same file).
- Cross-check: the research assembler `assemble_training_matrix` produces exactly the same 45700 rows as this reconciliation (identical row sets, 0 differences).
- Canonical row lists: `sx10_47_rows_v3.txt.gz` (v2 kept: 45695 rows) and `full49_h10_rows_v2.txt.gz` (sorted `SYMBOL|YYYY-MM-DD`, newline separated; the sha256 is over the decompressed text).

## 4. Exact model recipe (VERIFIED from prod GET /ml/models/2, 16, 17 and the code)

| Item | Value |
|---|---|
| Algorithm | LightGBM `LGBMClassifier` (prod rows 2, 16, 17 all `lightgbm`) |
| Hyperparameters stored on the prod rows | empty: the code defaults of `ml/train._build_estimator` apply |
| Fixed hyperparameters (code defaults) | n_estimators 400, learning_rate 0.05, max_depth 6, num_leaves 31, subsample 0.8, colsample_bytree 0.8, min_child_samples 50, reg_alpha 0.1, reg_lambda 0.1, n_jobs -1, verbose -1 |
| Class weighting | `class_weight="balanced"` |
| Seed | `random_state = settings.ML_RANDOM_SEED`, code default **42**. A local `.env` can override it, so the research run must pin 42 explicitly and refuse otherwise |
| Scaling | `StandardScaler` fitted on the training rows only |
| Calibration | none (`calibrate=False`; prod `calibrated: False`) |
| Fold fit | `fit_and_score` on the chronological, label-purged first 80% (`ML_TRAIN_TEST_SPLIT` code default 0.2) of the rows up to the fold cut-off, exactly as `brain/five_day_train.train_endpoint_model` and `brain/ten_day._train` do. The last 20% before the cut-off is only that fold's internal check |
| Tuning | **none**. Every number above is fixed in advance: no search, no early stopping, no feature selection |
| Prod sizes | model 2: 48,145 samples, 49 stocks, 37 inputs, trained to 2025-10-09; model 16: 22,691 samples, 24 stocks, 46 inputs; model 17: 28,418 samples, 30 stocks, 46 inputs |
| Subtlety (UNVERIFIED by test) | LightGBM ignores `subsample` unless `subsample_freq` > 0 and the code does not set it, so row subsampling is probably inactive while `colsample_bytree` is active. Reproduced as is. `n_jobs=-1` may differ slightly between machines: record the library versions and the artifact sha256 |

**Inputs (owner decision 2026-11-05; replaces the former open question A2).** The current code (`FEATURE_COLUMNS`) has **53** existing inputs, not 46. The prod models use **37 (model 2, large caps) and 46 (models 16, 17)**: their saved lists are subsets of the 53. The primary matched baseline A_53 is the 53; R_37 is model 2's 37-input configuration, kept as a separate production-reference benchmark; C_56 adds three sector inputs (`sector_ret_10d_vs_nifty`, `sector_rank_10d`, `stock_vs_sector_10d`) to the 53 (a fourth, `sector_ret_20d_vs_nifty`, was dropped on 2026-11-06: see section 4 and `c56_decision_v3.json`). **R_37's list is now VERIFIED against the prod row (2026-11-06)**: the saved `feature_names` of model 2 (read-only GET /api/v1/ml/models/2; `docs/brain/evidence/sector_prep/model2_saved_features_v1.json`) are exactly 37 names in exactly the same order as the 37 columns of the very first `FEATURE_COLUMNS` (git `7da460c^`), which equal the 53 minus the 16 inputs that `2026-10-30-model-facts-corrections.md` (C1) says model 2 lacks (that note says "4 newer technical"; the difference is 5: days_since_52w_high, days_since_52w_low, streak, volatility_percentile_rank, cmf_20; the total of 16 agrees). No difference in names, order or count. **R_37 is labelled `R_37: a 37-feature RESEARCH REFERENCE, not an exact production replay`**: the names and order are the saved ones, but the values built by today's feature code differ from model 2's training values for `obv_slope` (formula changed in fcaef35, 2026-10-05; `2026-10-30-obv-slope-incident.md`). Other inputs of the 37 are identical to the training-era code (tested). The saved scaler and booster are not available locally, so scaling and tree settings are not compared. The harness still takes the list as a parameter.

| Arm | Inputs | Role |
|---|---|---|
| **A_53** | the 53 existing inputs (`ml/features.FEATURE_COLUMNS`) | **primary matched baseline** (owner decision 2026-11-05) |
| **R_37** | the 37-input configuration of production model 2 (a subset of the 53) | **separate production-reference benchmark**; never the baseline of the A_53 versus C_56 comparison |
| **C_56** | the 53 plus three sector inputs (renamed from C_57 on 2026-11-06; `sector_ret_20d_vs_nifty` dropped) | the challenger |

All three arms use IDENTICAL eligible rows, dates, folds, seed, costs and evaluation metrics (enforced and tested in the harness: each arm receives the same row list, the same label and only its own columns; the run is refused if any arm's rows, folds or evaluated days differ). The 53 are the primary baseline **provided they pass the feature-availability and leakage checks**; they did (below, "Feature availability and leakage check").

**Overlap of the four originally proposed new inputs with the 53 (VERIFIED, before the 2026-11-06 drop of `sector_ret_20d_vs_nifty`; pooled stock-days on the 45,930 SX5 eligible rows; script `backend/scripts/feature_availability_report.py`, data `docs/brain/evidence/sector_prep/feature_audit_53.json`).** The 53 already hold `sector_relative_strength_5d/20d` (the stock minus its sector) and `sector_trend_regime`. The new inputs are mostly not those, but one is a combination of existing inputs: `sector_ret_20d_vs_nifty` equals `relative_strength_20d - sector_relative_strength_20d` (two existing inputs) on 45,917 of 45,930 rows (the other 13 differ by at most 0.032: calendar alignment), so it carries **no information beyond the 53** (a tree model may still use it differently, but a gain from it alone would be surprising). `stock_vs_sector_10d` is a 10-day version of the existing sector relative strength (Pearson 0.69 with the 5-day and 0.70 with the 20-day existing input; 0.72 with `return_10d`). `sector_ret_10d_vs_nifty` and `sector_rank_10d` correlate at most 0.44 and 0.36 with any single existing input (both with `return_10d`). Linear R-squared of each new input on all 53 (in-sample, descriptive): sector_ret_20d_vs_nifty 1.00, stock_vs_sector_10d 0.83, sector_ret_10d_vs_nifty 0.74, sector_rank_10d 0.50. So the genuinely new content is mostly the sector's own 10-day move and rank; a small gain is the expected case. (Computed on the SX5 rows; the SX10 rows differ by 235 rows, so the SX10 figures are expected to be the same to the printed precision, not separately computed.)

**Feature availability and leakage check of the 53 existing inputs (VERIFIED, read-only, local data; the 49 stocks and the 47 mapped).**
- Availability after the 252-session warm-up (47,470 stock-days in the 47): 50 of the 53 inputs have no missing row. Missing rows: `volatility_percentile_rank` 893 (rolling 252-day rank of a 20-day volatility, first valid 2022-09-09), `vix_percentile_rank` 1,081 (INDIA VIX starts 2021-09-13; rolling 252-day rank, first valid 2022-09-15) and `mfi_14` 22 isolated rows (for example AXISBANK 2022-11-30, BAJAJFINSV 2024-09-04, BPCL 2023-05-05). The three together are the 1,103 "existing-input gap" rows of section 3 (893 and 1,081 overlap on the early rows). No input is missing for a whole stock. Per-input first-valid dates are in the JSON.
- Point-in-time test of the EXISTING builder (`ml/features.build_features`, unedited): for 49 stocks x 25 cut days (1,225 stock-days, 53 inputs each) the features of day t built from data cut at t equal the features of day t built from the full history (relative tolerance 1e-7): **0 mismatches in all 53 inputs**. This covers the rolling percentile ranks, the 52-week inputs, the VIX rank, the sector relative strength through `merge_asof` and `obv_slope`. A second test wrecks every stock, index, VIX and breadth value after a day T and confirms that no input on or before T moves (12 stocks, 0 changes). The tests can fail (a deliberately leaking builder is caught). **No input fails.**
- Caveats that are NOT look-ahead but stay visible: (a) market breadth is built from today's watchlist applied to past days (a survivor/selection effect; values at t use only data up to t); (b) production computes `obv_slope` differently from how models 2, 16 and 17 were trained (since 2026-10-05; see the 2026-10-30 obv-slope note): all research arms use the CURRENT builder, so the comparison is internally consistent, but arm R_37 is not a replica of production model 2's trained behaviour; (c) the first ~23 sessions after the warm-up lack a VIX rank for every stock (removed for all arms).

**Label (td-protocol-v1 barrier label, VERIFIED).** Barrier: `target = 1` if the stock reaches +6% before -3.5% within 10 trading bars (`ml/features.build_label` barrier rule; `ten_day.TARGET = 0.06`, `STOP = 0.035`, `HORIZON_BARS = 10`). A same-bar touch of both levels scores as the stop. The last 10 sessions of each stock are dropped.

**Code status (updated 2026-11-05; VERIFIED by tests).** `DatasetSpec` now has `label_kind`; SX10 uses `barrier` with target 0.06 and stop 0.035 over 10 bars, and its labels equal `ml/features.build_label(..., 10, 0.06, 0.035)` as used by `ten_day` (tests: synthetic data, an independent loop reference, and real local data for five stocks on every date, SELECT only; `ten_day.TARGET`, `STOP` and `HORIZON_BARS` are asserted equal to the SX10 settings). Adding the field adds one key to the configuration, so every `config_sha256` changes; removing it reproduces the previous hash exactly (pinned in a test). No approved configuration exists, so no approval is invalidated. The walk-forward harness exists (section 5) and has been tested with stub models and synthetic data only; no model has been fitted on any real SX data. Still not built: the signed `fit_fn`.

*Superseded text, kept for the record:* `sector_research.assemble_training_matrix` builds the label with `build_label` (the barrier rule) for both candidates and `DatasetSpec` has no label-kind field. SX10 uses the barrier rule with target 0.06 / stop 0.035, which the module already supports; the `DatasetSpec` must carry those values (the test fixtures use 0.02 / 0.02). The walk-forward evaluation harness and the `fit_fn` are not in the repo yet; they are the next build step after approval.

## 5. Walk-forward design (PROPOSED; counts computed from the eligible rows)

- **Development folds:** 28-calendar-day test windows, back to back, 2023-07-01 to 2026-01-31 (`selection_lab.make_folds`, the `wf-protocol-v1` windows). Each fold's model is trained on rows whose label had resolved before the fold started (`label_end_ts < test start`; embargo = 10 sessions), retrained once per fold, expanding window. **Harness rule (implemented; property-tested over random fold configurations):** a training row is used only if its whole label window ends before the test window starts (no overlap with the test window) AND its decision day is not among the last 10 sessions before the test start; test rows are those decided inside the 28-day window. On the real eligible rows the embargo removes no row beyond the purge (0 rows), so the purge alone defines the training set. Training uses the injected `fit_fn` only; the harness has no default recipe. The holdout marker file makes a second holdout run impossible (a crash does not reset it). All three arms use the same folds, rows, seed, costs and metrics.
- **Final holdout:** 2026-02-01 to 2026-08-15, scored once at the end, **never used for choosing anything** (nothing is chosen: there is no tuning). Rows after 2026-08-15 are unused (label buffer).
- Eligible rows run from 2022-09-15 to 2026-08-24 (45700 rows, 45 to 47 stocks every day).

**Predicted test coverage (computed, VERIFIED on the final eligible rows):**

| | Folds | Test days | Test rows | Days per fold | Training rows per fold (after purge) |
|---|---|---|---|---|---|
| Development folds | 34 | 642 | 30,111 | 13 to 21 | 8720 (fold 1) to 38243 (fold 34) |
| Final holdout | 1 | 133 | 6,118 | 133 | all development rows |

Per-fold table: `docs/brain/evidence/sector_prep/sx10_fold_coverage_v3.csv`. Re-computed by the harness's `plan_folds` (no fit): identical counts, and every arm has the same rows in every fold (`docs/brain/evidence/sector_prep/arm_row_counts_v3.json`: A_53, R_37 and C_56 all 45,700 rows, 0 missing values in any arm's columns). All 34 folds have at least 10 test days. Best-5 ideas are at most 5 per test day; the number after the no-repeat rule is NOT computed.

**Minimum detectable edge: not computed.** The repo's `brain/lanes/h05_power.py` simulates the h05 forward lane from a database table of model scores; it does not apply to a paired walk-forward comparison. For context only, the td-protocol-v2 draft cites about +0.12% per trade at 396 days of 5 picks (10D analysis); a naive square-root scaling to 642 days gives about +0.09% (UNVERIFIED; ignores dependence between days). A paired difference between A and B is smaller and noisier than either alone, so INCONCLUSIVE is a likely outcome and is stated in advance.

## 6. Metrics (all computed by the same code on the same rows for every arm: A_53, R_37, C_56)

1. **Daily rank IC:** Spearman correlation per test day between the model score and the 10-day trade result over that day's eligible stocks (the `selection_lab.daily_ic` definition; days with fewer than 10 stocks left out).
2. **Top-5 hit rate:** share of each day's 5 highest-scored stocks whose label is 1, next to the every-stock hit rate that day.
3. **Excess benchmarks** (as `evidence-defs-v2`): average daily result of the top 5 minus **every eligible stock**, minus **random-5** (200 seeded draws), and against **NIFTY 50** held over the same days.
4. **Paired differences** on each of the above, per day, so the same days and stocks are compared: **C_56 minus A_53 is the primary pair**; A_53 minus R_37 (what the extra 16 existing inputs add) and C_56 minus R_37 are descriptive. Block bootstrap over days: td-protocol-v1 section 5 (block 10), 2,000 draws, seed 7, 5th percentile as the lower bound.
5. **Economic result after costs:** `ten_day.score_trade` exactly (+6% / -3.5%, 10 bars, no half-out, entry at the next open, stop before target, 0.10% slippage per side in total, charges on the shared scorer's Rs 40,000 position), as td-protocol-v1 section 5 permits for the history gate. Reported beside the ranking result; the pass rule below is ranking-based.
6. Per-fold results, worst fold, market-type split (rising / sideways / falling windows, `selection_lab.market_label`), hit rate needed to break even.

## 7. Pass/fail rule — PROPOSED (no number is agreed until you accept it)

Copied BY REFERENCE, not re-decided: td-protocol-v1 section 5 (eligible fold: at least 10 test days and 20 finished best-5 ideas; at least 12 eligible folds and 100 ideas else INCONCLUSIVE; 60% of eligible folds; block bootstrap 2,000 draws, seed 7) and its benchmarks. Rows marked NEW are not in any signed protocol.

| Row | Needs | Source |
|---|---|---|
| R0 Same rows | the A_53, R_37 and C_56 eligible row lists are identical (equal sha256; the harness refuses to run otherwise) | NEW |
| R1 Paired skill | C_56 beats A_53 on the daily top-5 excess over every eligible stock in at least 60% of eligible folds | NEW row; the 60% is borrowed |
| R2 Paired lower bound | 5th percentile of the mean daily difference (C_56 minus A_53) is above zero | NEW row; bootstrap settings borrowed |
| R3 Enough data | at least 12 eligible folds and at least 100 finished best-5 ideas, else INCONCLUSIVE | borrowed |
| R4 Holdout agrees | the paired difference on the final holdout has the same sign (reported; not a second chance to pass) | NEW |
| R5 No harm | C_56's worst fold versus A_53's worst fold (and R_37's) is shown (descriptive; no numeric threshold invented) | NEW, descriptive |

Outcome words: **IMPROVES** (R0 to R4 all met), **NO IMPROVEMENT** (enough data and R1 or R2 not met), **INCONCLUSIVE** (R3 not met). IMPROVES only means "worth proposing a forward shadow test"; it never activates anything. A null or negative result is stored with equal prominence. Nothing is changed after a result is seen.

## 8. Experiment register and multiple testing (PROPOSED entry for `docs/brain/EXPOSURE-LEDGER.md`)

- The entry is written BEFORE any model is trained: candidate SX10, rows hash, config hash, folds, seed, date, "no outcome read".
- Count: this is **one** pre-registered paired comparison (one change, three inputs; one horizon). With SX5 it makes two. In the wider programme the signed or drafted candidates are Phase B 3 + selection lab 6 + the td-protocol-v2 draft B1 (if signed) + SX5 + SX10, i.e. 11 to 12 comparisons on largely the same prices.
- Multiple-testing note (illustration; assumes independent tests at 5%): the chance that at least one of 11 passes by luck is about 43% (1 - 0.95^11); for these two alone about 10%. This is why a result can only justify a forward test, and why the primary metric is fixed (R1, R2) while IC and hit rate are descriptive.
- Relation to td-protocol-v2's B1 (breadth + four sector inputs): SX10 is the sector-only half of B1 (inputs B1-5 to B1-8). If SX10 is signed, B1 should be re-scoped or retired so the same idea is not counted twice. The owner decides (A5). The exact differences between the two (label, inputs, folds, evaluation, universe, status) are listed in `2026-11-05-sx10-vs-tdv2-b1-differences.md`; no combination and no reuse of results is proposed, and the td-protocol-v2 draft is unchanged.

## 9. History already seen, and the earlier failure (kept visible)

- **td-protocol-v1 FAILED on 2023-07-01 to 2025-01-31 (VERIFIED, `docs/brain/evidence/td_v1/ten_day_2023-07-01_2025-01-31.md`):** picks beat every stock in 8 of 21 eligible folds (lower bound -0.31%); average -0.34% per trade over 1,980 finished ideas against -0.22% for every stock; NIFTY 50 held -0.18%; reading: no evidence of skill and no profit. That result stays on record; SX10 does not replace or re-run it and is not a re-tune (target, stop, horizon, top 5, costs are td-v1's).
- The td-protocol-v2 draft says no unseen 10-day history is left. A and B see the same data, so the comparison is fair, but a pass cannot be called independent proof. The 47 stocks are today's names (survivor bias) and no liquidity or circuit-limit modelling exists.
- Every month since 2021-09 has been used for some study; the exposure-ledger row records this.

## 10. Index availability at decision time (VERIFIED from code and local data; arrival times UNKNOWN)

Full note: `docs/brain/evidence/sector_prep/index_availability_v2.md`. Summary: stock and index daily candles for day t are ingested by the same 15:40 IST job (stocks first, then NIFTY 50, then the 16 context indices); the signal scan runs at 15:45 and the h05 and lane jobs from 18:30 IST. The ingestion code does not refuse a partial bar; real arrival times are unknown (`candle_arrivals` is empty locally). **Rule for this research path (implemented and tested in `assemble_asof_row`):** the features for day t are built only if the stock, NIFTY 50 and the stock's own sector index each have a bar dated t, and, when a clock is given, only at or after 15:40 IST on a trading day (`last_closed_trading_day`).

## 11. Limits

Survivor-biased 47 stocks; HINDUNILVR windows excluded until the fresh fetch; ASIANPAINT and BHARTIARTL not covered; no liquidity modelling; daily bars cannot order target and stop inside a day (stop first); the new inputs overlap the existing sector inputs; rows are not independent (overlapping 10-day windows, shared market moves); the minimum detectable edge is not computed.

## 12. Exact approvals needed before any training (nothing proceeds until each is ticked)

- [ ] **A1** Accept this protocol text and its hash (signature below); an approval file needs a `protocol_id`.
- [x] **A2** DECIDED by the owner 2026-11-05: primary matched baseline = the 53 existing inputs (they passed the availability and leakage checks above); model 2's 37-input configuration is a SEPARATE production-reference benchmark (arm R_37); the challenger adds three sector inputs to the 53 (changed 2026-11-06 from four: `sector_ret_20d_vs_nifty` dropped). All arms use identical rows, dates, folds, costs and metrics.
- [ ] **A3** Folds and holdout (section 5): development 2023-07-01 to 2026-01-31, holdout 2026-02-01 to 2026-08-15.
- [ ] **A4** Pass rule rows R0 to R5 and outcome words (section 7), including that they are new rows.
- [ ] **A5** Relation to the td-protocol-v2 draft's B1: re-scope B1 or retire it.
- [ ] **A6** Experiment-register row written, with the rows hash and the config hash, before training.
- [ ] **A7** Code: `label_kind` (barrier 0.06 / 0.035) in `DatasetSpec`, the walk-forward harness (three arms, purge, immutable records, once-only holdout, approval refusal) and the seed-42 pin are BUILT AND TESTED with stub models and synthetic data (2026-11-05). Still open: the `fit_fn` of the signed protocol (the pinned recipe of section 4, with `n_jobs=1` for determinism) and the owner's review of the harness.
- [ ] **A8** HINDUNILVR fresh-fetch comparison done (otherwise its windows stay excluded and the row hash stays as above).
- [ ] **A9** Approval file created by the owner naming this candidate and the `config_sha256` of the final `DatasetSpec` (this session cannot create or sign it).

Signed: ______________________  Date: ____________  (DRAFT: not signed, not tagged.)
