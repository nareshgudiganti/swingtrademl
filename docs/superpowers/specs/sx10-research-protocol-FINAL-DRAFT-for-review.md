# SX10 research protocol: FINAL DRAFT for owner review (UNSIGNED, UNTAGGED)

Prepared: before signing (date set at signing). Status: **DRAFT FOR REVIEW. Not signed, not tagged. No model has been trained or fitted, no holdout has been evaluated, nothing has been activated, no authorisation exists.** Training stays unauthorised: none before 2026-12-04, and none afterwards without a separate, explicit approval (section 15).

Prepared against the worktree tip `1484e3819cd6b48e0cce38e80f258e584598200c` (branch `change/sector-features-prep`). That is NOT the signing commit. The signing commit hash and the matrix hash are marked **TO BE FILLED AT SIGNING** below.

How to read the tags. **[V] VERIFIED** = read from code, data or an evidence file (or recomputed) while preparing this draft. **[P] PROPOSED** = a recommended choice for the owner to accept or change; nothing is agreed until signed. **[A] ASSUMED** = a modelling assumption, not data. **OWNER INPUT** = a number or choice only the owner can supply.

This is one of two sister documents (`sx5-...` and `sx10-...`). They share all rules; they differ only in the horizon, the counts, the label wording and the power numbers. Companion: `sx-owner-review-checklist.md`.

## 1. Plain-English summary

1. **The question.** Does giving the existing 10-day model three extra numbers about the stock's sector (the sector index's return against NIFTY 50 over 10 days, the sector's rank among 15 sector indices, and the stock's 10-day return against its own sector) help it pick better stocks? The three numbers come from official NSE sector indices.
2. **How it is tested.** Three versions of one fixed model recipe are trained on exactly the same rows, dates and folds, one fold at a time, each scored only on later days: **A_53** (the 53 existing inputs; the baseline that counts), **R_37** (a 37-input research reference; descriptive only) and **C_56** (the 53 plus the three sector numbers; the challenger). The one comparison that decides is **C_56 minus A_53**, each day, on the five highest-scored stocks against all eligible stocks.
3. **What the three outcome words mean** (the computer code prints exactly one of them):
   - **PASS**: the new inputs did better on all three checks (the development folds, the statistical lower bound, and the separate holdout period). It means only that a **separately signed forward shadow test (no real money, no orders) may be proposed**. It is not proof. It changes no model, no order, no screen, no customer message.
   - **FAIL**: the data were large enough to rule out a gain of 0.24 percentage points per trade or more, and the best estimate stayed below it. It does **not** mean "the inputs do nothing"; smaller gains cannot be ruled out. Nothing is promoted, nothing is re-run.
   - **INCONCLUSIVE**: the test cannot tell "no effect" from "a useful effect", or its checks disagree, or there was too little data. It is **not** read as "no effect". Nothing is promoted, nothing is re-run on the same holdout.
4. **What to expect.** The study was checked for how small a gain it could ever see (section 8, S-9). It can reliably see a gain of about **0.24 percentage points per trade** (central assumption; 0.15 to 0.50 over the assumed ranges). A realistic gain from three extra inputs is assumed to be much smaller (0.03 to 0.13 pp). At such a size the chance of a PASS is only **about 7% to 20% before the holdout check R4 (which lowers it further)**. So **a PASS is far from certain even if the inputs help a little, and a lucky PASS is rare (2% to 4% when the true effect is zero)**. The most likely printed word at a realistic edge is **FAIL** (about 75% to 90% of runs when the true gain is 0 to 0.05 pp, see the check in section 9) and otherwise INCONCLUSIVE; PASS is the least likely (section 9). This protocol is a screening test for a large effect, not a test that can confirm a small one.
5. **What it is not.** It does not change the live models (2, 16, 17), the h05 lane, the sealed 15-day trial, any signed protocol, or any order. No new algorithm, no new input family, no new trading rule, no tuning. Phase B (separate, starts 2026-11-09) is not part of this.
6. **What you must decide before signing** is in section 15 and in `sx-owner-review-checklist.md`.

## 2. Question and scope

**Question (one sentence).** Using only information known at the close of each trading day, does arm C_56 (the 53 existing inputs plus three official-sector-index inputs) rank the 47 mapped large stocks better than arm A_53 (the 53 existing inputs), on identical rows and identical walk-forward folds, for the 10-day question of td-protocol-v1 (reach +6% before -3.5% within 10 trading days)? Arm R_37 runs on the same rows and folds as a descriptive reference.

**Limitation U (universe and survivorship), verbatim and binding on every report and every sentence about a result.** [P, replaces the earlier breadth-only caveat]

> **Limitation U (universe and survivorship).** The conclusions of this protocol are limited to the **fixed historical cohort of 47 stocks**: today's watchlist (minus ASIANPAINT and BHARTIARTL) applied to 2022-09-15 to 2026-08-31. The list was hand-chosen, has no written selection rule, and contains only companies that are listed and active in 2026-08. Companies that were delisted, merged, suspended, renamed away or dropped from an index during 2021-2026 are not in the data, and point-in-time index membership is not available locally. The two market-breadth inputs are computed over the same 49 names. Results therefore **do not generalise** to the full market, to other cap groups (mid and small caps), to delisted or merged names, or to future changes in index constituents. Absolute levels (hit rates, returns, excess over NIFTY 50) are likely flattered relative to a universe that includes names that failed; the size of that effect is not measured. The paired comparison C_56 minus A_53 uses identical rows and identical breadth in both arms, but is not proved free of universe bias, because a universe of names that are large today favours stocks that kept strengthening, which is what sector-strength inputs describe. **A PASS would justify only a forward shadow test on the same cohort.** It would not justify any production change, any wider rollout, or any claim to customers. A forward test would remove look-ahead on the data and the repeated use of the same history for this candidate; it would not remove the fixed-cohort limitation.

(The sentence in the earlier drafts "The comparison C_56 minus A_53 is unaffected by this construction" is true only for the two breadth inputs, which are identical in both arms. It is replaced by the Limitation U text above.)

**Report header (above the first number of every report on this protocol).** "Cohort: 47 large stocks, today's list applied to the past (2022-09 to 2026-08). Survivors only: delisted, merged and dropped names are missing. Results apply to this cohort only. Not evidence about other stocks, other sizes of company, or the future market."

**Forward-test rule (PROPOSED).** If a forward shadow test is ever proposed, it must carry a cohort rule fixed in advance for what happens when a cohort name is delisted, suspended or merged (count the idea as a loss at the last traded close, never drop it).

## 3. Data

**Stocks.** 47 of the 49 model stocks (ASIANPAINT and BHARTIARTL have no verified official sector index; owner decision). [V] ADANIENT, ADANIPORTS, APOLLOHOSP, AXISBANK, BAJAJ-AUTO, BAJAJFINSV, BAJFINANCE, BPCL, BRITANNIA, CIPLA, COALINDIA, DIVISLAB, DRREDDY, EICHERMOT, GRASIM, HCLTECH, HDFCBANK, HDFCLIFE, HEROMOTOCO, HINDALCO, HINDUNILVR, ICICIBANK, INDUSINDBK, INFY, ITC, JSWSTEEL, KOTAKBANK, LT, M&M, MARUTI, NESTLEIND, NTPC, ONGC, POWERGRID, RELIANCE, SBILIFE, SBIN, SHRIRAMFIN, SUNPHARMA, TATACONSUM, TATASTEEL, TCS, TECHM, TITAN, ULTRACEMCO, UPL, WIPRO. Daily candles run 2021-08 to 2026-09-07 (indices to 2026-09-09). The 129 held-back stocks and the Phase B reject set are not used.

**Eligible rows: 45,700** stock-days, decision days 2022-09-15 to 2026-08-24. [V] No artificial exclusion rule was added to preserve the older count (45,695); the five extra rows are APOLLOHOSP 2022-10-27 and 2022-11-01 to 2022-11-04 (valid point-in-time inputs, matured labels, training rows only).

**Reconciliation, raw to final** (each row counted once, at the first reason that applies; overlaps in `reconciliation_v3.md`) [V]:

| Step | Rows removed | Reason | Rows left |
|---|---|---|---|
| Raw stock-days of the 47 stocks | 0 | all daily bars | 59,314 |
| Warm-up | 11,844 | first 252 sessions of each stock (47 x 252): long-window inputs not defined yet | 47,470 |
| Label not finished | 470 | last 10 sessions of each stock (47 x 10): the outcome is not known yet | 47,000 |
| Corporate-action window | 187 | HINDUNILVR demerger of 2025-12-05, price adjustment pending a fresh fetch (177 feature-window rows and 10 label-window rows); other events retained (RELIANCE 2023-07-20 and ITC 2025-01-06 verified adjusted) | 46,813 |
| Existing-input gap | 1,103 | 1,081 rows of one window (2022-08-11 to 2022-09-14, all 47 stocks, no VIX rank yet: INDIA VIX starts 2021-09-13) plus 22 rows where MFI is undefined after 14 straight up days | 45,710 |
| Sector gap | 10 | APOLLOHOSP, early rows where the NIFTY HEALTHCARE history is too short | **45,700** |

Reconciliation checks: the research assembler and the reconciliation give identical row sets (0 differences) [V]. Against the full-49 baseline (existing inputs only, a separate reference that no comparison uses) the 47-stock set loses 1,964 (4.12%) rows: ASIANPAINT and BHARTIARTL (unmapped) and 10 APOLLOHOSP rows [V]. Of the 1,103 gap rows, 1,088 are before the first test fold and 15 are in test folds; the removal is identical across arms [V].

**HINDUNILVR.** The 187 rows of its demerger windows are excluded until a fresh price fetch is compared. The row-list hash and every hash below assume this exclusion. If the fetch changes anything, the row list and every hash change and this document is reissued [V, B15 default: keep excluded]. Fetch status: **PENDING** (non-blocking if the exclusion is accepted).

**Hashes** (complete values from `docs/brain/evidence/sector_prep/final_hashes_v3.json`, verified against the code in the worktree at preparation) [V]:

| Item | Value |
|---|---|
| Row-list sha256 (one key per row, symbol and date joined by a vertical bar; keys sorted, newline-joined, no trailing newline) | `d10ef048f52a7bfe377472ff51814f8f3710998a5847f3159e7ae66fe359b444` |
| Row-list file (decompressed text sha256) | `docs/brain/evidence/sector_prep/sx10_47_rows_v3.txt.gz` : `4dfc5496c293ea4e0930c2f49abb90424db81fd67e1b70ffa02db7108e64bff3` |
| DatasetSpec `config_sha256` (the value the approval file must name, complete, never a prefix) | `3c1507a9324b93417f3f9000e431778da944eb817a7631070112a96455842be5` |
| Harness config sha256 | `69b049a8e1599711c2a2c08e3125c1e821cffc180722766f9ec670882b084933` |
| Fold definition sha256, development folds plus holdout (the one bound for a holdout run) | `a39693b0640106ee92bfeb81972ec6855576dec94ce50249ffa7a0b0dcbddaae` |
| Fold definition sha256, development folds only | `fe4f133f20aafe39ff4c3d696e5c49ab5061c5d88098f3dd5b8e4545eb3bd023` |
| Exclusion file | `docs/brain/evidence/sector_prep/excluded_rows_h10_v2.csv` sha256 `0aaec2b5b1e4a79620df5d683f4506c4bdf4a501be2ed0a28d36535cd3cf9372` (187 rows, all HINDUNILVR) |
| Exclusion keys sha256 | `f91418585c918d9f71c2cef5da98cd094e2df04ecd8f1dc8399160e3012f3565` |
| Events input (`events_input_v2.csv`, 419 events) sha256 | `23f145d80e6ce64e784c5db4d93d479929f4c429fcf369c84aa4b46710b649cf` |
| Matrix hash (`dataset_sha256`, feature and label VALUES; depends on the pandas build) | carried from the verification run: `ee5eba79bfddda8d2f3cf347ff419d8961634ae9a398cf9c1587967608573d8c`. **TO BE FILLED AT SIGNING** (regenerate on the signing environment) |
| Model recipe sha256 (`sx_recipe_v1`, includes library versions) | `fa6b3e974f62a20a8363e3ceef34105b728bcf1b3a0fe502e2aa05d00e501233` (to be recomputed in the signing environment) |
| Signing commit (full 40-hex) | **TO BE FILLED AT SIGNING** |
| Protocol file sha256 (this file, as committed) | **TO BE FILLED AT SIGNING** |
| Verdict parameter-set sha256 and verdict code sha256 | **TO BE FILLED AT SIGNING** (section 11) |

**Regenerating the hash sheet on the signing commit** (read-only, no database, fits nothing; refuses unless the commit argument is the full 40-hex `git rev-parse HEAD` and the working tree is completely clean):

```
cd backend
PYTHONPATH=src python scripts/final_hash_sheet.py <FULL-40-HEX-COMMIT> --out <sheet.json> --protocol SX10=<path of this file> --prior-sheet ../docs/brain/evidence/sector_prep/final_hashes_v3.json
```

Add `--protocol SX5=<path>` and `--protocol SX10=<path>` for both sister documents. Every number in the sheet must equal the values above except the commit, the protocol hashes and the environment block; any difference stops signing.

## 4. Features

**Manifests** [V] (exact ordered column lists in `docs/brain/evidence/sector_prep/feature_manifests_v3.json`):

| Arm | Columns | `feature_list_sha256` (canonical, BINDING) | `manifest_sha256` (plain cross-reference, checked by no code) |
|---|---|---|---|
| **A_53** (baseline that counts) | 53: `ml/features.FEATURE_COLUMNS` | `3bd35e8549ebddcea9f52ee680530cdef80a4bb524cf74b1a04c328e1a7141c4` | `f5a8d398d56e47d8bce33943ea78d50d949933022d12c2cb6ef24f5792086f29` |
| **R_37** (RESEARCH REFERENCE) | 37 | `b00fc7076853bbd56ba3f32d254a57cfbc89ef19969f27564c4d5ac4939574c5` | `0615e2fb6c1c9ae120d1455895ad39d3422fcc1bd2053c4bd4b1a1476946d122` |
| **C_56** (challenger) | 56 = 53 + 3 | `123aa67a611a564d3e41a362b018c08f2d7d18606079abb3d3acb62c01303a0e` | `1a691d7df13366b2c438e5024878bfc228adaa4c77560a39ac39bfd3fd22b910` |

- **C_56 = A_53 plus** `sector_ret_10d_vs_nifty`, `sector_rank_10d`, `stock_vs_sector_10d`. The earlier fourth input `sector_ret_20d_vs_nifty` was dropped: it equals `relative_strength_20d - sector_relative_strength_20d` (two existing inputs) on 45,917 of 45,930 audited rows; the other 13 (all APOLLOHOSP) differ only because NIFTY HEALTHCARE has no close on seven sessions (a window-definition difference, no new information; `c56_decision_v3.json`). (Rename note: this arm was called "C_57" in earlier drafts; no C_57 number applies.) [V]
- **Overlap of the three new inputs with the 53** (in-sample linear R-squared, descriptive): `stock_vs_sector_10d` 0.83, `sector_ret_10d_vs_nifty` 0.74, `sector_rank_10d` 0.50 (`feature_overlap_v3.json`). The genuinely new content is mostly the sector's own 10-day move and rank; a small gain is the expected case. [V]
- **R_37 is a 37-feature RESEARCH REFERENCE, not a production replay.** Its 37 names and their order equal the list saved in production model 2 (`model2_saved_features_v1.json`); it is the 53 minus 16 inputs (`days_since_52w_high`, `days_since_52w_low`, `streak`, `volatility_percentile_rank`, `cmf_20`, `relative_strength_5d`, `relative_strength_20d`, `nifty_volatility_20`, `nifty_trend_regime`, `sector_relative_strength_5d`, `sector_relative_strength_20d`, `sector_trend_regime`, `vix_change_5d`, `vix_percentile_rank`, `breadth_pct_above_sma50`, `breadth_advance_pct`). Its `obv_slope` VALUES differ from what model 2 was trained on: training era `obv.diff(10) / obv.rolling(20).mean().abs()`; current builder since commit `fcaef35` `obv.diff(10) / volume.rolling(20).mean()`. All three research arms use the CURRENT formula on the FULL history, so C_56 minus A_53 is not affected. R_37 is also retrained under the SX recipe, so it is not model 2's weights, scaler, hyper-parameters or training stocks. No R_37 result may be described as production performance. The current `obv_slope` implementation is not changed. [V] Models 16 and 17 save 46 names (the 53 minus `sector_relative_strength_5d`, `sector_relative_strength_20d`, `sector_trend_regime`, `vix_change_5d`, `vix_percentile_rank`, `breadth_pct_above_sma50`, `breadth_advance_pct`); they are not used here.
- **Breadth.** `breadth_pct_above_sma50` and `breadth_advance_pct` are computed over today's 49 watchlist stocks for every past date (correlation with the 306-stock version 0.895 and 0.876). They are in A_53 and C_56 identically and absent from R_37. Comparisons involving R_37 are confounded by this and by VIX and are descriptive only. [V]

**The one hash convention to be signed.** The binding column-list hash is `feature_list_sha256`: take the ORDERED list of the arm's column names (exact spelling; order is part of the hash); serialise with JSON using `sort_keys=True` and separators `","` and `":"` (no spaces; names are ASCII); encode as UTF-8; SHA-256, lowercase hex, 64 characters. It is the value the harness writes into every record and the holdout registry and approval file bind. `manifest_sha256` (`json.dumps(list)` with Python's default separators) is a labelled human cross-reference only. Never write "the feature hash" alone: always the name plus the first 8 characters. Independent recomputation (needs only Python):

```python
import hashlib, json
cols = json.load(open("docs/brain/evidence/sector_prep/feature_manifests_v3.json"))["arms"]["C_56"]["columns"]
print(len(cols), hashlib.sha256(json.dumps(cols, separators=(",", ":")).encode("utf-8")).hexdigest())
# expect: 56 123aa67a611a564d3e41a362b018c08f2d7d18606079abb3d3acb62c01303a0e
```

**Point-in-time evidence** [V]:
- The existing builder (`ml/features.build_features`, unedited): for 49 stocks x 25 cut days (1,225 stock-days, 53 inputs) the features built from data cut at day t equal those built from the full history (tolerance 1e-7): 0 mismatches. A second test wrecks every stock, index, VIX and breadth value after a day T: no input on or before T moves (12 stocks, 0 changes). Both tests can fail (a deliberately leaking builder is caught). No input fails.
- The five restored APOLLOHOSP rows (`final_verification_v3.md`, `apollohosp_mutation_check_v1.md`): the as-of builder equals the batch builder (max absolute difference 0.0, 56 of 56 inputs bit-identical); a mutation test replacing all later data with random multiples leaves the row and every earlier row bit-identical (10 of 10 day-by-horizon cases); the row n = 1, 2, 5, 10, 20, 60 sessions later does change in every case (0 cases without power); the as-of versus batch mirror check passes 30 of 30. Labels recomputed independently from raw candles equal the matrix; none of the five rows is in any test set; independent purge recount: 0 mismatches in 35 folds.
- Index availability at decision time: features for day t are built only if the stock, NIFTY 50 and the stock's own sector index each have a bar dated t (`assemble_asof_row`; `index_availability_v2.md`). Real arrival times of index bars are UNKNOWN (the arrivals table is empty locally). [V]

## 5. Label and the quantity that decides

**Training label (barrier) [V].** target = 1 if the stock reaches +6% before -3.5% within 10 trading bars (`ml/features.build_label` barrier rule; `ten_day.TARGET` 0.06, `STOP` 0.035, `HORIZON_BARS` 10); a same-bar touch of both levels scores as the stop. The last 10 sessions of each stock are dropped. Development base rate of the label: 20.1% (S-9 measurement). Tested equal to the `ten_day` definition in code.

**The quantity that decides, and OWNER DECISION D-Q10 (NEW).** The earlier SX10 draft (section 6) and the S-9 note call the SX10 quantity "the 10-day trade result" and describe it with the +6% / -3.5% barrier. **That is not what the harness and the verdict code compute.** [V in code] They record and use the **raw 10-session forward return** (close 10 sessions later divided by the decision-day close, minus 1); the barrier label is used only to train the models (and for the descriptive top-5 hit rate). The S-9 simulation also used 10-day sums of daily returns, so the power numbers below describe the raw return.

Options:
- **(a) DEFAULT RECOMMENDATION [P]: the raw 10-session forward return is the primary quantity** (this text). It matches the code, the S-9 numbers and the other protocol; the barrier trade result (`ten_day.score_trade`: +6% / -3.5%, 10 bars, no half-out, entry at the next open, stop before target, 0.10% slippage per side in total, Rs 40,000 position) is reported as a **labelled diagnostic with no weight**. Consequence: a model trained to find "+6% before -3.5%" is judged on the plain 10-day return, which is related but not the same thing; a result must be worded that way.
- **(b)** Change the harness so the daily value is the barrier trade result. Needs a code change, new tests, a new recipe/config/code hash, a new S-9 power run (that result is bounded and has a different spread) and a re-review. Nothing of this is done or estimated here.

Until D-Q10 is signed, the phrase "10-day trade result" must not be used for the primary number in any document.

## 6. Model recipe

One recipe for every arm: `ml/sx_recipe.py`, version `sx_recipe_v1`, written out in `sx-model-recipe-FINAL-DRAFT` (file name carries an assumed date; see the checklist). [V] LightGBM binary classifier: 400 trees, learning rate 0.05, depth 6, 31 leaves, column sampling 0.8, `subsample` 0.8 but **inert** (`subsample_freq` stays 0 exactly as in production), min child samples 50, L1 and L2 0.1, balanced class weights, **seed 42**, **`n_jobs=1`**, StandardScaler fitted on the training rows only. **No tuning, no early stopping, no validation split, no calibration, no feature selection, no imputation.** Each fold fits on **100% of the purged training rows** (production-style models fit on 80%). Recipe sha256 `fa6b3e974f62a20a8363e3ceef34105b728bcf1b3a0fe502e2aa05d00e501233` with lightgbm 4.7.0, scikit-learn 1.9.1, numpy 2.5.4, pandas 3.1.0, scipy 1.18.1 (Python 3.12.6, Windows 11). `build_fit_fn` refuses a library-version mismatch and any approval mismatch; the returned function carries `recipe_sha256`, which the registry binds per arm. The environment is pinned and the recipe hash is recomputed in the environment that runs the real fit (B7). Bit-identical scores on another platform are not guaranteed; all input hashes are platform-independent. [V] Owner-accepted choices behind it (B4 100% fit, B5 inert subsample, B6 `n_jobs=1`, B9 the `fit_fn` signature). [P until signed]

## 7. Folds, purge, embargo, burn-in, holdout

**Fold numbering is 0-based throughout this document and in the code** (fold 0 to fold 33). The evidence CSVs `sx5_fold_coverage_v3.csv` and `sx10_fold_coverage_v3.csv` number the same folds 1 to 34 and add a holdout row 35; fold N in this document is row N+1 of those files. [V]

- **Development folds** [V]: 34 back-to-back 28-calendar-day test windows from 2023-07-01 to 2026-01-31 (642 test days, 30,111 test rows, 13 to 21 days per fold). Each fold is trained on an expanding window of rows whose whole label window ended before the test window starts, and whose decision day is not among the last 10 sessions before the test start (purge 458 to 470 rows per fold; the embargo of 10 sessions removes no further row). Training rows per fold: 8,725 (fold 0) to 38,248 (fold 33). Independent recount of the purge: 0 mismatches in 35 folds.
- **Burn-in (B2, accepted as the basis).** R1 and R2 count **folds 4 to 33 only (30 folds; test windows 2023-10-21 to 2026-01-31; 565 test days)**. Folds 0 to 3 (77 test days; they train on under one year of history) are reported labelled "burn-in, not counted" and never enter R1, R2 or any outcome. This is fixed at signing and is a choice made before any result exists. [P]
- **Final holdout (SX models only)** (replacement wording, B3). Decision days 2026-02-01 to 2026-08-14 (the last session on or before Saturday 2026-08-15): 133 days, 6,118 rows, fit set 38,846 rows, scored once. The labels of the last 10 of these decision days use bars dated up to 2026-08-28. Every such bar exists, and no label uses a bar after 2026-09-07 (460 (10 decision days) holdout rows have a label window that uses bars after 2026-08-15). No feature uses data after its decision day. Decisions after 2026-08-14 are not scored. Development decisions in the last 10 sessions before 2026-02-01 have labels reaching into February 2026; they are scored in the last development fold (fold 33) and removed from the holdout training set. **These prices are not untouched in the exposure ledger: the holdout-period prices were used in earlier diagnostics. The period is a holdout only for the SX models and labels.** Holdout test rows sha256 `6b84f05db3da0f6c0736a9db06bb6097461935c1a9367605b36254dac6261f3d`. [V]
- Nothing is chosen on the holdout (nothing is chosen at all: there is no tuning). The harness refuses any non-holdout fold whose test window reaches 2026-02-01. [V]
- **Training-period character** (limitation, section 13): every training window is 81% to 94% bullish; folds 0 to 18 never trained through a NIFTY 50 drawdown worse than 10% (the first such fold is 19). [V]
- **When the holdout is run (OWNER DECISION D-H, PROPOSED).** The harness can run the development folds alone (`include_holdout` false) and the verdict code reads development records first. PROPOSED: the holdout is authorised and run only if the development-only call returns PENDING_HOLDOUT; otherwise the holdout stays unrun. Whether a holdout-only invocation after a development-only run works in the harness as built is **UNVERIFIED** and must be tested on synthetic data before signing. Alternative: run both in one invocation (the holdout is then consumed in every case). See the checklist.

## 8. Statistical procedure S-1 to S-9 (final text, to be signed)

`h` = 10. All numbers below are fixed at signing; none may change after any result.

**S-1 Unit.** The unit is the decision day. For each arm and day, among the stocks that day with a final score, take the five with the highest score (ties broken by ascending symbol, as in `sector_walkforward._day_metrics`). The daily value x_t is the mean `forward_return` of those five minus the mean `forward_return` of all eligible stocks that day (`excess_vs_all`). `forward_return` is the close 10 trading sessions after the decision day divided by the decision-day close, minus 1 (raw close-to-close, entry at the decision-day close, no costs). Days with fewer than 10 eligible stocks are left out of every arm. Pooled rows, picks or folds are never the unit of an interval. [V in code; P as text] **For SX10 this is the raw 10-session return, not the barrier trade result; see D-Q10 in section 5.**

**S-2 Paired series.** T = the decision days that lie in the test windows of folds 4 to 33 (0-based), have at least 10 eligible stocks, in ascending date order (565 days expected). D_t = x_t(C_56) minus x_t(A_53) for t in T. Blocks are runs of consecutive entries of T, not calendar days.

**S-3 Interval.** n = |T|, b = 2h = 20. One draw: pick ceil(n/b) = 29 starts s uniformly from 0..n-b using `random.Random(7).randrange(n - b + 1)` (one generator, 2,000 draws, never reseeded), append D[s:s+b], take the mean of all appended values (same convention as `brain/walk_forward.bootstrap_low`). Sort the 2,000 means m(1) <= ... <= m(2000). One-sided lower bound at level alpha = m(floor(alpha x 2000) + 1), 1-based (alpha 0.05 gives m(101), alpha 0.025 gives m(51)). One-sided **upper** bound at 5% = m(1900). p-value = (1 + number of means <= 0) / 2001. If n < max(5, 2b) the interval is not computable. Block h, block 3h and day-iid (block 1) are computed by the same code as **sensitivity with no weight** and can never change the outcome. Implemented in `ml/sx_verdict.py`. [V]

**S-4 One primary comparison per horizon.** C_56 minus A_53 on the daily top-5 excess over every eligible stock. Everything else (A_53 minus R_37, C_56 minus R_37, IC, hit rates, random-5, NIFTY 50, economics, market-type splits, per-fold tables) is secondary or descriptive and carries no pass/fail weight. Nothing is added after results. [P, B8]

**S-5 Multiplicity (one-horizon Holm rule).** The family is {SX5, SX10}. The two protocols may be read at different times, so "the smaller p-value" may not exist when one is read. **Rule: this protocol is read in `single_horizon` mode: R2 uses the one-sided 2.5% lower bound (the stricter level), and that choice is not changed later.** The `two_horizon` mode (smaller p tested at 2.5%, the other at 5%; ties SX5 first) is NOT used by this protocol; using it would need a new signed text. No programme-wide Bonferroni is applied; the programme-wide count (section 14) is recorded and is the reason a PASS only proposes a forward shadow test. R1 is not adjusted; the level applies to R2 only. [P, NEW since the last summary]

**S-6 Folds.** Fold k (0-based) is eligible if its status is `ok` in both arms and it has at least 10 test days with at least 10 eligible stocks and at least 20 top-5 picks. Picks are counted as 5 per such day **before any no-repeat rule; no no-repeat rule is applied in this historical test**, so any fold with 10 or more days already has at least 50 picks and the "20 picks" condition can never bind. (The actual folds have 13 to 21 days, so all 30 counted folds are expected to be eligible.) R1 uses per-fold means of D_t over eligible counted folds; R1 is a consistency check and R2 carries the inference. A fold whose status is not `ok` in any arm is ineligible, listed, and makes the data check fail. [V code; P as text]

**S-7 No peeking.** Block length, draws, seed, bounds, folds counted, the Holm mode, MDE_H and the primary quantity are fixed at signing in the verdict parameter set (section 11). The verdict is produced by `ml/sx_verdict.py` at the signed commit, from the `manifest.json` and the `dev_*` records (and, only if needed, the `holdout_*` records) of ONE run id named in the signed text. Its output file is created with exclusive-create and records the code hash, the parameter hash, the record hashes and the outcome word. A second computation of the verdict is a protocol breach; a change to the code or parameters is a new protocol id, and the old result stays on record. The holdout is scored once. No change to block, metric, fold set or threshold after any result. [P]

**S-8 Holdout.** The paired difference on the 133 holdout days is reported with the S-3 interval. It is R4, a sign-consistency check, not a second chance to pass.

**S-9 Minimum detectable edge (computed; closes blocker B18).** [V computed, ASSUMED structure] Before signing, the study computed the smallest true paired edge (C_56 minus A_53, in percentage points of the daily top-5 excess, equal to percentage points per trade) that R1 and R2 with the block-2h bootstrap at the 2.5% one-sided bound would pass 80% of the time, on synthetic data with the dependence measured on the development period (`backend/scripts/sx_power_analysis.py`, master seed recorded in the script, 1,000 simulations per cell, results `docs/brain/evidence/sector_prep/sx_s9_power_v1.json`).

| | SX10 |
|---|---|
| **MDE80, central** (persistence of the top picks 0.5, correlation between the two arms' scores 0.8, 34 folds, 2.5% bound, R1 + R2) | **0.24 pp** (0.25 with the 30 counted folds) |
| Optimistic corner (persistence 0, correlation 0.95) | 0.15 pp |
| Pessimistic corner (persistence 0.9, correlation 0.5) | 0.50 pp |
| MDE50 (50% power), central | 0.17 pp |
| MDE80 with R4 included, central | 0.27 pp |
| Realistic gain from three extra inputs [A] | 0.03 to 0.13 pp per trade |
| Power at a realistic gain, central cell | 0.05 pp: 7%; 0.10 pp: 20%; 0.15 pp: 40% |
| False PASS when the true edge is zero (R1 + R2, 2.5% bound) | 1.9% to 4.5% across the nine cells (2.4% at the central cell) |
| Effective independent days: market-wide daily mean (all 838 days, findings) / development days only (S-9 note) | about 95 / 78 |
| Effective days of D_t itself (simulated, of 642): central / range | 522 / 153 to 686 |

- **Assumptions [A]**: iid daily returns with one market factor and Student-t tails (measured market share of variance 0.252, 4.9 degrees of freedom); AR(1) score persistence phi (central 0.5, matched to one measurement: day-to-day rank correlation 0.59 of the stored production score over nine pairs, 40% of today's best five in tomorrow's best five); arm correlation rho_AC (central 0.8; **not measurable without fitting models; it moves the answer about 2x**); a constant true edge over all folds and the holdout; the whole gain of C_56 is information A_53 does not see. The realistic-gain range is an assumption anchored on the repo's own evidence that A-like models show no skill (fd-protocol-v1 5-day best-5 edge -0.011 pp; td-protocol-v1 10-day about -0.12 pp). None of the structural variations tested (normal or heavy tails, volatility regimes, sector-style groups) moved the answer by more than 6%.
- **The two effective-sample figures do not measure D_t.** The market-wide daily mean figures (about 246 and 95 of 838 days in the findings; 199 and 78 of 637 and 632 development days in the S-9 note) are the wrong yardstick for D_t, whose market move cancels. The 565 counted days carry the D_t effective sample shown in the table.
- **Power limits (stated plainly).** The test is **not adequately powered for a realistic edge**; it is adequate only for about 0.24 (central) and as much as 0.50 (pessimistic corner) pp or more. A failure to pass is not evidence that the inputs do nothing. Burn-in (30 folds instead of 34) and R4 cost at most 0.01 pp and 0.01 to 0.06 pp respectively. The simulation used the 642 development days; the counted series has 565, so the true minimum is slightly higher (not simulated). The bootstrap has 29 blocks per draw, so its lower bound is somewhat noisier than the table suggests. The holdout (133 days) is a sign check with little power of its own. The programme-wide count of 11 to 12 comparisons is not corrected in the rule; if the owner wished to correct for it, the detectable edge would be about 24% larger.
- **MDE_H (a REQUIRED signed number; the verdict code refuses to run without it).** MDE_H is the smallest paired edge, in percentage points per trade, that the study declares worth being able to see. **PROPOSED: MDE_H = the central MDE80 = 0.24 pp** (written into the parameter set as the return fraction 0.0024 per day). **OWNER DECISION: accept, or sign a different number.** What it changes: it is the only number that separates FAIL from INCONCLUSIVE (section 9). A smaller MDE_H makes FAIL rarer (the interval must sit below a smaller edge); a larger one makes FAIL more frequent and weaker in meaning. Changing it after any result is forbidden.
- **E\* (the owner's "edge worth acting on").** E\* is the size of gain below which the owner no longer cares. **OWNER INPUT: no default is signed.** (The power analysis suggested, as a starting point only, 0.13 pp, the top of the assumed realistic range.) E\* is used only to word the plain-English reading and the decision to propose a forward test; **the code takes no E\* and no outcome word depends on it.**

## 9. Success criteria R0 to R5 and the outcome words

Numbers are written into this text; it does not defer to fd-protocol-v1, td-protocol-v1 or the h05 draft. Vocabulary: **PASS / FAIL / INCONCLUSIVE** (the earlier words IMPROVES / NO IMPROVEMENT are retired). Implemented and tested in `ml/sx_verdict.py` (30 tests on synthetic records). [V]

| Rule | Final text |
|---|---|
| **R0 Same rows** | A_53, R_37 and C_56 have identical eligible row lists (equal sha256), the same days, the same `n_stocks` per day and the same status per fold. Otherwise the run is VOID: no result, recorded as void. |
| **R1 Paired skill** | Among eligible counted folds E, the number with mean(D_t over the fold's days) strictly > 0 is at least ceil(0.6 x \|E\|) (18 of 30). A fold mean of exactly 0 is not a win. |
| **R2 Paired lower bound** | The one-sided **2.5%** lower bound of the mean of D_t (S-3 on T) is strictly above 0. |
| **R3 Enough data** | \|E\| >= 12, picks over E >= 100, \|T\| >= 2h (20), and every counted fold has status `ok`. Otherwise INCONCLUSIVE (data). |
| **R4 Holdout agrees** | The mean of D_t over the holdout days (decision days 2026-02-01 to 2026-08-14 with at least 10 eligible stocks, all holdout folds status `ok`) is strictly > 0 **and** the development mean over T is strictly > 0. A mean of exactly 0 does not meet R4. The holdout interval is reported with no weight. The code does not enforce "133 days"; the registry and the reader verify the count. [P: the packages said only "same sign"] |
| **R5 No harm** | A table only: per-fold mean D_t for folds 4 to 33 with the minimum and maximum. No threshold, no weight in the outcome word, not quoted as a reason to promote or reject. |

**Outcome rule, evaluated mechanically in this fixed order** (after the parameters are valid and R0 holds):

1. **INCONCLUSIVE (data)** if R3 is not met.
2. Else if R2 **and** R1 are met: if the holdout run is not recorded COMPLETED the printed word is **PENDING_HOLDOUT** (an interim status, not a protocol outcome: the development checks are met and R4 cannot be read yet). Once COMPLETED: **PASS** if R4 is met, else **INCONCLUSIVE** (the signals disagree).
3. Else if R2 is not met and the one-sided **5% upper bound** of the mean of D_t is **below MDE_H**: **FAIL**.
4. Else if R2 is not met: **INCONCLUSIVE** (the upper bound is at or above MDE_H: no effect cannot be told from a useful effect).
5. Else (R2 met, R1 not met): **INCONCLUSIVE** (the signals disagree).

If the holdout is COMPLETED but no holdout records are supplied, or any input is incomplete, duplicated, non-finite or breaks R0, the code refuses: there is no result and nothing is guessed. The holdout records are never opened unless the registry shows COMPLETED **and** the outcome depends on R4.

**What the words will usually look like at a realistic gain (approximate check, [A]).** Check run while preparing this draft: 200 simulated runs per row, D_t drawn as independent normal values over 568 days with the spread set so that the 80%-power edge equals the S-9 figure (standard error about 0.086 pp), the real `ml/sx_verdict.py` bootstrap, block 20, MDE_H 0.24 pp. R1 and R4 are NOT in this check (so "R2 met" is an upper limit for PASS). It is a scratch calculation, not in the repository; the independent-day assumption is simpler than S-9 (it reproduces S-9's 78% R2 power at the 0.24 pp edge).

| True edge (pp per trade) | FAIL | INCONCLUSIVE | R2 met (then R1 and R4 still decide) |
|---|---|---|---|
| 0 | 90% | 7% | 4% |
| 0.05 | 76% | 15% | 9% |
| 0.13 | 43% | 21% | 35% |
| 0.24 | 9% | 14% | 78% |

**Reading, and a point the earlier documents got wrong.** The summaries said INCONCLUSIVE is the expected outcome, especially at 10 days. With MDE_H set to the central MDE80, that is not what the rule produces: when the true gain is zero or tiny the most likely printed word is **FAIL**, because FAIL only says "a gain of 0.24 pp or more is unlikely". INCONCLUSIVE is never the majority in this check. So every FAIL report must carry the sentence "This does not show that the inputs do nothing; a gain below 0.24 pp per trade cannot be ruled out." If the owner wants INCONCLUSIVE to be the usual word at realistic edges, a different MDE_H (or a different outcome rule, which is a code change) would have to be signed; a smaller MDE_H makes FAIL need a mean at or below about zero. This is listed as a NEW decision in the checklist.

**What happens after each outcome.**
- **PASS.** Recorded in the register with Limitation U, the programme-wide 43% to 46% chance of a lucky pass, and the fact that the holdout prices were seen in earlier diagnostics. It proposes, and only proposes, a **separately signed forward shadow test** on the same 47-stock cohort. No model is promoted; no production model, h05 lane, brain, scoring, order or customer screen changes. A PASS is never described as proof or as production performance.
- **FAIL.** Recorded with equal prominence. No promotion, no re-run on the same holdout, no re-tuning, no variant of the recipe or the inputs under the same protocol id. A different idea is a new protocol id with this failure on record. It is not read as "the inputs do nothing".
- **INCONCLUSIVE.** Recorded in the register with the numbers. No model promotion. No re-run on the same holdout. No re-tuning (hyper-parameters, seed, block, folds, inputs, rows). **No extension of the sample (more days, a wider cohort) under the same protocol id; any extension is a new protocol id signed before its data are read.** Not read as "no effect". A forward shadow continuation can be proposed only in a separate protocol, separately signed, and an INCONCLUSIVE result carries no weight toward it.
- **PENDING_HOLDOUT** is not an end state: it leads to the holdout authorisation step (section 10) and then to PASS or INCONCLUSIVE.
- For all outcomes: the word is not changed after it is produced; sensitivity results and secondary arms are shown and cannot change it; a null or negative result is stored with the same prominence as a PASS.

## 10. Holdout authorisation safeguards and recovery

**State today** [V]: the registry file `docs/brain/evidence/sector_prep/HOLDOUT-REGISTRY.jsonl` is 0 bytes. A real holdout run is refused ("no owner authorisation exists for the horizon-10 holdout"). Registry tests 36 and security tests 25 passed at the time of the review (the full-suite result must be re-checked, section 15).

- **One event per horizon, all arms together.** An owner-signed AUTHORISED record binds the signer, date, protocol id, protocol file sha256, authorisation-text sha256, dataset (matrix) sha256, DatasetSpec config sha256, harness config sha256, fold-definition sha256, the code version string, and ALL THREE arms with their `feature_list_sha256` and fit-recipe hashes. A partial or different arm set, or any different hash, is refused.
- **Entry sequence (normal):** `AUTHORISED` (owner) -> `STARTED` (harness, before any holdout fit; names the marker file and record directories) -> `RESULTS_EXPOSED` (harness, written and fsync'd after the holdout fit and **before the first holdout prediction exists**) -> `COMPLETED` (harness, with every arm's record hash). `COMPLETED` needs `RESULTS_EXPOSED` first. If writing `RESULTS_EXPOSED` fails, no prediction is made.
- **A STARTED event without COMPLETED means the holdout is CONSUMED.** Changing the output folder, marker directory, run name, a copy of the protocol, the code version string, or deleting the registry file re-opens nothing (demonstrated on synthetic data; the local guard file detects a truncated registry on this machine).
- **No recovery after exposure.** Recovery after `RESULTS_EXPOSED`, `COMPLETED` or a second crash does not exist; the machine refuses whatever the owner states. A further event then needs a new owner-signed AUTHORISED entry naming the consumed event it supersedes, a reason and a NEW protocol id.
- **Recovery procedure text (to be signed):**

> A holdout run that stops without a `COMPLETED` entry never re-opens the holdout by itself. Only the owner may authorise ONE recovery per event, and only when ALL of the following hold: (a) the latest registry state of the event is `STARTED` or `ABORTED`; (b) there is no `RESULTS_EXPOSED` entry for the event; (c) no `holdout_*.json` file exists in any record directory named in the `STARTED` entry; (d) the owner checked these facts by running `verify()` and reading the registry, and states that no holdout prediction, metric or record was observed. If any of (a) to (d) fails, or after `RESULTS_EXPOSED`, `COMPLETED` or a second crash, no recovery exists: a new event requires a new owner-signed `AUTHORISED` entry that names the consumed event it supersedes, a reason and a NEW protocol id. The recovery entry cites the `STARTED` line hash, repeats every bound hash, carries the signer, the date and the hash of a recovery text that has never been used before, and is used up by the next `STARTED`. **The recovered run must use a fresh marker directory** (a marker file that does not exist and differs from the crashed run's); the crashed run's marker is never deleted or edited. Before any holdout run the owner confirms that the working copy holds the current committed registry, runs from that single working copy, and commits and pushes the registry after `STARTED` and after `COMPLETED`. Preferably the owner makes a signed git tag over each of those registry commits.

- **Hard-kill windows** [V on synthetic data]: kill before STARTED (no recovery needed); during the fit before the marker (recoverable once); after the fit with a failed or torn marker write (recoverable once after the owner trims the torn line; `predict` never ran); after the marker (impossible, new protocol id); records written but COMPLETED missing (impossible; the owner may still write COMPLETED as bookkeeping, no new evaluation).
- **Residual risks, stated plainly** [V from the security review]: (1) a determined owner can rewrite git history and the local guard and re-run: the registry deters accidents and casual edits, it is not adversary-proof; (2) the "signature" is a name, a date and a text hash, not cryptography; (3) a registry copy that is behind (another clone that has not pulled the STARTED commit) is undetectable by code: the holdout is run from ONE working copy at the committed head; (4) record directories are scanned only where STARTED names them; (5) a kill right after the marker closes the holdout although nothing may have been seen: accepted; (6) a torn tail blocks every operation until the owner trims it (an owner edit, visible in the diff); (7) on Windows a directory cannot be fsync'd: read the registry back after STARTED and commit it. **RECOMMENDATION [P]: signed git tags over the registry commit after AUTHORISED, after STARTED / RESULTS_EXPOSED, and after COMPLETED, with the tag hashes published (for example in the experiment register), so any later rewrite contradicts them.** No keys are implemented in code.
- **Other guards**: the harness requires the protocol file path and a fit function carrying `recipe_sha256`, requires seed 42, refuses to run without an approval file naming this candidate and the exact config hash, and writes each result as an exclusive-create read-only JSON record sealed with its own sha256.

## 11. Reproducibility and immutability

- **Records**: one JSON per (arm, fold) carrying the dataset, row-list, fold, feature-list, config and harness hashes and the code version string, which must be the **full signing commit hash** (B11: commit the empty registry, the harness, the recipe, the registry code, the verdict code and these protocol files first; the code version is that commit). Any later commit means regenerating the hash sheet and re-signing.
- **Verdict parameter set** (frozen dataclass, canonical JSON, sha256; shown here with the PROPOSED MDE_H and the current code-version string, **ILLUSTRATIVE: the hash is recomputed at signing**):

```
{"alpha_loose":0.05,"alpha_strict":0.025,"block_multiple":2,"burn_in_folds":4,"code_version":"sx_verdict_v0_PROPOSED","draws":2000,"fail_upper_alpha":0.05,"holm_mode":"single_horizon","horizon":10,"last_fold_index":33,"mde_h":0.0024,"min_days_multiple":2,"min_eligible_folds":12,"min_fold_days":10,"min_fold_picks":20,"min_picks":100,"min_stocks":10,"primary_arm":"C_56","r1_share":0.6,"reference_arm":"A_53","seed":7,"top_k":5}
```
  Illustrative parameter-set sha256: `f67b691466c4c10a22ef61fd72ab0bbf63b23e354a87e413d23c3c01ee2a6bcf`. Illustrative verdict-code sha256 of the working-copy `ml/sx_verdict.py` at preparation (CR/CRLF normalised): `da0638f1fb96fe3d6ffbe69885c2cb73fdea7761dbe24ff78995efe4e3edb95e`. **Both change** if MDE_H changes, if the code-version string `sx_verdict_v0_PROPOSED` is replaced by a final name, or if any byte of the file changes (including a docstring that names a renamed document). The signed text names the final values.
- **Write-once verdict**: the output file is created with exclusive-create by the caller (the module is pure and does not do this itself; a thin signed caller is part of the training-authorisation review), names ONE run id, and stores the code hash, the parameter hash, the record hashes and the outcome word. `compute_verdict` returns a `record_sha256` over its canonical JSON; the same input in any file order gives identical text.
- **Run environment**: part of the recipe hash (section 6). A lock file `backend/requirements-research.lock` with exact `==` pins from `pip freeze` of the signing environment is recommended and its sha256 would be named here (OWNER DECISION; not created in this draft). The in-code refusal on the five tracked library versions is the hard guard. pip-freeze sorted-lines sha256 on the preparation machine: `3e1095b7c20e1621fe6982c76cc0dfc87953ccde3782d2deecb741a4d04eee3c` (97 lines; it describes that machine and moves with any package change). [V]
- File hashes are over committed bytes (`git show <commit>:<path> | sha256sum`); the registry is stored `-text` so git never converts its line endings.

## 12. Isolation

Research only. [V in code, tested] The research models never enter `ml_models`, the production model directory, the model registry table, production scoring (`ml/predict.py`), the h05 lane, the brain, strategies, the scheduler, paper orders or any order. Nothing in the app imports `sector_research`, `sector_walkforward`, `sx_recipe`, `holdout_registry` or `sx_verdict` (a test enforces it). Output goes only under `backend/data/research_models/<candidate>/...` (gitignored); the writer refuses the production model directory and any path containing `ml_models`. Nothing is written to the database (SELECT only). `ml/features.py`, `ml/predict.py`, `ml/sector_map.py`, `ml/dataset.py`, `ml/train.py` and everything fingerprinted in `backend/tests/trial_freeze.json` are unchanged. The sealed 15-day trial, `wf-protocol-v1`, `fd-protocol-v1`, `td-protocol-v1`, the h05 lane, Phase B, the unsigned td-protocol-v2 draft and the 129 held-back stocks are untouched. SX10 shares no code or evidence with the td-protocol-v2 draft. ASIANPAINT and BHARTIARTL stay UNMAPPED (their sector inputs would be missing, never 0; `include_unverified` is not exposed to the research path).

## 13. Limitations

### BLOCKING: must be decided before signing

| # | Item | Why it blocks |
|---|---|---|
| K1 | **MDE_H** signed number (and E\* owner input) | the verdict code refuses to run without MDE_H; it separates FAIL from INCONCLUSIVE |
| K2 | **D-Q10: the SX10 primary quantity** (raw 10-session forward return recommended) | the harness and the earlier text disagree; choosing after records exist would be a choice made with outcomes in view |
| K3 | **FAIL / INCONCLUSIVE rule and the single-horizon 2.5% Holm timing** | NEW; decides what the printed words mean |
| K4 | **R4 definition** (holdout mean > 0 and development mean > 0, strict) and the **PENDING_HOLDOUT** wording; **when the holdout is run (D-H)** | NEW; a choice made before results |
| K5 | **Limitation U** accepted verbatim | replaces the old breadth-only caveat |
| K6 | **Whether to run this protocol at all** given the power (section 8) (central 0.24 pp against an assumed realistic 0.03 to 0.13 pp; PASS chance 7% to 20%; about 1.5x harder than SX5; it could be folded into SX5 as a descriptive extension) | a programme choice |
| K7 | Fold numbering fixed as 0-based; burn-in folds 4 to 33; holdout wording; 100% fit; inert subsample; `n_jobs=1`; pinned environment | B1 to B7, B9 to B14 defaults accepted as the basis; must be signed as one text |
| K8 | Hash sheet regenerated on the signing commit; code version string = full commit; final verdict code-version name; clean full-suite result | the binding of code to text |
| K9 | Rename and redate files that carry assumed dates (checklist table), BEFORE the code is hashed | code docstrings name some of them |

### NON-BLOCKING: must be read; they limit what any result can mean

- **L1 Breadth survivorship** (section 4): R_37 comparisons are confounded; C_56 minus A_53 unaffected by breadth. [V]
- **L2 Input-gap selection**: the 1,103 removed rows are one five-week rally window (breadth 0.87 against 0.60 for all development rows) plus 22 MFI rows, removed for all arms; no sector concentration. [V]
- **L3 R_37 / `obv_slope`**: research reference only (section 4). [V]
- **L4 Bullish training windows**: 81% to 94% bullish; folds 0 to 18 never saw a drop worse than 10%; results say little about falling markets. [V]
- **L5 Effective sample** (section 8): INCONCLUSIVE or FAIL-with-weak-meaning is likely; never read a null as proof of no effect. [V]
- **L6 HINDUNILVR fresh fetch pending**: 187 rows absent; HUL missing from late test days. If the fetch changes anything, every hash is reissued. [V]
- **L7 Exposure-ledger status of the holdout prices**: used in earlier diagnostics; the holdout is untouched only for SX models and labels. Record this in the ledger. [V]
- **L8 Survivor-biased 47 stocks**, ASIANPAINT and BHARTIARTL not covered, static sector labels, thin sector groups (COMMODITIES, HEALTHCARE, CONSUMPTION one stock each) (Limitation U). [V]
- **L9 Platform differences**: LightGBM scores may differ across platforms and builds. [V]
- **L10 Registry tamper evidence is procedural** (section 10). [V]
- **L11 Programme-wide multiplicity** (section 14). [V]
- **L12 Overlap with other work**: SX10 is the sector-only half of td-protocol-v2 B1 (B1-5, B1-7 and B1-8 equal its three inputs; B1-6 was dropped from SX10 as redundant). The protocols stay independent (B16): no shared promotion evidence unless equivalence is demonstrated in writing and approved; B1's re-scope or retirement is decided separately. [V]
- **L13 Daily bars** cannot order target and stop inside a day; no liquidity or circuit-limit modelling; entry at the decision-day close, not an executable trade. [V]
- **L14 Index bar arrival times UNKNOWN** at decision time (`index_availability_v2.md`). [V]
- **L15 Ideas per fold**: picks are counted as 5 per day before any no-repeat rule, so the "20 picks" test never binds; a different count (after a no-repeat rule) is not implemented. [V]
- **L16 Verdict code is a thin pure module**: write-once file, run-id naming and the holdout day count are the caller's job. [V]
- **L17 A5 / economics**: `ten_day.score_trade` is reported beside the ranking result as an appendix diagnostic with no weight (section 5). [P]
- **L18 Cohort rule for a forward test** (delisting) must be written in advance (section 2). [P]

## 14. Experiment-register entry and multiple testing

**Register entry text** (to be written into `docs/brain/EXPOSURE-LEDGER.md` at signing, BEFORE any training; B17):

> Candidate SX10 (paired comparison C_56 minus A_53, 10-day, 47-stock cohort). Protocol id: ______ (set at signing). Row-list sha256 `d10ef048f52a7bfe377472ff51814f8f3710998a5847f3159e7ae66fe359b444` (45,700 rows). DatasetSpec config sha256 `3c1507a9324b93417f3f9000e431778da944eb817a7631070112a96455842be5`. Fold-definition sha256 `a39693b0640106ee92bfeb81972ec6855576dec94ce50249ffa7a0b0dcbddaae`. Recipe sha256 `fa6b3e97...` (recompute at signing). Verdict parameter-set sha256 ______ and verdict code sha256 ______ (set at signing). MDE_H ______ pp (signed). Seed 42. Signing commit ______. "No outcome read." Holdout 2026-02-01 to 2026-08-14 scored once, only for SX models and labels (prices were used in earlier diagnostics). Training not before 2026-12-04 and only with a separate explicit approval.

**Count.** This is one pre-registered paired comparison (one change, three inputs, one horizon). With the sister candidate it is two. In the wider programme the signed or drafted candidates (Phase B 3, selection lab 6, the td-protocol-v2 draft B1 if signed, SX5, SX10) come to **11 to 12** comparisons on largely the same prices. Illustration (assumes independent tests at 5%): the chance that at least one of 11 passes by luck is about **43%** (1 - 0.95^11), of 12 about **46%**; for the two SX candidates alone, uncorrected, 9.75%. With the rule above the simulated false-PASS rate when the true effect is zero is 2% to 4% per horizon (R1 + R2 at the 2.5% bound) and 4.0% to 7.5% for either horizon under Holm (2.1% to 4.5% with R4); the single-horizon rule used here is stricter than Holm for the second horizon, so the pair figure is expected to be at or below those (not separately simulated) [A]. This is why a PASS can only justify a forward shadow test and why the primary metric is fixed (R1, R2) while IC and hit rate are descriptive.

**Relation to other work.** SX10 is independent of td-protocol-v2 B1 (exact differences in `sx10-vs-tdv2-b1-differences`, file name carries an assumed date): different question (3 official-sector inputs on the 53 against 8 inputs on 37 to 46), different sector definition, retrospective walk-forward against a forward-only shadow lane, ranking-based against absolute benchmarks. No SX10 result is reported as a B1 result or the reverse. **td-protocol-v1 FAILED on 2023-07-01 to 2025-01-31** (picks beat every stock in 8 of 21 eligible folds, lower bound -0.31%; average -0.34% per trade over 1,980 finished ideas against -0.22% for every stock; NIFTY 50 held -0.18%); that result stays on record, SX10 does not replace or re-run it and is not a re-tune (target, stop, horizon, top 5, costs are td-v1's). The td-protocol-v2 draft says no unseen 10-day history is left: A and B see the same data, so the comparison is fair, but a pass cannot be called independent proof. It does not touch the h05 lane, production models 2, 16, 17 or the sealed 15-day trial.

## 15. Approvals still required (nothing proceeds until each is done)

- [ ] **A1** Sign this protocol text and its sha256 (the owner personally; no session, subagent or automated process signs). An approval file needs a `protocol_id`.
- [x] **A2** Decided: A_53 primary baseline, R_37 reference, C_56 challenger.
- [ ] **A3** Folds, holdout and the replacement "Final holdout" wording (sections 7).
- [ ] **A4** Pass rule R0 to R5 and the outcome words PASS / FAIL / INCONCLUSIVE (section 9), including D-H, R4 and PENDING_HOLDOUT, and that they are new.
- [ ] **A5** Economics reported as a DIAGNOSTIC only, with no weight in PASS, FAIL or INCONCLUSIVE, now or later, unless a new protocol id says otherwise (PROPOSED: a fixed yes-as-diagnostic; the earlier "unless you explicitly sign it" door is closed).
- [ ] **A6** Experiment-register row written at signing (section 14).
- [ ] **A7** Owner review of the harness, recipe, registry and verdict code at a named commit; the code version string equals the full commit hash.
- [ ] **A8** HINDUNILVR: exclusion accepted as it stands, or the fresh-fetch comparison done (then all hashes are reissued).
- [ ] **A9** Approval file naming candidate `SX10` and the complete `config_sha256` `3c1507a9324b93417f3f9000e431778da944eb817a7631070112a96455842be5`.
- [ ] **A10** S-9 read and **MDE_H signed** (and E\* supplied). Computed, see section 8.
- [ ] **A11** A **separate, explicit training authorisation** dated on or after 2026-12-04. None exists; none is implied by signing this document. Signing is not a go.
- [ ] **A12** Later and separate: the holdout AUTHORISED record in the registry (not requested now), then signed git tags over each registry commit.
- [ ] **A13** The hash sheet regenerated on the signing commit equals section 3; clean full-suite result recorded; assumed-date files renamed or redated (checklist).

Protocol signed (owner): ______________________    Date: ____________

Signing commit (full 40-hex): ______________________________________________

Protocol id: ______________    MDE_H signed: ____________ pp    E\* supplied: ____________ pp

(DRAFT: not signed, not tagged.)

## Appendix: source documents behind this draft

File names below carry assumed dates (see the checklist): the two protocol drafts, the model recipe final draft, the pre-signing findings (S-1 to S-9), the blockers summary (B1 to B19), the two approval packages, the S-9 power analysis, the survivorship and rule audit, the verdict code spec, the holdout registry security review, the hash convention and environment note, `final_verification_v3.md`, `final_hashes_v3.json`, `apollohosp_mutation_check_v1.md`, `feature_manifests_v3.json`, and the SX10-versus-td-v2-B1 differences note.
