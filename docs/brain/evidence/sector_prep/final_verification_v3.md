# Final verification v3: SX5 / SX10, A_53 / R_37 / C_56

Status: **verification evidence, UNSIGNED.** Read-only (SELECT only) on the local database; no model was fitted on real data; no holdout was evaluated; nothing was signed or tagged. The scripts were scratch files (not in the repository); the numbers below are the record. Full hashes: `final_hashes_v3.json`.

Code: git HEAD `412a125a76db8e2afbdc6ba8f64d538fd7b187b8` (branch `change/sector-features-prep`), data end 2026-09-07, cut-off 2026-12-31, 47 mapped stocks of 49.

## Result in one table

| Check | SX5 | SX10 |
|---|---|---|
| Assembler rows equal the v3 row list (set equality) | PASS (45,935 rows) | PASS (45,700 rows) |
| v3 minus v2 = exactly the five APOLLOHOSP rows; v2 minus v3 empty | PASS | PASS |
| (i) as-of builder = batch builder on the 5 rows, all 56 inputs | PASS (max abs diff 0.0; 56/56 bit-identical per row) | PASS (max abs diff 0.0; 56/56 bit-identical per row) |
| (i) 25 random control rows, as-of vs batch, max abs diff | 0.0 (0 not built) | 0.0 (0 not built) |
| (i) mutation test: scramble all data dated after the decision day; the 56 inputs of the row do not move | PASS (5/5 rows) | PASS (5/5 rows) |
| (ii) labels matured; independent recomputation equals (forward return, target, label end date) | PASS (5/5 rows) | PASS (5/5 rows) |
| (ii) none in a holdout or dev test window (decision and label end before 2023-07-01) | PASS (in the test set of 0 folds) | PASS (in the test set of 0 folds) |
| (iii) arms matched: 0 missing values in any arm's columns; same train/test rows per fold | PASS | PASS |
| (iv) per-fold TEST rows identical v2 vs v3 (35 folds incl. holdout) | PASS | PASS |
| (iv) training-row difference v3 minus v2 | [5] in all 35 folds | [5] in all 35 folds |
| (iv) holdout test rows (6,118) identical v2 vs v3 | PASS (sha 6b84f05db3da0f6c...) | PASS (sha 6b84f05db3da0f6c...) |
| (v) independent purge recount equals the harness in every fold | PASS (0 mismatches; purge 230-235 rows per fold) | PASS (0 mismatches; purge 458-470 rows per fold) |
| (v) no training row's label window reaches its test window; train set equals the independent rule | PASS | PASS |
| (v) label end dates from candle positions equal the matrix label_end_ts, all rows | PASS | PASS |
| Stored v2 and v3 fold-coverage CSVs equal the recomputed numbers | PASS | PASS |

## 1a. The five restored APOLLOHOSP rows

Rows: APOLLOHOSP on 2022-10-27, 2022-11-01, 2022-11-02, 2022-11-03, 2022-11-04. They are in `sx5_47_rows_v3.txt.gz` and `sx10_47_rows_v3.txt.gz` and not in the v2 lists (a `diff` of the lists shows exactly these five lines and nothing else, for both horizons). 2022-10-28 is in neither list (it is not part of this restoration).

**Why they were dropped before.** The NIFTY HEALTHCARE index has no close on 2022-09-26, 09-27, 09-29, 09-30, 10-03, 10-04 and 10-06. The removed input `sector_ret_20d_vs_nifty` counted 20 sessions and was missing across that gap. The three remaining sector inputs use 10-session windows, and the last missing session (2022-10-06) lies outside the 10-session window of all five rows. The EXISTING input `sector_relative_strength_20d` (in A_53 and C_56) takes a 20-ROW return of the index, so on these rows its window reaches back further than 20 sessions: a definition difference, point-in-time valid and identical in both arms (`c56_decision_v3.json`).

Missing NIFTY HEALTHCARE sessions inside the 21-session window of each row: 2022-10-27: 09-27, 09-29, 09-30, 10-03, 10-04, 10-06; 2022-11-01: 09-30, 10-03, 10-04, 10-06; 2022-11-02: 10-03, 10-04, 10-06; 2022-11-03: 10-04, 10-06; 2022-11-04: 10-06.

### (i) Point in time

- All 56 inputs are finite on all five rows (A_53's 53 and R_37's 37 are subsets of the 56).
- As-of builder (`assemble_asof_row`: data cut at the decision day, breadth cut too) against the batch builder: max absolute difference 0.0 and 56 of 56 values bit-identical on each row, both horizons. 25 random other rows per horizon: max absolute difference 0.0.
- Mutation test: every stock, NIFTY 50, sector-index, VIX and breadth value dated after the decision day was replaced by random multiples (prices x0.5-2, volume x0.2-5, breadth random), the matrix rebuilt, and the 56 inputs of the row compared: bit-identical for 5 of 5 rows, both horizons. The label of each row did change, as it should. That the scramble really changes later rows was confirmed on the 2022-10-27, 11-03 and 11-04 runs (against the row 60 calendar days later); for 11-01 and 11-02 that calendar day is not a trading day, so the effectiveness check was not available for those two runs (the same scrambling code ran).

### (ii) Labels

**SX5** (endpoint: close 5 bars later >= +2%), recomputed independently from the raw candles (not with `build_label`):

| Decision day | Bars used | Label end | Forward return | Target |
|---|---|---|---|---|
| 2022-10-27 | 2022-10-28 .. 2022-11-03 | 2022-11-03 | -0.8315% | 0 |
| 2022-11-01 | 2022-11-02 .. 2022-11-09 | 2022-11-09 | -3.3283% | 0 |
| 2022-11-02 | 2022-11-03 .. 2022-11-10 | 2022-11-10 | -2.2279% | 0 |
| 2022-11-03 | 2022-11-04 .. 2022-11-11 | 2022-11-11 | +0.6007% | 0 |
| 2022-11-04 | 2022-11-07 .. 2022-11-14 | 2022-11-14 | +4.4492% | 1 |

**SX10** (barrier: +6% before -3.5% within 10 bars, a same-bar tie counts as a stop), recomputed independently from the raw candles (not with `build_label`):

| Decision day | Bars used | Label end | Forward return | Target |
|---|---|---|---|---|
| 2022-10-27 | 2022-10-28 .. 2022-11-11 | 2022-11-11 | -0.2358% | 0 |
| 2022-11-01 | 2022-11-02 .. 2022-11-16 | 2022-11-16 | -0.7115% | 0 |
| 2022-11-02 | 2022-11-03 .. 2022-11-17 | 2022-11-17 | +0.3924% | 0 |
| 2022-11-03 | 2022-11-04 .. 2022-11-18 | 2022-11-18 | +0.0944% | 0 |
| 2022-11-04 | 2022-11-07 .. 2022-11-21 | 2022-11-21 | +1.2894% | 1 |

Every window uses only bars after the decision day, every bar exists (data end 2026-09-07), the label end is before the cut-off 2026-12-31 and before the first development test start (2023-07-01). Forward return and target equal the matrix values; the label end date equals `label_end_ts` for all rows of the matrix (independent candle-position recount).

### (iii) Matched arms

The three arms are slices of one matrix, so row sets and fold splits are identical by construction. Verified: 0 missing values in the A_53, R_37 and C_56 columns over all rows; `plan_folds` gives identical train and test row counts for the three arms in all 35 folds. The harness's `assert_identical_across_arms` runs on every real run (it needs a fit, so it was not run here). Test days per fold are identical because test rows are identical.

### (iv) Where the five rows enter

- **SX5:** in the TRAINING set of every development fold (indexes 0 to 33) and of the holdout fit set (35 of 35); in the test set of 0 folds. Training rows v2 -> v3: fold 0 8,955 -> 8,960; fold 33 38,478 -> 38,483; holdout fit set 39,076 -> 39,081 (+5 each time). Test rows are identical in all 35 folds (per-fold `test_rows_sha256` equal); holdout test rows 6,118 with sha256 `6b84f05db3da0f6c0736a9db06bb6097461935c1a9367605b36254dac6261f3d` in both versions. Purge counts per fold are identical v2 vs v3.
- **SX10:** in the TRAINING set of every development fold (indexes 0 to 33) and of the holdout fit set (35 of 35); in the test set of 0 folds. Training rows v2 -> v3: fold 0 8,720 -> 8,725; fold 33 38,243 -> 38,248; holdout fit set 38,841 -> 38,846 (+5 each time). Test rows are identical in all 35 folds (per-fold `test_rows_sha256` equal); holdout test rows 6,118 with sha256 `6b84f05db3da0f6c0736a9db06bb6097461935c1a9367605b36254dac6261f3d` in both versions. Purge counts per fold are identical v2 vs v3.

Per-fold detail for both horizons: `final_verification_v3_folds.csv`.

### (v) Leakage: purge recount

Independent recount (the label end date taken from the candle position of each decision bar plus the horizon, not from the stored label end column): the number of rows with decision day before the test start and label end on or after it equals the harness's purge count in all 35 folds, both horizons (SX5 230-235 per fold, SX10 458-470). The embargo removes 0 further rows. The harness's training set equals `decision < test start AND label end < test start AND decision not in the last h sessions` exactly, and no training row's label window reaches its test window.

## 1b. Final hashes

Complete 64-hex values: `final_hashes_v3.json` (repeated in the two approval packages). Against the earlier prefixes: SX5 config `fb5648bb` MATCH, SX10 config `3c1507a9` MATCH, SX5 row list `fdf0b566` MATCH, SX10 row list `d10ef048` MATCH, A_53 manifest `f5a8d398` MATCH, R_37 manifest `0615e2fb` MATCH. **No mismatch.** The C_56 manifest (`1a691d7d...`) is new.

Two hashes exist for a column list and both are recorded. `manifest_sha256` is sha256 of `json.dumps(list(columns))` (the form behind `f5a8d398` and `0615e2fb`). `feature_list_sha256` is the harness's canonical form (sorted-key compact JSON), the value stored in records and bound in the registry. They are different numbers for the same list, so a signed text must name which one it means.

The config uses `excluded_rows_h5_v2.csv` (SX5) and `excluded_rows_h10_v2.csv` (SX10): 187 HINDUNILVR rows each (SX5 182 feature-window and 5 label-window rows; SX10 177 and 10). There are no v3 exclusion files, because the C_56 change did not alter exclusions. `events_input_v2.csv` (419 events) is the input of the exclusion report; its sha256 is recorded. The `DatasetSpec` hash covers the exclusion KEYS, not the file.

## 1c. Registry bypass demonstration (synthetic data, scratch registry copies)

Synthetic matrix (the unit-test generator), a stub least-squares fit, scratch directories and scratch lock/guard files. The real registry file was only read.

**Real registry** `docs/brain/evidence/sector_prep/HOLDOUT-REGISTRY.jsonl`: 0 bytes (sha256 `e3b0c44298fc1c14...` = empty content), no events. A holdout run against it was refused: `no owner authorisation exists for the horizon-5 holdout`. The SX10 check was refused: `no owner authorisation exists for the horizon-10 holdout`. The file was byte-identical afterwards (True).

**After a completed holdout in a scratch registry** (state COMPLETED), each attempt to run again:

| Attempt | Outcome |
|---|---|
| different out_root | REFUSED: `HoldoutRefused` the horizon-5 holdout is CONSUMED (event demo5 is COMPLETED); it needs a new owner-signed authorisation that supers |
| different marker_dir (fresh) | REFUSED: `HoldoutRefused` the horizon-5 holdout is CONSUMED (event demo5 is COMPLETED); it needs a new owner-signed authorisation that supers |
| different run name / output folder (same everything else) | REFUSED: `HoldoutRefused` the horizon-5 holdout is CONSUMED (event demo5 is COMPLETED); it needs a new owner-signed authorisation that supers |
| different seed (43) | REFUSED: `HarnessRefused` seed must be 42 on a real run, got 43 |
| byte-identical protocol copy at another path | REFUSED: `HoldoutRefused` the horizon-5 holdout is CONSUMED (event demo5 is COMPLETED); it needs a new owner-signed authorisation that supers |
| edited protocol copy | REFUSED: `HoldoutRefused` the horizon-5 holdout is CONSUMED (event demo5 is COMPLETED); it needs a new owner-signed authorisation that supers |
| different code_version string | REFUSED: `HoldoutRefused` the horizon-5 holdout is CONSUMED (event demo5 is COMPLETED); it needs a new owner-signed authorisation that supers |
| fresh empty registry path (and fresh lock/guard) | REFUSED: `HoldoutRefused` no owner authorisation exists for the horizon-5 holdout |
| registry file deleted after use (local guard remembers the chain head) | REFUSED: `HoldoutRefused` registry failed verification: the registry no longer contains the entries this machine last saw (truncated or rewri |

Notes: the harness has no 'run name' argument, so the output folder (the nearest thing) was changed. A different seed is stopped earlier by the harness's own rule (the seed must be 42). The registry check comes before the protocol or code mismatch check, so an edited protocol copy is stopped as CONSUMED.

**Exception after STARTED.** The registry already read `{'demo5': 'STARTED'}` inside the first holdout fit (STARTED is written before any holdout fit). After the exception the state is STARTED. A retry with fresh directories is refused (CONSUMED). An ABORTED note changes nothing (still CONSUMED). Final state {'demo5': 'ABORTED'}.

**Hard kill.** A subprocess ran the holdout; as soon as it reached the first holdout fit it was killed (process terminated, return code 1). State after the kill: `{'demo5': 'STARTED'}`. A retry with fresh output and marker directories: refused (CONSUMED). Recovery needs the signed recovery authorisation: one without 'no predictions or metrics observed' is refused; one for an unknown event is refused; after a valid one the state is `{'demo5': 'RECOVERY_AUTHORISED'}`. A run with a different code version is still refused (hash mismatch). A run in the OLD output folder is stopped by the old per-run marker (`HoldoutAlreadyUsed`, a second guard that the recovery procedure must account for). The run with identical hashes and a fresh marker directory then completed (state `{'demo5': 'COMPLETED'}`), and exactly one further run was consumed (the next attempt is refused). `verify()` passes at the end.

**Tests:** `backend/tests/test_holdout_registry.py` 36 passed and `backend/tests/test_sx_recipe.py` 12 passed (48 passed, 0 failed together, 28 s).

## 1d. Limitations documented

Both protocol drafts already carried a one-line survivor-bias caveat but not the precise text. Each now has an 'Update 2' block with (L1) the breadth survivorship text, (L2) the input-gap selection text, (L3) the `obv_slope` old and current formulas, their effect on R_37, the 400-bar versus full-history difference, and a note that the older C_57, 45,930 and 45,695 text is superseded. `docs/brain/SECTOR-FEATURES-SPEC.md` has a new subsection 'R_37 and obv_slope'. Nothing is committed.

## Observations that need a decision (not failures)

1. After a recovery authorisation, the per-run marker file of the crashed run (read-only, in its output folder) still blocks a run in that folder. The registry is the real gate; the recovery procedure must say that the owner uses a fresh marker directory (or removes the marker).
2. Two different hashes exist for a column list (`manifest_sha256` and `feature_list_sha256`); the signed text and the approval file must name the one meant.
3. The registry binds the dataset hash `sr.matrix_sha256` (feature and label VALUES), not only the row list; the signed text should list both.
