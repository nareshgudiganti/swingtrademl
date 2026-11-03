# SX5 research protocol — DRAFT FOR OWNER APPROVAL (unsigned, untagged)

Date: 2026-11-05. Status: **DRAFT. Not signed, not tagged, no model trained, no model fitted, nothing activated.**
Labels in this file: **VERIFIED** = read from code, data or a signed/published document in this session; **PROPOSED** = my suggestion for the owner to accept or change; **UNVERIFIED** = not checked.

## 0. The short version (plain English)

1. **The question.** Does adding four sector-strength numbers to the existing 5-day model help it rank the large stocks better? The four numbers: the stock's sector-index return minus NIFTY 50's over 10 and over 20 days, the sector's rank among 15 sector indices, and the stock's 10-day return minus its sector's.
2. **How it is tested.** Two versions of the same model are trained on exactly the same rows and dates: **A** (the existing inputs) and **B** (the existing inputs plus the four sector numbers). Nothing else differs. Both are scored on later days, one fold at a time (the model never sees the future).
3. **What it is not.** It does not change the live 5-day models, the h05 lane, the sealed 15-day trial, any signed protocol, or any order. No new algorithm, no new input family, no new trading rule, no tuning.
4. **What a good result means.** At most "worth a proper forward test", never proof: these stocks and this history have been looked at before (section 9).
5. **The stocks.** 47 of the 49 large stocks. ASIANPAINT and BHARTIARTL have no verified official sector index, so their sector numbers would be missing and they are left out (owner decision 2026-11-05). A and B use exactly the same 47 stocks and rows, so the comparison is fair. What is lost versus the full 49 is reported in section 3.
6. **What you must still decide before anything is trained** is in section 12.

## 1. Question (one sentence)

Using only information known at the close of each trading day, does model B (existing inputs + four official-sector-index inputs) rank the 47 mapped large stocks better than model A (existing inputs only), on identical rows and identical walk-forward folds, for the original 5-day question (is the close 5 trading days later at least +2% above today's close)?

## 2. What stays unchanged (VERIFIED boundaries)

- The official h05 lane (disabled, protocol unaccepted), prod models 2, 16, 17 (ACTIVE), the sealed 15-day trial, `wf-protocol-v1`, `fd-protocol-v1`, `td-protocol-v1` (signed), the unsigned `td-protocol-v2` draft, Phase B and the selection lab.
- `ml/features.py`, `ml/predict.py`, `ml/sector_map.py`, `ml/dataset.py`, `ml/train.py` are read only. Nothing fingerprinted in `backend/tests/trial_freeze.json` is edited (that test passes).
- The 129 held-back stocks are not used. The Phase B reject set is not used. The v1 data and trading path are untouched.

## Isolation (VERIFIED in code, tested)
- The research models never enter `ml_models`, the production model directory, the model registry (`ml_models` table), production scoring (`ml/predict.py`), the h05 lane, the brain, strategies or orders.
- Code: `backend/src/swing_trade_ml/ml/sector_research.py` (nothing in the app imports it; a test enforces that). It reads the existing feature code (`ml/features.py`, read-only) and the one sector builder (`ml/sector_features.py`).
- Output goes only under `backend/data/research_models/<candidate>/<version>_<artifact sha>/` (gitignored) with a `manifest.json`. The writer refuses the production model directory and any path containing `ml_models`. Nothing is written to the database.
- ASIANPAINT and BHARTIARTL stay UNMAPPED: their four sector inputs are missing (never 0), and `include_unverified` is not exposed by the research path at all.
- Training requires an **approval file** (JSON; path in `SECTOR_RESEARCH_APPROVAL_FILE` or the `approval_path` argument) with `protocol_id`, `approved_by`, `candidate`, `config_sha256`. `config_sha256` must equal the hash of the exact `DatasetSpec` (symbols, horizon, label rule, cut-off, the exact exclusion list, columns, version). Any change to rows or settings changes the hash and the approval stops matching. Without a matching file the function only returns a dry-run plan. The model recipe is NOT in the module: the signed protocol supplies it as `fit_fn`.

## 3. The data (VERIFIED, reproducible; reports in `docs/brain/evidence/sector_prep/` with `_v2` names, v1 files kept)

Universe: the 49 model stocks (`stock_split_ev15.json`, `used_49`), local daily candles 2021-08 to 2026-09-07 (indices run to 2026-09-09). Sector rule: the stock's official NSE sector index from `ml/sector_map.py`. Unmapped: ASIANPAINT, BHARTIARTL. APOLLOHOSP loses 15 rows because NIFTY HEALTHCARE history is missing for a few sessions.

**Corporate-action policy (owner decisions 2026-11-05).** RELIANCE 2023-07-20 and ITC 2025-01-06: histories verified adjusted, rows RETAINED (category `RETAIN_VERIFIED_ADJUSTED`, flagged in the report). HINDUNILVR 2025-12-05: pending fresh fetch; its feature window (253 rows, both ends included) and label window are removed. BAJAJELEC 2023-09-14 is not in the 49. Genuine and provisional events stay retained.

**Row reconciliation, 5-session horizon** (each row counted once, first reason wins, in the order of the columns; overlaps in `reconciliation_v2.md`):

| Set | Raw rows | Warm-up | Label unknown | HUL event window | Existing-input gap | Sector gap | **Final** | sha256 |
|---|---|---|---|---|---|---|---|---|
| (i) SX universe, 47 mapped | 59314 | 11844 | 235 | 187 | 1103 | 15 | **45930** | `a862cdf4c81b0718657338ba868e6bb47e3537082d66873c92841472f3c35fb8` |
| (ii) full-49 baseline (existing inputs only) | 61838 | 12348 | 245 | 187 | 1149 | 0 | **47909** | `8b32492c653890e5da4334d888893b73c7f417a8d7ccf2c86ce610c68c0e10af` |
| (iii) matched baseline (existing inputs on exactly the rows of (i)) | - | - | - | - | - | - | **45930** | `a862cdf4c81b0718657338ba868e6bb47e3537082d66873c92841472f3c35fb8` (same row list as (i)) |

- The 187 removed HINDUNILVR rows split as {'label': 5, 'feature': 182} (feature and label windows). The earlier review's prediction is reproduced exactly: buildable 49245, excluded 187, retained 49058, sha256 `5800233d76617208db30ea6e1d42b486aee921dcb45c70b57b84f6ee1d5693c6` (49 stocks, before the existing-input and sector stages).
- The "existing-input gap" (1103 rows in the 47) is a stage the earlier prediction did not have: the first ~23 sessions after the 252-session warm-up lack a VIX percentile rank (INDIA VIX starts 2021-09-13), plus a few missing MFI values (checked on two stocks, MARUTI and HINDUNILVR; full per-column counts are in the JSON). Removed for both arms.
- Event windows that also have a sector gap: 0 rows. Event versus event: none.
- **Coverage loss of the SX universe versus the full-49 baseline:** 1979 rows (4.131%): {'APOLLOHOSP': 15, 'ASIANPAINT': 982, 'BHARTIARTL': 982}. The full-49 baseline (ii) is a SEPARATE reference; no A-versus-B comparison uses it.
- **Matched baseline (iii):** model A's rows are exactly (i)'s rows, and (iii) is a subset of (ii) (checked). A and B have identical eligible universes by construction (the reconciliation script checks that the matched rows are a subset of the full-49 rows; the row lists are the same file).
- Cross-check: the research assembler `assemble_training_matrix` produces exactly the same 45930 rows as this reconciliation (identical row sets, 0 differences).
- Canonical row lists: `sx5_47_rows_v2.txt.gz` and `full49_h5_rows_v2.txt.gz` (sorted `SYMBOL|YYYY-MM-DD`, newline separated; the sha256 is over the decompressed text).

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

**Inputs.** The current code (`FEATURE_COLUMNS`) has **53** existing inputs, not 46. The prod models use **37 (model 2, large caps) and 46 (models 16, 17)**: their saved lists are subsets of the 53. Model B adds the four sector inputs (`sector_ret_10d_vs_nifty`, `sector_ret_20d_vs_nifty`, `sector_rank_10d`, `stock_vs_sector_10d`): 57 in total. **Decision needed (A2):** model A = the 53 current inputs (PROPOSED; what `sector_research.RESEARCH_COLUMNS` builds today) or model 2's 37. Note that the 53 already include `sector_relative_strength_5d/20d` and `sector_trend_regime` (same sector index, NIFTY fallback), so the four new inputs partly overlap them and a small gain is the expected case.

**Label (original 5-day label, VERIFIED).** Endpoint: `target = 1` if `forward_return >= +2%`, where `forward_return` is the close 5 trading bars later divided by today's close, minus 1 (`brain/five_day_train.endpoint_target`; the prod rows say `label_kind=endpoint`, horizon 5, target 0.02, stop none). The last 5 sessions of each stock are dropped.

**Code gap to close before any training (VERIFIED by reading):** `sector_research.assemble_training_matrix` builds the label with `build_label` (the barrier rule) for both candidates and `DatasetSpec` has no label-kind field. SX5 needs the endpoint label: the matrix already carries `forward_return`, so `endpoint_target` can be applied, but a `label_kind` field must be added to `DatasetSpec` (this changes the config hash on purpose). Not done in this session. The walk-forward evaluation harness and the `fit_fn` are not in the repo yet; they are the next build step after approval.

## 5. Walk-forward design (PROPOSED; counts computed from the eligible rows)

- **Development folds:** 28-calendar-day test windows, back to back, 2023-07-01 to 2026-01-31 (`selection_lab.make_folds`, the `wf-protocol-v1` windows). Each fold's model is trained on rows whose label had resolved before the fold started (`label_end_ts < test start`; embargo = 5 sessions), retrained once per fold, expanding window. A and B use the same folds, rows and seed.
- **Final holdout:** 2026-02-01 to 2026-08-15, scored once at the end, **never used for choosing anything** (nothing is chosen: there is no tuning). Rows after 2026-08-15 are unused (label buffer).
- Eligible rows run from 2022-09-15 to 2026-08-31 (45930 rows, 45 to 47 stocks every day).

**Predicted test coverage (computed, VERIFIED on the final eligible rows):**

| | Folds | Test days | Test rows | Days per fold | Training rows per fold (after purge) |
|---|---|---|---|---|---|
| Development folds | 34 | 642 | 30,116 | 13 to 21 | 8955 (fold 1) to 38478 (fold 34) |
| Final holdout | 1 | 133 | 6,118 | 133 | all development rows |

Per-fold table: `docs/brain/evidence/sector_prep/sx5_fold_coverage_v2.csv`. All 34 folds have at least 10 test days. Best-5 ideas are at most 5 per test day; the number after the no-repeat rule is NOT computed.

**Minimum detectable edge: not computed.** The repo's `brain/lanes/h05_power.py` simulates the h05 forward lane from a database table of model scores; it does not apply to a paired walk-forward comparison. For context only, the td-protocol-v2 draft cites about +0.12% per trade at 396 days of 5 picks (10D analysis); a naive square-root scaling to 642 days gives about +0.09% (UNVERIFIED; ignores dependence between days). A paired difference between A and B is smaller and noisier than either alone, so INCONCLUSIVE is a likely outcome and is stated in advance.

## 6. Metrics (all computed on the same rows for A and B)

1. **Daily rank IC:** Spearman correlation per test day between the model score and the 5-day forward return over that day's eligible stocks (the `selection_lab.daily_ic` definition; days with fewer than 10 stocks left out).
2. **Top-5 hit rate:** share of each day's 5 highest-scored stocks whose label is 1, next to the every-stock hit rate that day.
3. **Excess benchmarks** (as `evidence-defs-v2`): average daily result of the top 5 minus **every eligible stock**, minus **random-5** (200 seeded draws), and against **NIFTY 50** held over the same days.
4. **Paired difference B minus A** on each of the above, per day, so the same days and stocks are compared. Block bootstrap over days: fd/h05 (block 5), 2,000 draws, seed 7, 5th percentile as the lower bound.
5. **Economic result after costs (diagnostic only):** the h05 shadow trade `h05_rules.simulate_trade` (+2% target / -4% stop / at most 5 sessions, entry at the open of session 1, stop checked first, large-cap slippage 10 bps per side, taxes and depository charge per `h05_protocol`, order Rs 1,00,000). h05 is an unaccepted DRAFT, so this is reported only if the owner approves it (A5) and it never decides pass or fail.
6. Per-fold results, worst fold, market-type split (rising / sideways / falling windows, `selection_lab.market_label`), hit rate needed to break even.

## 7. Pass/fail rule — PROPOSED (no number is agreed until you accept it)

Copied BY REFERENCE, not re-decided: fd-protocol-v1 section 6 (`2026-10-24-five-day-protocol.md`: eligible fold at least 10 test days and 20 finished ideas, at least 12 eligible folds, 60% of folds, lower bound above zero) and the h05 rules (`2026-10-30-h05-protocol-v1-DRAFT.md` sections 3, 4, 8, 9). Rows marked NEW are not in any signed protocol.

| Row | Needs | Source |
|---|---|---|
| R0 Same rows | the A and B eligible row lists are identical (equal sha256) | NEW |
| R1 Paired skill | B beats A on the daily top-5 excess over every eligible stock in at least 60% of eligible folds | NEW row; the 60% is borrowed |
| R2 Paired lower bound | 5th percentile of the mean daily difference (B minus A) is above zero | NEW row; bootstrap settings borrowed |
| R3 Enough data | at least 12 eligible folds and at least 100 finished best-5 ideas, else INCONCLUSIVE | borrowed |
| R4 Holdout agrees | the paired difference on the final holdout has the same sign (reported; not a second chance to pass) | NEW |
| R5 No harm | B's worst fold versus A's worst fold is shown (descriptive; no numeric threshold invented) | NEW, descriptive |

Outcome words: **IMPROVES** (R0 to R4 all met), **NO IMPROVEMENT** (enough data and R1 or R2 not met), **INCONCLUSIVE** (R3 not met). IMPROVES only means "worth proposing a forward shadow test"; it never activates anything. A null or negative result is stored with equal prominence. Nothing is changed after a result is seen.

## 8. Experiment register and multiple testing (PROPOSED entry for `docs/brain/EXPOSURE-LEDGER.md`)

- The entry is written BEFORE any model is trained: candidate SX5, rows hash, config hash, folds, seed, date, "no outcome read".
- Count: this is **one** pre-registered paired comparison (one change, four inputs; one horizon). With SX10 it makes two. In the wider programme the signed or drafted candidates are Phase B 3 + selection lab 6 + the td-protocol-v2 draft B1 (if signed) + SX5 + SX10, i.e. 11 to 12 comparisons on largely the same prices.
- Multiple-testing note (illustration; assumes independent tests at 5%): the chance that at least one of 11 passes by luck is about 43% (1 - 0.95^11); for these two alone about 10%. This is why a result can only justify a forward test, and why the primary metric is fixed (R1, R2) while IC and hit rate are descriptive.
- Relation to td-protocol-v2's B1 (breadth + four sector inputs): SX5 has no equivalent in the drafts.

## 9. History already seen, and the earlier failure (kept visible)

- The 5-day history 2023-07 to 2025-01 is the fd-protocol-v1 confirmation window; whether it has already been spent for a 5-day rule is UNVERIFIED here (check the exposure ledger). The h05 lane (unaccepted) and the 5-day models 2, 16, 17 are unchanged and not compared with here.
- The td-protocol-v2 draft says no unseen 10-day history is left. A and B see the same data, so the comparison is fair, but a pass cannot be called independent proof. The 47 stocks are today's names (survivor bias) and no liquidity or circuit-limit modelling exists.
- Every month since 2021-09 has been used for some study; the exposure-ledger row records this.

## 10. Index availability at decision time (VERIFIED from code and local data; arrival times UNKNOWN)

Full note: `docs/brain/evidence/sector_prep/index_availability_v2.md`. Summary: stock and index daily candles for day t are ingested by the same 15:40 IST job (stocks first, then NIFTY 50, then the 16 context indices); the signal scan runs at 15:45 and the h05 and lane jobs from 18:30 IST. The ingestion code does not refuse a partial bar; real arrival times are unknown (`candle_arrivals` is empty locally). **Rule for this research path (implemented and tested in `assemble_asof_row`):** the features for day t are built only if the stock, NIFTY 50 and the stock's own sector index each have a bar dated t, and, when a clock is given, only at or after 15:40 IST on a trading day (`last_closed_trading_day`).

## 11. Limits

Survivor-biased 47 stocks; HINDUNILVR windows excluded until the fresh fetch; ASIANPAINT and BHARTIARTL not covered; no liquidity modelling; daily bars cannot order target and stop inside a day (stop first); the new inputs overlap the existing sector inputs; rows are not independent (overlapping 5-day windows, shared market moves); the minimum detectable edge is not computed.

## 12. Exact approvals needed before any training (nothing proceeds until each is ticked)

- [ ] **A1** Accept this protocol text and its hash (signature below); an approval file needs a `protocol_id`.
- [ ] **A2** Inputs of model A: the 53 current inputs (PROPOSED) or model 2's 37.
- [ ] **A3** Folds and holdout (section 5): development 2023-07-01 to 2026-01-31, holdout 2026-02-01 to 2026-08-15.
- [ ] **A4** Pass rule rows R0 to R5 and outcome words (section 7), including that they are new rows.
- [ ] **A5** Economics: report the h05 shadow-trade result as a diagnostic, yes or no.
- [ ] **A6** Experiment-register row written, with the rows hash and the config hash, before training.
- [ ] **A7** Code gap closed and tested: `label_kind` (endpoint) in `DatasetSpec`; pinned seed 42; the walk-forward harness; the `fit_fn`. Tests first.
- [ ] **A8** HINDUNILVR fresh-fetch comparison done (otherwise its windows stay excluded and the row hash stays as above).
- [ ] **A9** Approval file created by the owner naming this candidate and the `config_sha256` of the final `DatasetSpec` (this session cannot create or sign it).

Signed: ______________________  Date: ____________  (DRAFT: not signed, not tagged.)
