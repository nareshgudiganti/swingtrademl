# Catalogue: 5D research models, the failed 10D model and the 15D candidates (#267, part 2)

Audit date: 2026-11-24 (IST). Read-only catalogue. Nothing was trained, scored, activated or written to the database; no prod access; `.env` not read.
Companion to `2026-11-24-as-built-models-2-16-17.md` (models 2/16/17, not repeated here).
Issues: #267 (inventory), #223 (10D large cap), #224 (15D large cap), #225 (15D mid cap), all OPEN.
Baseline: branch `docs/218-model-audit-r0` (PR #492), `origin/main` at `5de3b9c`.

## How the evidence was gathered

* The saved files are gitignored (`backend/data/` is in `.gitignore`), so they exist only inside local worktree folders. They were opened read only
  with the repo venv Python (`joblib.load`), hashed with sha256, and their embedded settings listed. Scratch scripts and output stayed in the session
  scratchpad, not the repo.
* Registry rows come from a `SELECT` on local dev DB `swing_trade_ml` (table `ml_models`, container `stml-postgres`). `model_research_slots` has 0 rows.
* Result numbers come from evidence files committed in this repo (paths below) and from the signed protocol documents. Nothing was re-evaluated.
* Per-file sha256 values are in the appendix; the main table is per family.

## Main table (artifacts that exist)

All three families share one bundle layout: a joblib dict with 9 keys (`estimator`, `scaler`, `feature_names`, `algorithm`, `horizon_days`,
`target_return`, `stop_return`, `label_kind`, `calibrated`). Verified across every file: the same 53 input names in the same order (one list hash for all
62 files; the same count as today's `FEATURE_COLUMNS`), LightGBM `LGBMClassifier`, 400 trees, learning rate 0.05, 31 leaves, max depth 6, min child
samples 50, subsample 0.8, colsample 0.8, `class_weight` balanced, random state 42, `StandardScaler`, not calibrated.

| Item | `fd_h5_*` (5D, v1) | `td_h10_*` (10D, v1) | `wf_h15_*` (15D, v2) |
|---|---|---|---|
| Files | 21, under `swing-trade-bot/.claude/worktrees/fd-tag/backend/data/models/` | 21, under `td-run-wt/backend/data/models/` | **20**, under `swing-trade-bot/backend/data/models/` (the earlier note said 18) |
| Fold cut-off dates (file names) | 2023-06-30 to 2025-01-10, every 28 days | 2023-06-30 to 2025-01-10, every 28 days | 2025-01-31 to 2026-07-17, every 28 days |
| Algorithm | LightGBM, uncalibrated | same | same |
| Inputs | 53 (saved in file; equals registry) | 53 | 53 |
| Label | `endpoint`: close 5 trading days later at least +2%; no stop (`stop_return` None) | `barrier`: +6% before -3.5% within 10 trading days | `barrier`: +8% before -4% within 15 trading days |
| Universe | 49 watchlisted stocks (today's list: survivor bias); registry `training_symbols` 49 | same 49 (symbol-list sha256 `18d79fc8...c5fb` in the td manifest) | 49 in registry; same survivor-bias caveat |
| Data window | rows from 2022-09-15 IST (registry `train_start`); train end per fold 2023-04-19 to 2024-07-10 | train end per fold 2023-04-04 to 2024-06-27 | train end per fold 2024-07-02 to 2025-10-05 |
| Split | per fold, chronological with embargo = horizon (`brain/five_day_train.py:62`; read, not re-run) | `brain/ten_day.py` `_train`; embargo not separately checked | `brain/walk_forward.py` trainer; embargo for these exact files: unknown |
| Train rows (registry) | 9,352 to 28,012 | 9,107 to 27,767 | 28,257 and up (to 47,410 across the 2025-2026 v2 rows) |
| Registry rows | `fd_h5_<cutoff>` v1, all `TRAINED`, never activated; artifact path (fd-tag worktree) exists | `td_h10_<cutoff>` v1, all `TRAINED`, never activated; path exists | 150 `wf_h15_*` rows over versions v1 to v5; the 20 files match v2 rows (`TRAINED`, never activated). **130 registry paths point to files that no longer exist** |
| Held-out AUC (registry, per fold) | 0.480 to 0.615, mean 0.529 | 0.482 to 0.611, mean 0.535 | 0.452 to 0.590, mean 0.539 |
| Trained at (UTC) | 2026-10-26 10:17 to 10:22 | 2026-11-02 12:16 to 12:22 | v2 rows 2026-10-26 12:08 to 12:12 (v1 rows of the same names: 2026-10-12) |
| Code that built it | `brain/five_day_train.py`, commit `271eb1c` (tag `fd-protocol-v1`; manifest says "uncommitted changes present") | `brain/ten_day.py`, commit `45880ac1` (annotated tag `td-protocol-v1`, 2026-11-02 17:45 IST; the manifest records the same commit) | `brain/walk_forward.py` (`wf-protocol-v1` at `7b97291`, 2026-10-12). Commit for the 2026-10-26 v2 retrain: **unknown** |
| Evidence | `docs/brain/evidence/fd_v1/` (`five_day_2023-07-01_2025-01-31.md/.json`, `RUN-NOTES.md`): predictive 10 of 21 folds, economic 3 of 17, both FAIL; best 5 average -0.37% a trade over 1,980 trades | `docs/brain/evidence/td_v1/ten_day_2023-07-01_2025-01-31.md/.json`: picks beat every stock in 8 of 21 folds, average -0.34% a trade over 1,980 ideas, both FAIL | `docs/brain/evidence/wf_v1/walk_forward_2023-07-01_2025-01-31.md/.json` (7 of 21 folds, FAIL; those folds' files are gone). On development data 2025-02-01 to 2026-08-15: `docs/brain/evidence/ranking_diag/` (descriptive, not pass/fail) |
| Status | Research, **FAILED** (owner decision 2026-10-26 in `docs/brain/EXPOSURE-LEDGER.md`; the 21 models stay inactive; no 5D shadow lane) | Research, **FAILED and deferred** (`docs/architecture/CURRENT-STATE.md` line 66: no v2, no retrain, no 10D slot) | Research files; the protocol run FAILED. The 20 files are later development-data retrains, never activated |
| Governing documents | `docs/superpowers/specs/2026-10-24-five-day-protocol.md`, `2026-10-26-fd-protocol-v1-prerun-checklist.md` | `docs/superpowers/specs/2026-10-26-td-protocol-v1-PROPOSAL.md`; issue #223 | `docs/superpowers/specs/2026-10-12-walk-forward-protocol.md`; issues #224 and #225 |

10D scope note: the failed 10D model is the large-group history gate on the 49 stocks. #223 asks for sector-only inputs to be verified and protocol approval
before training. No sector-only 10D candidate exists as an artifact or registry row, and the td files use the full 53 inputs.

## The six planned 15D lab candidates (`sl-protocol-v1.1`)

**None is built.** No file named `sl_*` exists in any worktree, the registry has no `sl_*` rows, and `docs/brain/evidence/sl_v1/` holds only the signed
Amendment 2 marker, a gap classification and a mid-cap universe snapshot. The runner refuses to start before 2026-12-05 IST.

| ID | Role | Group and universe | Label (design doc section 4, Amendment 3) | Compared with |
|---|---|---|---|---|
| S0 | control | large, trained on the 49 | raw 15-day barrier +8% before -4% within 15 trading days, LightGBM, retrained per fold, uncalibrated | none |
| S1 | experiment A (target) | large, 49 | "beats the 49": excess return over the group median, top 30% per day = 1 | S0 |
| S2 | experiment B (wider training) | large; trained on 177 (49 plus 128 extra), scored on the 49 | same "beats the 49" label | S1 |
| S0M | control | mid group, 14 stocks (limited sample) | raw 15-day barrier | none |
| S1M | experiment A | mid, 14 | "beats" label, mid reference group | S0M |
| S2M | experiment B | mid, 14 | "beats" label, wider training | S1M |

Statistical family S1, S2, S1M, S2M (5% divided by 4). S2r (fewer inputs) and S3 (company inputs) are not built; S3 is blocked by the owner.
Governing documents: `docs/superpowers/specs/2026-10-29-selection-model-experiments-design.md` (rev 3.1), Amendment 2 (signed 2026-11-02), Amendment 3
`2026-11-04-evidence-plan-amendment-3.md` (`CURRENT-STATE.md` line 63: **unsigned**; needs D1 to D10 and tag `sl-protocol-v1.1`). Code: `brain/selection_lab.py`,
`selection_lab_run.py`, `selection_lab_start.py`. Local tags: only `sl-protocol-v1` (no v1.1). Issues #224 (large) and #225 (mid).
The mid snapshot (`sl_v1/mid_universe_snapshot.json`, 2026-11-03) freezes model id 16 (`swing_classifier_midcap` v2, sha256 `633259b0...a20`, equal to the
hash in the as-built record) and a 14-stock mid group taken from that model's 24 training symbols. The 177-stock list is described in the design doc only;
no build artifact exists. The three Phase B candidates (B1 to B3, `docs/brain/PHASE-B-FINISH.md`) are not among the six; no Phase B model file was found.

## Discrepancies

1. **Count:** the earlier note and #267 say 18 `wf_h15` files; there are 20 (cut-offs 2025-01-31 to 2026-07-17). The 21 `fd_h5` count is correct.
2. **The `wf_h15` files on disk are not the files behind the wf-protocol-v1 verdict.** That verdict covers 21 folds with cut-offs 2023-06-30 to 2025-01-10, and no `wf_h15` file exists for those cut-offs.
3. **Evidence predates the files.** `ranking_diag/` (committed 2026-10-12) matches the 20 folds on disk, but the v2 files were trained 2026-10-26, and the v1 rows from 2026-10-12 point to files that are gone. Whether v2 is identical in content to v1 cannot be shown. `pause_check.md` line 113 says the stored `wf_h15` models were reused, so v1 files existed then.
4. **130 `wf_h15` registry paths are dead** (v1, v3, v4, v5 and 35 older v2 rows; many point to a removed worktree, `ps-wave2`).
5. **fd and td registry paths are local worktree paths**; they break if those worktrees are cleaned up.
6. **td ledger row** in `docs/brain/EXPOSURE-LEDGER.md` still reads "Owner's decision: to be written after reading", while `CURRENT-STATE.md` and the evidence both say FAILED. The decision is not recorded where the ledger expects it.
7. **fd manifest says "uncommitted changes present"**; `RUN-NOTES.md` explains it (the tool writes the ledger row first); no code file changed.
8. **#223 wording vs artifacts:** the issue speaks of sector-only inputs; the 10D files use the full 53-input set.

## Gaps and unknowns

* Commit and command for the 2026-10-26 `wf_h15` v2 retrain: not recorded.
* Library versions, dataset snapshot and exact held-out cut-off per file: not stored in the artifacts.
* Evidence for the v2 `wf_h15` files themselves: none; the recorded evidence concerns the v1 files, which are missing.
* The 177-stock training list and the 14-stock mid group exist as docs and one snapshot JSON only.
* Whether the missing v1 files exist in any backup: not searched beyond local worktrees (`docs/brain/evidence/model_artifact_backup.md` not reviewed).
* Registry `hyperparameters` for these rows were not compared; the values above are read from the artifacts.
* Prod state not checked (no prod access).

## #267 exit-condition check

| Condition | Status |
|---|---|
| 5D models 2/16/17 | Done earlier (`2026-11-24-as-built-models-2-16-17.md`) |
| 5D research files `fd_h5` (21) | Done here: sha256 appendix, label, evidence, FAILED |
| Deferred 10D model | Done here: 21 `td_h10` files catalogued, FAILED and deferred; no sector-only candidate exists |
| Six planned 15D candidates | Recorded as planned, not built: no artifacts, rows or evidence; no run before 2026-12-05 IST; Amendment 3 unsigned |
| 15D research files `wf_h15` (20) | Done here, with discrepancies 2 to 4 |
| Unknowns marked | Yes |

Overall: the catalogue covers everything that exists. #267 can close if the owner accepts "planned, not built" as the record for the six 15D candidates.
obv_slope parity stays with #272 and the score trace with #226. This file does not close the issue.

## Appendix: per-file sha256

Registry AUC is on the registry's held-out split for that fold. Train end is the last training row date.

#### fd_h5 (21 files)

| File | Bytes | sha256 | Registry AUC | Train rows | Train end |
|---|---|---|---|---|---|
| fd_h5_20230630_v1.joblib | 1,050,794 | 5041e57ef1f43f604cb7b9ac18ea5c9ab51eebc5a0a9b7a64a2ec2f696c4c02a | 0.572 | 9,352 | 2023-04-19 |
| fd_h5_20230728_v1.joblib | 1,075,690 | 55c51c0066ffaba3d200f817cd840bfbe13c91a8302fe3e9afa7a9054f29057f | 0.544 | 10,332 | 2023-05-14 |
| fd_h5_20230825_v1.joblib | 1,122,554 | 2133918bcf147f6c3586ecf90bf5b23ee61110e714c0e1d0a9c0c97442ddf3f7 | 0.539 | 11,263 | 2023-06-05 |
| fd_h5_20230922_v1.joblib | 1,153,322 | f7bf4fff2cb2faffb8589a407140d82644b68821870090d4d953210ba0b050b7 | 0.615 | 12,194 | 2023-06-26 |
| fd_h5_20231020_v1.joblib | 1,151,690 | 7bd7d7e2b940d1532c98ce08318ea6f73630e0956cb63c2c981ec69955093f45 | 0.545 | 13,125 | 2023-07-18 |
| fd_h5_20231117_v1.joblib | 1,121,274 | 0d917838462c6db2d6076ee6b2c5f1cf5bc2a7d9e00abb09e18e7adcadf77459 | 0.524 | 14,056 | 2023-08-08 |
| fd_h5_20231215_v1.joblib | 1,133,114 | 641f484cf2d1b49580cf9aed9cf09804a1d4e570280ebfd4ddecc3a156b435df | 0.500 | 14,987 | 2023-08-30 |
| fd_h5_20240112_v1.joblib | 1,163,242 | 66eb8f29df9d25580291dcb2dd4c531c11cd418d3a9e92cdbba762fff1bb74ba | 0.513 | 15,918 | 2023-09-24 |
| fd_h5_20240209_v1.joblib | 1,178,394 | b9aee220bcdae1f20613f8b7673835d0b1083e61aef37c5653294c0bfd0a6b5f | 0.498 | 16,849 | 2023-10-16 |
| fd_h5_20240308_v1.joblib | 1,196,810 | cd348d1110bd502dca99c48f918ea52b7e0f427250b7df1a7888a882fe02c04e | 0.506 | 17,829 | 2023-11-08 |
| fd_h5_20240405_v1.joblib | 1,199,450 | f976c91e2e5443a6023d3aeba0922dedc4bb32adbd2afa9d2c79c609711021fc | 0.480 | 18,711 | 2023-11-29 |
| fd_h5_20240503_v1.joblib | 1,188,202 | a7d48f0d3a1bfb8c48ebed3302d26bfb85df98975d38f202395398295a324a6f | 0.493 | 19,544 | 2023-12-19 |
| fd_h5_20240531_v1.joblib | 1,185,306 | 516bd667665987d9ca0e6e94878d14127133904292f8c32839f9b0ba753e837e | 0.525 | 20,524 | 2024-01-11 |
| fd_h5_20240628_v1.joblib | 1,182,826 | 84767a035cb0f1594b8e3b17ff61b26fd4102e8c435a39334e2f6037bf48c9d6 | 0.557 | 21,455 | 2024-02-04 |
| fd_h5_20240726_v1.joblib | 1,196,506 | ce34b523fe6db1482701a745c8ba39c87bc0d977f9e8a278a0d510222db1654b | 0.519 | 22,382 | 2024-02-25 |
| fd_h5_20240823_v1.joblib | 1,199,338 | 7b72946cf4f31f9e0b2d29c02e110548d02d7c26c946474213101932b6139091 | 0.536 | 23,311 | 2024-03-17 |
| fd_h5_20240920_v1.joblib | 1,193,146 | ef7c3a0cf610194c389b033973e575af538b8ab6c96e310ee7a6ed3f89e08372 | 0.545 | 24,288 | 2024-04-11 |
| fd_h5_20241018_v1.joblib | 1,219,018 | f16302a01733f0e38ef3114ad9fdcfc6ecd8c624f3187e9dd5cbdcbaf1683b02 | 0.523 | 25,219 | 2024-05-07 |
| fd_h5_20241115_v1.joblib | 1,205,402 | eb0673fd4dd392dbed2fc845cc66c93a8b1e849f91f08990d80ca7958f6aad41 | 0.513 | 26,150 | 2024-05-28 |
| fd_h5_20241213_v1.joblib | 1,246,938 | 0e93ad2c2ad460845198f6bbabeaf3410c13c620cf08cb03ad9c89b8d5cb142c | 0.533 | 27,081 | 2024-06-19 |
| fd_h5_20250110_v1.joblib | 1,248,922 | 270e4c27933fb30fcb23486877fca1d0b1d62e770eb8b990bfc8ed0b74971b52 | 0.538 | 28,012 | 2024-07-10 |

#### td_h10 (21 files)

| File | Bytes | sha256 | Registry AUC | Train rows | Train end |
|---|---|---|---|---|---|
| td_h10_20230630_v1.joblib | 1,129,889 | 36efc858a1de979a56c77b97cf5bbfad6a020c9d67c039502767d7493194b145 | 0.595 | 9,107 | 2023-04-04 |
| td_h10_20230728_v1.joblib | 1,117,521 | 467137d6f7118db82be8503f3ffb45d63f2c5929c71025468b169b34127f1abf | 0.503 | 10,087 | 2023-05-01 |
| td_h10_20230825_v1.joblib | 1,165,665 | 8ae3c8429a496009675c43667bd48fba61b60ac0e64f40d376c54ba790124b66 | 0.482 | 11,018 | 2023-05-23 |
| td_h10_20230922_v1.joblib | 1,153,105 | d003c3da1423887f2c9704a02783786507ff917ee0c5a0f0b5a35acbcd9dc23d | 0.590 | 11,949 | 2023-06-13 |
| td_h10_20231020_v1.joblib | 1,147,057 | 808f5e9ca26f0a2a795a38473ae8665430c0381c1b0b23c20c71903f57575e0e | 0.611 | 12,880 | 2023-07-05 |
| td_h10_20231117_v1.joblib | 1,168,193 | 270d791acfa0db35c4a44392bc14684fbfdeb28ca24894e7319b04c1f4263b87 | 0.541 | 13,811 | 2023-07-26 |
| td_h10_20231215_v1.joblib | 1,185,041 | e591bcffadb5e73a067f5600129889b2f06a920ff95102593958898ae924f0a3 | 0.494 | 14,742 | 2023-08-17 |
| td_h10_20240112_v1.joblib | 1,199,761 | 829ff578610ae389d7eebb1994553439c9e85319f3c5d2a02636d34baaf18c67 | 0.488 | 15,673 | 2023-09-10 |
| td_h10_20240209_v1.joblib | 1,208,337 | 6ddf3560f1e2a16cb747315ca8b05644cc9d7415e324ec5d0948ce3481b17fc5 | 0.497 | 16,604 | 2023-10-03 |
| td_h10_20240308_v1.joblib | 1,255,665 | b61108219256b636e69917cfea7516dd17ee076013193f24d69d3252e6f48175 | 0.500 | 17,584 | 2023-10-26 |
| td_h10_20240405_v1.joblib | 1,268,289 | 4aabc85adcd3b9f90c006a82a008ca67623058c211bf878903bfd2eaa6db2ad0 | 0.503 | 18,466 | 2023-11-15 |
| td_h10_20240503_v1.joblib | 1,277,041 | 0f7d232dd1502b932949e59e101b5b2d79a3d39e028f496637c6a147ace5c93b | 0.484 | 19,299 | 2023-12-06 |
| td_h10_20240531_v1.joblib | 1,249,777 | 13b96c3ec50dc88955b0bc4b1c7f54a2ac08851aec8dd84f280efa89d00d7e79 | 0.524 | 20,279 | 2023-12-31 |
| td_h10_20240628_v1.joblib | 1,221,409 | bb267e5ad518895bec2607d19d57f1b49924cf7843c1212ce07fecfddfa6ac92 | 0.553 | 21,210 | 2024-01-19 |
| td_h10_20240726_v1.joblib | 1,219,825 | e9e6502b0ddcb546328d2bde96c455296d862bf60534780cd9302a6ffc9f9cfc | 0.537 | 22,141 | 2024-02-12 |
| td_h10_20240823_v1.joblib | 1,210,721 | 965d89bb715ffcc226f821ec5e2ca841f749f7a9d44cf633a26803a32d30558a | 0.549 | 23,066 | 2024-03-03 |
| td_h10_20240920_v1.joblib | 1,239,793 | 9b57222e12e668b2b1da7dcaab584c01cd071c53b3772b870f94d80c85526180 | 0.538 | 24,043 | 2024-03-27 |
| td_h10_20241018_v1.joblib | 1,252,737 | 7e56178b999278474d7fbf04caedc85caa24d3050558f91268e0c22e7802bf9f | 0.572 | 24,974 | 2024-04-23 |
| td_h10_20241115_v1.joblib | 1,251,969 | ec55436329afe5267c830dc0290e2a68993ae6516c10052c8839b058b5bcdd4c | 0.571 | 25,905 | 2024-05-15 |
| td_h10_20241213_v1.joblib | 1,240,337 | f6c1c1b3550c530d94e328a709cc738cf6ef832a4c077e850778c7f465d6b8ae | 0.551 | 26,836 | 2024-06-05 |
| td_h10_20250110_v1.joblib | 1,296,641 | 82cd4e00b3b06dcd3879a6663220eb29f216c84775fab1bf2ee4d9d016128e85 | 0.542 | 27,767 | 2024-06-27 |

#### wf_h15 (20 files)

| File | Bytes | sha256 | Registry AUC | Train rows | Train end |
|---|---|---|---|---|---|
| wf_h15_20250131_v2.joblib | 1,281,857 | ecf4e1b8445f3e9b6784fc77ac1b75ff839444c30b1a316eadbe65a3097898e4 | 0.534 | 28,257 | 2024-07-02 |
| wf_h15_20250228_v2.joblib | 1,294,321 | 8667a4239984ffb7f6b8ee9787aada07368aab6dde66b903137258b68c9d1be8 | 0.528 | 29,237 | 2024-07-25 |
| wf_h15_20250328_v2.joblib | 1,293,617 | 33226182135a81b1969e5e111f78d0c66776e95a4c0df3ecd00e224c69fb8ab9 | 0.548 | 30,168 | 2024-08-18 |
| wf_h15_20250425_v2.joblib | 1,318,769 | 34bbb6ce26c5ed3452a09ea29b1363e91be37231c97500ed167d478be11faed5 | 0.580 | 30,952 | 2024-09-04 |
| wf_h15_20250523_v2.joblib | 1,307,329 | 4a2884bf086b9efd0f19dfe9511b4004f5ea72cd4bbe4f84e7c86f13883968ad | 0.551 | 31,883 | 2024-09-25 |
| wf_h15_20250620_v2.joblib | 1,302,113 | ad28e28b08a6b29960b314ca907988e45206ba676c323e3b04a7e99070194561 | 0.566 | 32,863 | 2024-10-20 |
| wf_h15_20250718_v2.joblib | 1,314,913 | 5de92fdda57a7325b03cbac170e4dabd0b8a608c91071158ce69fdff4fd087b8 | 0.545 | 33,843 | 2024-11-11 |
| wf_h15_20250815_v2.joblib | 1,324,673 | 4d6a55187ce683ad1de45ab33ba8b9aafa24d6069a23824cf858ad756928a099 | 0.590 | 34,774 | 2024-12-05 |
| wf_h15_20250912_v2.joblib | 1,326,977 | fa381bb58ce3ce7c22277d0cc0b45075de869bed1154884b635f062f80de8368 | 0.588 | 35,705 | 2024-12-29 |
| wf_h15_20251010_v2.joblib | 1,334,433 | fbb199618f49545e289f9ebe503f43ed2cc9dce7eb6bc8b21217062283d38fce | 0.589 | 36,634 | 2025-01-19 |
| wf_h15_20251107_v2.joblib | 1,329,073 | 7af8880c4b165dbae5f64af70b970c0540420c9802a1e746c8edd6f2ab44b967 | 0.570 | 37,516 | 2025-02-05 |
| wf_h15_20251205_v2.joblib | 1,330,993 | 5f78b017bdaaf30a97c213b8eca30b078aeb339410b3229d3de808c934746bf8 | 0.533 | 38,496 | 2025-03-02 |
| wf_h15_20260102_v2.joblib | 1,333,793 | 616e0b3523ef3988e62ad2fd9fe30ebfe40f4fb7b9a2a141ca368107cfc56a60 | 0.470 | 39,423 | 2025-03-25 |
| wf_h15_20260130_v2.joblib | 1,335,009 | 1b514f3ddec54be9e1e55e9dc01b63f49e31171c0a850f6ca73c7b8865be2481 | 0.452 | 40,305 | 2025-04-20 |
| wf_h15_20260227_v2.joblib | 1,339,041 | e376b78a8d6ead1b51091a9530d3ce2494f051601f9f54ea2e3d9dff247a1064 | 0.487 | 41,334 | 2025-05-14 |
| wf_h15_20260327_v2.joblib | 1,344,433 | 576f4cc2c3a722ed202aa1efec49654cc59cce7dfd845f868fbe53c90fe2ef44 | 0.461 | 42,216 | 2025-06-03 |
| wf_h15_20260424_v2.joblib | 1,340,305 | 734bf716cc50890f298322cf1b9fab4e4b2a4c2440da9b38f5157840c5b6ac9d | 0.510 | 43,049 | 2025-06-23 |
| wf_h15_20260522_v2.joblib | 1,346,529 | f24564442a4827d4cb4588830e888a4c5fd98b2ff19b079630cd3eb5f7fad2d8 | 0.559 | 43,980 | 2025-07-14 |
| wf_h15_20260619_v2.joblib | 1,341,153 | 54de4e59987fd6b7fb4d6dc784187dac467000134c578a01c5f10615a4a6dd44 | 0.561 | 44,911 | 2025-08-04 |
| wf_h15_20260717_v2.joblib | 1,338,817 | 8b8c2c5055bed61f869b5a6ea34bf663e35c2e6cbc976911f7e94c9962d2afc2 | 0.560 | 45,842 | 2025-08-27 |
