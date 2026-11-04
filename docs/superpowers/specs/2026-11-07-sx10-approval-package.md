# SX10 approval package (2026-11-07): sector inputs for the 10-day model

**Status: DRAFT FOR OWNER APPROVAL. UNSIGNED, untagged. Nothing is trained, nothing is fitted on real data, the holdout has not been evaluated, no authorisation exists.** Training stays unauthorised: none before 2026-12-04 and none afterwards without a separate, explicit approval. Signature lines below are blank on purpose. Companion files: `2026-11-05-sx10-research-protocol-DRAFT.md` (full protocol draft), `2026-11-07-sx-blockers-summary.md` (the decisions both packages share), `docs/brain/evidence/sector_prep/final_verification_v3.md` and `final_hashes_v3.json` (verification and complete hashes).

## 1. Plain-English summary

- **The question.** Does giving the existing 10-day model three extra numbers about the stock's sector (how the sector index did against NIFTY 50 over 10 days, where the sector ranks among 15 sector indices, and how the stock did against its own sector) help it pick better stocks? The three numbers come from official NSE sector indices.
- **How it is tested.** Three versions of the same model recipe are trained on exactly the same rows and dates, one fold at a time, each fold scored only on later days: **A_53** (the 53 existing inputs; the baseline that counts), **R_37** (the 37 inputs of production model 2; a reference only) and **C_56** (the 53 plus the three sector numbers; the challenger). The one comparison that decides is C_56 minus A_53 on each day's five highest-scored stocks against all eligible stocks.
- **What a good result means.** At most 'worth a forward shadow test'. These stocks and this history have been looked at before, and about a 43% chance of at least one lucky pass exists across the whole research programme. A flat or unclear result ('INCONCLUSIVE') is the most likely outcome and is stated in advance.
- **What it does not do.** It changes no live model, no h05 lane, no sealed trial, no signed protocol, no order. The research models are never stored with production models and never score anything.
- **State today.** The data and checks are prepared and verified (45,700 rows; hashes below). The code (harness, recipe, holdout registry) is built and tested with synthetic data only. The holdout registry is empty: no holdout run is possible until the owner signs an authorisation. What is still needed from the owner is listed in section 15.

## 2. Dataset

**Stocks.** 47 of the 49 model stocks (ASIANPAINT and BHARTIARTL have no verified official sector index and are left out, owner decision 2026-11-05): ADANIENT, ADANIPORTS, APOLLOHOSP, AXISBANK, BAJAJ-AUTO, BAJAJFINSV, BAJFINANCE, BPCL, BRITANNIA, CIPLA, COALINDIA, DIVISLAB, DRREDDY, EICHERMOT, GRASIM, HCLTECH, HDFCBANK, HDFCLIFE, HEROMOTOCO, HINDALCO, HINDUNILVR, ICICIBANK, INDUSINDBK, INFY, ITC, JSWSTEEL, KOTAKBANK, LT, M&M, MARUTI, NESTLEIND, NTPC, ONGC, POWERGRID, RELIANCE, SBILIFE, SBIN, SHRIRAMFIN, SUNPHARMA, TATACONSUM, TATASTEEL, TCS, TECHM, TITAN, ULTRACEMCO, UPL, WIPRO.

**Rows.** 45,700 eligible stock-days, decision days 2022-09-15 to 2026-08-24. Row-list sha256 (sorted `SYMBOL|YYYY-MM-DD`, newline separated): `d10ef048f52a7bfe377472ff51814f8f3710998a5847f3159e7ae66fe359b444`. File: `docs/brain/evidence/sector_prep/sx10_47_rows_v3.txt.gz`. The owner decided on 2026-11-07 that the population is 45,700 rows and that no artificial exclusion rule is added to keep the older count (45,695); the five extra rows are APOLLOHOSP 2022-10-27 and 2022-11-01 to 11-04 (verified: valid point-in-time inputs, matured labels, training rows only; `final_verification_v3.md`).

**Reconciliation, raw to final** (each row counted once, at the first reason that applies; overlaps are in `reconciliation_v3.md`):

| Step | Rows removed | Reason | Rows left |
|---|---|---|---|
| Raw stock-days of the 47 stocks | 0 | all daily bars | 59,314 |
| Warm-up | 11,844 | first 252 sessions of each stock (47 x 252): long-window inputs are not defined yet | 47,470 |
| Label not finished | 470 | last 10 sessions of each stock (47 x 10): the outcome is not known | 47,000 |
| Corporate-action window | 187 | HINDUNILVR demerger of 2025-12-05, price adjustment still PENDING a fresh fetch (177 feature-window rows and 10 label-window rows); other events are retained (RELIANCE 2023-07-20 and ITC 2025-01-06 verified adjusted) | 46,813 |
| Existing-input gap | 1,103 | 1,081 rows of one window (2022-08-11 to 2022-09-14, all 47 stocks, no VIX rank yet: INDIA VIX starts 2021-09-13) plus 22 rows where MFI is undefined | 45,710 |
| Sector gap | 10 | APOLLOHOSP, early rows where the NIFTY HEALTHCARE history is too short for a sector input | 45,700 |

Final: **45,700** (assembler and reconciliation agree: identical row sets, 0 differences). Against the full-49 baseline (existing inputs only) the 47-stock set loses 1,964 rows (4.12%): ASIANPAINT and BHARTIARTL (unmapped) and 10 APOLLOHOSP rows. Exclusion files used by the configuration: `docs/brain/evidence/sector_prep/excluded_rows_h10_v2.csv` (sha256 `0aaec2b5b1e4a79620df5d683f4506c4bdf4a501be2ed0a28d36535cd3cf9372`, 187 rows, all HINDUNILVR); `events_input_v2.csv` sha256 `23f145d80e6ce64e784c5db4d93d479929f4c429fcf369c84aa4b46710b649cf`. There are no v3 exclusion files (the C_56 change did not alter exclusions).

## 3. Inputs: the three manifests

Exact ordered column lists are in `final_hashes_v3.json`. Two hash forms are recorded because both appear in the evidence; the harness and registry bind the second.

| Arm | Columns | manifest sha256 (`json.dumps(list)`) | feature_list_sha256 (harness, bound in records and registry) |
|---|---|---|---|
| A_53 (baseline) | 53 | `f5a8d398d56e47d8bce33943ea78d50d949933022d12c2cb6ef24f5792086f29` | `3bd35e8549ebddcea9f52ee680530cdef80a4bb524cf74b1a04c328e1a7141c4` |
| R_37 (research reference) | 37 | `0615e2fb6c1c9ae120d1455895ad39d3422fcc1bd2053c4bd4b1a1476946d122` | `b00fc7076853bbd56ba3f32d254a57cfbc89ef19969f27564c4d5ac4939574c5` |
| C_56 (challenger) | 56 | `1a691d7df13366b2c438e5024878bfc228adaa4c77560a39ac39bfd3fd22b910` | `123aa67a611a564d3e41a362b018c08f2d7d18606079abb3d3acb62c01303a0e` |

A_53 = `ml/features.FEATURE_COLUMNS`. R_37 = the 37 names saved in production model 2, same order (checked against the saved list; `model2_saved_features_v1.json`). C_56 = A_53 plus `sector_ret_10d_vs_nifty`, `sector_rank_10d`, `stock_vs_sector_10d` (the fourth proposed input, `sector_ret_20d_vs_nifty`, was dropped on 2026-11-06 because it equals the difference of two existing inputs; owner accepted C_56 on 2026-11-07). R_37 is a **37-feature research reference, not an exact production replay**: see section 13.

## 4. Frozen fit recipe (same for every arm)

One LightGBM recipe (`ml/sx_recipe.py`, `sx_recipe_v1`), written out in full so it can be hashed: 400 trees, learning rate 0.05, depth 6, 31 leaves, column sampling 0.8, row sampling 0.8 (inactive: `subsample_freq` stays 0 exactly as in production), min child samples 50, L1 and L2 0.1, balanced class weights, seed 42, `n_jobs=1`; a StandardScaler fitted on the training rows only; no tuning, no early stopping, no validation split, no calibration, no feature selection, no imputation. **Recipe sha256 `fa6b3e974f62a20a8363e3ceef34105b728bcf1b3a0fe502e2aa05d00e501233`** with library versions lightgbm 4.7.0, scikit-learn 1.9.1, numpy 2.5.4, pandas 3.1.0, scipy 1.18.1 (Python 3.12.6). Any other version set gives a different hash by design; a real run must happen in the environment named in the signed text, and the hash recomputed there. Full detail: `2026-11-06-sx-model-recipe-FINAL-DRAFT.md`.

## 5. Label

barrier (td-protocol-v1): target = 1 if the stock reaches +6% before -3.5% within 10 trading bars (`ml/features.build_label`; `ten_day.TARGET`, `STOP`, `HORIZON_BARS`); a same-bar touch of both counts as the stop. The last 10 sessions of each stock are dropped.

## 6. Folds and purge

Development folds: 34 back-to-back 28-calendar-day test windows, 2023-07-01 to 2026-01-31 (642 test days, 30,111 test rows, 13 to 21 days per fold). Each fold is trained on an expanding window of rows whose whole label window ended before the test window starts, and whose decision day is not among the last 10 sessions before the test start (purge 458-470 rows per fold; the embargo removes no further row). Training rows per fold: 8,725 (fold 0) to 38,248 (fold 33). Final holdout: decision days 2026-02-01 to 2026-08-14 (133 days, 6,118 rows), fit set 38,846 rows, scored once. The five restored rows are in the training set of all 35 fits and in no test set; per-fold test rows are identical to the previous version (`final_verification_v3_folds.csv`). Fold-definition sha256 (dev folds plus holdout, the value bound for a holdout run): `a39693b0640106ee92bfeb81972ec6855576dec94ce50249ffa7a0b0dcbddaae`; development folds only: `fe4f133f20aafe39ff4c3d696e5c49ab5061c5d88098f3dd5b8e4545eb3bd023`. Independent recount of the purge: 0 mismatches in 35 folds.

## 7. Primary comparison and statistical procedure (PROPOSED: S-1 to S-9)

**The one primary comparison:** C_56 minus A_53 on the daily top-5 excess return over every eligible stock, same days, same stocks. Everything else (A_53 minus R_37, C_56 minus R_37, IC, hit rates, random-5, NIFTY, economics, market-type splits) is secondary or descriptive and carries no pass/fail weight.

These are the findings-file proposals (`2026-11-06-sx-presigning-findings.md` section 5). They REPLACE the draft's block = horizon and its un-corrected pass rule, and are the reason it blocks signing: day-level or row-level intervals were 1.7x (5-day) to 2.2x (10-day) too narrow in a synthetic demonstration, with false 'lower bound above 0' rates of 15-20% against a nominal 5%.

- **S-1 Unit.** The decision day. The daily value is the top-5 forward return minus the every-eligible-stock mean. Pooled rows, picks or folds are never the unit of an interval. Days with fewer than 10 eligible stocks are left out, as now.
- **S-2 Paired series.** D_t = (C_56 daily value minus A_53 daily value) on the same day, over the pooled contiguous development test days of the folds counted.
- **S-3 Interval.** Moving-block bootstrap of D_t: non-circular blocks of consecutive days, block length 2 x horizon (20 days for SX10), ceil(n / block) blocks per draw, 2,000 draws, seed 7; report the mean and the one-sided lower bounds at 5% and 2.5%. Block = horizon, block = 3 x horizon and day-iid are sensitivity only, never for pass/fail.
- **S-4 One primary comparison per horizon.** C_56 minus A_53 on daily top-5 excess over every eligible stock. Nothing is added after results.
- **S-5 Multiplicity.** The family is the two primaries (SX5, SX10). Holm: the smaller p-value must clear the 2.5% one-sided bound, the other the 5% bound. A PASS needs R1 and R2 at that level. The programme-wide count (11-12 comparisons on the same prices, about 43% chance of at least one lucky pass) is recorded in the register; it is the reason a PASS only proposes a forward shadow test. No programme-wide Bonferroni is applied.
- **S-6 Folds.** R1 uses per-fold means of D_t over eligible folds (at least 10 test days and 20 ideas). R1 is a consistency check; R2 carries the inference.
- **S-7 No peeking.** Block length, draws, seed, bounds, folds counted and the primary quantity are fixed at signing. The analysis is computed once from the immutable records. The holdout is scored once. No change to block, metric, fold set or threshold after any result; any change needs a new protocol id and the old result stays on record.
- **S-8 Holdout.** Report the paired difference on the 133 holdout days with the S-3 interval. It is a sign-consistency check (R4), not a second chance.
- **S-9 Minimum detectable edge.** Compute it before approval on a synthetic series with the measured dependence (about 246 effective days for 5-day, about 95 for 10-day) and state that INCONCLUSIVE is the expected outcome for any realistic edge, especially 10-day. **NOT YET COMPUTED** (open item before signing).

**Multiple-testing record.** This is one pre-registered paired comparison per horizon; with the sibling candidate it is two (the Holm family). In the wider programme the signed or drafted candidates (Phase B 3, selection lab 6, the td-protocol-v2 draft B1 if signed, SX5, SX10) come to 11-12 comparisons on largely the same prices: 1 - 0.95^11 = 43%, 1 - 0.95^12 = 46% chance of at least one lucky pass; for the two SX candidates alone 9.75%. The register row (`docs/brain/EXPOSURE-LEDGER.md`) is written before any training: candidate, row-list hash, config hash, fold hash, seed, date, 'no outcome read'.

## 8. Success criteria R0 to R5 (PROPOSED; none is agreed until accepted)

Copied BY REFERENCE, not re-decided: td-protocol-v1 section 5 (eligible fold at least 10 test days and 20 finished best-5 ideas; at least 12 eligible folds and 100 ideas else INCONCLUSIVE; 60% of eligible folds; block bootstrap 2,000 draws, seed 7). Rows marked NEW are not in any signed protocol.

| Row | Needs | Source |
|---|---|---|
| R0 Same rows | the A_53, R_37 and C_56 eligible row lists are identical (equal sha256; the harness refuses to run otherwise) | NEW |
| R1 Paired skill | C_56 beats A_53 on the daily top-5 excess over every eligible stock in at least 60% of eligible folds (with S-6; and, if you accept the burn-in rule, over folds 4-33 only) | NEW row; the 60% is borrowed |
| R2 Paired lower bound | 5th percentile of the mean daily difference (C_56 minus A_53) is above zero | NEW row; bootstrap settings borrowed (td-v1 block 10). **S-3 and S-5 revise this to the block-2h bootstrap and the Holm bound; that revision is NEW and needs your acceptance** |
| R3 Enough data | at least 12 eligible folds and at least 100 finished best-5 ideas, else INCONCLUSIVE | borrowed |
| R4 Holdout agrees | the paired difference on the final holdout has the same sign (reported; not a second chance to pass) | NEW |
| R5 No harm | C_56's worst fold versus A_53's worst fold (and R_37's) is shown (descriptive; no numeric threshold invented) | NEW, descriptive |

Outcome words: **IMPROVES** (R0 to R4 all met), **NO IMPROVEMENT** (enough data and R1 or R2 not met), **INCONCLUSIVE** (R3 not met). IMPROVES only means 'worth proposing a forward shadow test'; it never activates anything. A null or negative result is stored with equal prominence. Nothing is changed after a result is seen.

## 9. Diagnostics (no pass/fail weight)

- **After-cost performance, descriptive.** `ten_day.score_trade` exactly (+6% / -3.5%, 10 bars, no half-out, entry at the next open, stop before target, 0.10% slippage per side in total, charges on the shared scorer's Rs 40,000 position) reported beside the ranking result; the pass rule is ranking-based.

- Daily rank IC, top-5 hit rate against every-stock hit rate, top-5 minus random-5 (200 seeded draws), against NIFTY 50 held over the same days, per-fold results, worst fold, market-type split. All computed by the same code for every arm.

## 10. Relation to td-protocol-v2 B1

SX10 and the td-protocol-v2 draft's B1 (breadth plus four sector inputs, judged forward in a shadow lane) are **independent protocols**. SX10's three inputs equal B1-5, B1-7 and B1-8 in concept (B1-6 was dropped as redundant). The exact differences are in `2026-11-05-sx10-vs-tdv2-b1-differences.md`. No SX10 result may be reported as a B1 result or the reverse, and no promotion evidence is shared unless equivalence is demonstrated and you approve it in writing. If SX10 is signed, B1 should be re-scoped or retired so the idea is not counted twice; that is your decision (SX10 draft A5) and is not made here. td-protocol-v1 FAILED on 2023-07-01 to 2025-01-31 (picks beat every stock in 8 of 21 eligible folds; average -0.34% per trade against -0.22% for every stock); that stays on record, and SX10 is not a re-tune (target, stop, horizon, top 5 and costs are td-v1's).

## 11. Holdout authorisation safeguards

- **No authorisation exists today.** The registry file `docs/brain/evidence/sector_prep/HOLDOUT-REGISTRY.jsonl` is 0 bytes. A real holdout run is refused ('no owner authorisation exists for the horizon-10 holdout'); demonstrated on 2026-11-07 (`final_verification_v3.md` section 1c).
- **One event per horizon, all arms together.** An owner-signed AUTHORISED record binds the signer, date, protocol id and file sha256, the sha256 of the authorisation text, the dataset sha256, DatasetSpec config sha256, harness config sha256, fold-definition sha256, the code version string, and ALL THREE arms with their feature-list and fit-recipe hashes. A run with a partial or different arm set, or any different hash, is refused.
- **STARTED is written before any holdout fit.** A STARTED event without COMPLETED means the holdout is CONSUMED. Output folder, marker directory, run name, seed, a copy of the protocol, deleting the registry file: none re-opens it (all demonstrated with synthetic data).
- **Crash rule.** An exception or a hard kill after STARTED leaves the holdout consumed. Only a RECOVERY_AUTHORISATION, signed by the owner, citing the STARTED line by hash and stating that no holdout predictions or metrics were observed, permits exactly one further attempt with the same hashes. A second event for the same horizon needs a signed authorisation naming the consumed event it supersedes and a reason.
- **Tamper evidence.** The file is append-only and hash-chained; a local guard file detects a truncated tail on this machine. Honest limit: this protects against accidental or casual editing, not against a determined owner who rewrites git history and the local guard; the 'signature' is a name plus the hash of the authorisation text, not a cryptographic signature.
- **Other guards.** The harness refuses any non-holdout fold whose test window reaches 2026-02-01; requires the protocol file path and a fit function carrying `recipe_sha256`; requires seed 42 on a real run; refuses to run without an approval file naming this candidate and the exact config hash; writes each result as an exclusive-create, read-only JSON record sealed with its own sha256.

## 12. Reproducibility and isolation

- **Immutable records**: one JSON per (arm, fold), carrying the dataset, row-list, fold, feature-list, config and harness hashes and the code version string (the full commit hash; this package was verified at `412a125a76db8e2afbdc6ba8f64d538fd7b187b8`). Dataset sha256 as the harness computes it (feature and label VALUES): `ee5eba79bfddda8d2f3cf347ff419d8961634ae9a398cf9c1587967608573d8c`. Harness config sha256 `69b049a8e1599711c2a2c08e3125c1e821cffc180722766f9ec670882b084933`; DatasetSpec config sha256 `3c1507a9324b93417f3f9000e431778da944eb817a7631070112a96455842be5`.
- **Run environment** is part of the recipe hash (library versions). LightGBM results can differ across platforms and builds; `n_jobs=1` is used for determinism; whether another machine reproduces bit-identical scores is UNKNOWN.
- **Isolation.** Research models are written only under `backend/data/research_models/` (gitignored); the harness refuses the production model directory and any path containing `ml_models`; nothing in the app imports these modules (a test enforces it); no database writes (SELECT only); the h05 lane, brain, strategies, scheduler, paper orders and `ml/predict.py` are not involved.
- **What stays unchanged**: the h05 trial and lane, the sealed 15-day trial, active models 2, 16 and 17, the signed protocols (`wf-protocol-v1`, `fd-protocol-v1`, `td-protocol-v1`), `ml/features.py`, `ml/predict.py` and everything fingerprinted in `backend/tests/trial_freeze.json`, and the 129 held-back stocks (not used).

## 13. Outstanding limitations (none blocks signing; all must be read before signing)

1. **Breadth survivorship.** `breadth_pct_above_sma50` and `breadth_advance_pct` are computed over today's 49 watchlist stocks for every past date. They are in A_53 and C_56 identically and absent from R_37; C_56 minus A_53 is unaffected; comparisons with R_37 are confounded and descriptive.
2. **Input-gap selection.** 1,103 rows (one 5-week rally window plus 22 MFI rows) are removed for all arms; 1,088 are before the first test fold, 15 are in test folds.
3. **R_37 is not a production replay, and `obv_slope`.** Training-era formula `obv.diff(10) / obv.rolling(20).mean().abs()` (models 2, 16, 17); current builder since `fcaef35` (2026-10-05) `obv.diff(10) / volume.rolling(20).mean()`. All three research arms use the current formula on the full history, so C_56 minus A_53 is unaffected; R_37 has the right names but not model 2's `obv_slope` values, and is retrained under the SX recipe, so no R_37 result is production performance. Production serves 400 bars, research uses the full history. The current implementation is not changed (owner, 2026-11-07); an exact production comparison, if ever needed, is a separate read-only audit from a trusted source in an isolated environment, without loading the production joblib.
4. **Bullish training windows.** Folds 0-3 train on under a year; folds 0-18 never trained through a NIFTY drawdown worse than 10%; every training window is 81-94% bullish.
5. **Effective sample size.** Consecutive days and overlapping labels are strongly dependent (about 246 effective days for 5-day, about 95 for 10-day, out of 838). INCONCLUSIVE is the expected outcome.
6. **HINDUNILVR.** The fresh-fetch comparison for the 2025-12-05 demerger is pending; its windows are excluded (187 rows) and the row-list hash assumes that. If the fetch changes this, the row list and every hash change and this package must be reissued.
7. **Ledger exposure of the holdout prices.** The exposure ledger lists every period up to 2026-09-07 as development data (holdout-period prices were used in earlier diagnostics), so the holdout is untouched only for the SX models and labels, not for the prices.
8. **Other.** Survivor-biased 47 stocks; ASIANPAINT and BHARTIARTL not covered; sector label per stock is static; thin sector groups (COMMODITIES, HEALTHCARE, CONSUMPTION 1 stock each); no liquidity or circuit-limit modelling; daily bars cannot order target and stop inside a day (stop first); rows are not independent.

## 14. Reproduction commands (read-only)

`python scripts/arm_row_counts_report.py --out-dir ../docs/brain/evidence/sector_prep --suffix _v3` recomputes the counts and config hashes (SELECT only; fits nothing).

## 15. Exact approvals still required (nothing proceeds until each is done)

Blocking decisions with recommended defaults are in `2026-11-07-sx-blockers-summary.md` part A (B1 to B16). In addition, specific to this candidate:

- [ ] **A1** Accept the protocol text (`2026-11-05-sx10-research-protocol-DRAFT.md` plus the S-1 to S-9 and wording revisions) and its sha256; an approval file needs a `protocol_id`.
- [x] **A2** Decided: A_53 primary baseline, R_37 reference, C_56 challenger (owner, 2026-11-05 and 2026-11-07).
- [ ] **A3** Folds and holdout (development 2023-07-01 to 2026-01-31, holdout 2026-02-01 to 2026-08-14) and the replacement 'Final holdout' wording.
- [ ] **A4** Pass rule rows R0 to R5 and outcome words, including that they are new, with the S-1 to S-9 revision.
- [ ] **A5** Relation to the td-protocol-v2 draft B1: independent (recommended), re-scope or retire.
- [ ] **A6** Experiment-register row written with the row-list, config and fold hashes before any training.
- [ ] **A7** Owner review of the harness, recipe and registry code, committed at a named commit; the code version string equals that commit.
- [ ] **A8** HINDUNILVR fresh-fetch comparison done, or the exclusion accepted as it stands.
- [ ] **A9** Approval file created by the owner naming candidate `SX10` and the complete `config_sha256` `3c1507a9324b93417f3f9000e431778da944eb817a7631070112a96455842be5`.
- [ ] **A10** S-9 minimum-detectable-edge computation done and read.
- [ ] **A11** A separate, explicit training authorisation dated on or after 2026-12-04 (none exists; none is implied by signing this package).
- [ ] **A12** Later and separate: the holdout authorisation record in the registry (not requested now).

Protocol signed: ______________________  Date: ____________

Approval file created: ______________________  Date: ____________

Training authorised (not before 2026-12-04): ______________________  Date: ____________

*Sibling package: `2026-11-07-sx5-approval-package.md`.*
