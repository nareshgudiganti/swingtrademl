# SX5 / SX10 blockers summary (2026-11-07)

**Status: for owner decision. Nothing is signed, nothing is trained, no authorisation exists.** Companion to `2026-11-07-sx5-approval-package.md` and `2026-11-07-sx10-approval-package.md`. Training stays unauthorised: none before 2026-12-04, and none afterwards without a separate explicit approval.

## In plain English

The data, the checks and the code are ready and verified. Before anything is trained, you need to settle the choices below. Part A lists the choices that block signing: each has a recommended default and what happens with each answer. Part B lists weaknesses that do not block signing but must be read, because they limit what any result can mean. All hashes quoted are complete in `docs/brain/evidence/sector_prep/final_hashes_v3.json`.

## Verified facts the decisions rest on

- Populations: SX5 45,935 rows, SX10 45,700 rows. Row-list hashes `fdf0b5665613a501f059d6f6de421463673156efcc1b5a9e7a35fe18e1d19f04` and `d10ef048f52a7bfe377472ff51814f8f3710998a5847f3159e7ae66fe359b444`. Config hashes `fb5648bbf66a2c00ae0c24cd019d1c6079ff1c3fe2cb203e9bb2ed164d382371` and `3c1507a9324b93417f3f9000e431778da944eb817a7631070112a96455842be5`.
- Recipe hash `fa6b3e974f62a20a8363e3ceef34105b728bcf1b3a0fe502e2aa05d00e501233` (lightgbm 4.7.0, scikit-learn 1.9.1, numpy 2.5.4, pandas 3.1.0, scipy 1.18.1).
- The five restored APOLLOHOSP rows are valid, point-in-time, matured, training-only: no fold's test set and not the holdout set changed (final_verification_v3.md). Independent purge recount: 0 mismatches.
- The holdout registry file is empty; a real holdout run is refused; interrupted runs leave the holdout consumed (demonstrated on synthetic data). Tests: test_holdout_registry.py 36 passed, test_sx_recipe.py 12 passed.

## Part A: BLOCKING protocol decisions

| # | Decision | Recommended default | Consequence of each choice |
|---|---|---|---|
| B1 | Adopt the statistical procedure S-1 to S-9 (daily unit, paired series, block bootstrap with block 2 x horizon, Holm over the two primaries, no peeking) | Adopt as written. | Adopt: false-pass rate about 7% instead of 15-20% in the synthetic test, at some cost in power (small-edge power 0.76 vs 0.88 at 5-day, 0.69 vs 0.87 at 10-day). Reject: the drafts' block = horizon and no multiplicity rule stay, intervals are too narrow, and a lucky pass is more likely. |
| B2 | Burn-in rule: R1 and R2 use folds 4-33 only (folds 0-3 reported but not counted) | Accept (30 folds counted). | Accept: folds trained on under a year do not count. Reject: all 34 folds count and four weak early folds add noise to the 60% rule. Must be decided before any result exists; deciding later would be a choice made with outcomes in view. |
| B3 | Replace the 'Final holdout' wording with the exact text in findings section 3 (decision days 2026-02-01 to 2026-08-14; labels of the last decision days use bars up to 2026-08-21 / 2026-08-28; prices not untouched in the ledger) | Adopt. | Adopt: the text states the truth about label maturity and price exposure. Reject: the old wording hides that late holdout labels use bars after 2026-08-15. |
| B4 | Fit window: SX folds fit on 100% of the purged training rows (production-style models fit on 80%) (recipe item O3) | 100%. | 100%: more training data per fold, differs from production's 80% cut, which exists only to produce a held-back metric. 80%: symmetry with production, fewer rows, and it is a new recipe (new hash) that must be fixed before signing. |
| B5 | Keep `subsample` inert (`subsample_freq` 0 exactly as production) (O2) | Keep inert. | Keep: comparable with production-style models, nothing silently 'fixed'. Activate (`subsample_freq=1`): a different recipe and hash, decided before signing, never after any result. |
| B6 | `n_jobs=1` instead of production's -1 (O4) | Accept. | Accept: run-to-run determinism on one machine. Reject: faster, possibly non-reproducible. |
| B7 | Run environment and recipe-hash pinning (O5): which machine and library versions run the real fit; the recipe hash is recomputed there | The current project environment (Python 3.12.6, versions in the recipe hash); the signed text names the recipe hash, `build_fit_fn` refuses a version mismatch. | Pin: reproducible. A different machine or version set gives a different hash, so the signed text and the registry authorisation must be redone for it. |
| B8 | Primary comparison: C_56 minus A_53 on daily top-5 excess over every eligible stock (S-4) | As proposed. | Alternatives (IC, hit rate, after-cost result) as primary would change what 'pass' means and must be chosen now. Economics stay diagnostic. |
| B9 | The `fit_fn` signature and its binding: `fit_fn(X, y, meta, *, seed) -> predict`, carrying `recipe_sha256`, built only through the approval gate | Approve as built (code reviewed at a named commit). | Approve: the registry binds the recipe hash per arm. Change: any code change is a new commit, a new code version string and a new authorisation. |
| B10 | Approval file: names the candidate and the COMPLETE config_sha256 (not a prefix); and which column-list hash the signed text names (`manifest_sha256` as quoted in the evidence, or `feature_list_sha256` as bound by the harness and registry) | Complete 64-hex config hash; the signed text lists BOTH column-list hashes and states that `feature_list_sha256` is the bound one. | Naming only a prefix or the wrong column-list hash makes the approval or the registry authorisation fail to match, or worse, mean something different from what was reviewed. |
| B11 | Commit of the registry and code before any real run: the empty `HOLDOUT-REGISTRY.jsonl`, harness, recipe, registry code and the protocol drafts are committed at a named commit; the `code_version` string is that full commit hash | Commit first; use the full hash. | Commit first: the holdout authorisation can bind an exact code version. Not committing: the version string is a moving target, defeating the binding. |
| B12 | Who signs | The owner personally: protocol sign-off, approval file, (later) holdout authorisation and any recovery authorisation. No session, subagent or automated process signs. | The registry records a name and a hash of the authorisation text, not a cryptographic signature; the discipline is procedural. |
| B13 | Recovery procedure after an interrupted holdout run | Written into the signed text: recovery only by a signed RECOVERY_AUTHORISATION; the recovery run uses a fresh marker directory (the old read-only per-run marker still blocks the old folder). | Without this, a legitimately authorised recovery stalls on the per-run marker, tempting someone to delete files by hand. |
| B14 | Pass rules R0 to R5 and outcome words, including which rows are NEW; and economics as DIAGNOSTIC only (SX5 h05 shadow trade, SX10 `score_trade`) | Adopt R0-R5 as proposed with the S-1 to S-9 revision; economics diagnostic only, not a promotion criterion. | Making economics a pass criterion would bind the result to the unaccepted h05 draft (SX5) and to a trade rule that differs from the label. |
| B15 | HINDUNILVR: keep its windows excluded until the fresh fetch is done (A8) | Keep excluded; reissue all hashes if the fetch changes anything. | Keep: the hashes in this package stand. Wait for the fetch: if re-included, row lists and every hash change and both packages are reissued. |
| B16 | SX10 versus td-protocol-v2 B1: independent protocols, no shared promotion evidence unless equivalence is demonstrated and approved; whether B1 is re-scoped or retired | Independent; decide B1's fate separately. | Independent: no double counting by accident. Merging evidence needs a written equivalence argument and your approval. |
| B17 | Experiment-register row (exposure ledger) written before training, with row-list, config and fold hashes | Write it at signing. | Without it the number of looks at the same prices is not on record. |
| B18 | S-9: compute the minimum detectable edge on a synthetic series with the measured dependence before approval | Compute and read it before signing (not yet done). | Without it the owner approves without knowing how small an edge could ever be seen (expected: INCONCLUSIVE for realistic edges). |
| B19 | Training date: no training before 2026-12-04; afterwards only with a separate explicit approval | As stated; signing the packages does not authorise training. | Keeps the dev freeze and prevents signing being read as a go. |

## Part B: NON-BLOCKING research limitations and investigate-later items

| # | Item | What it limits | Later action |
|---|---|---|---|
| L1 | Breadth survivorship: breadth inputs use today's 49 watchlist stocks for all past dates | Comparisons with R_37 are confounded (R_37 has no breadth); C_56 minus A_53 unaffected | Point-in-time membership would be needed; not available locally |
| L2 | Input-gap rows (1,103) are one 5-week rally window plus 22 MFI rows, removed for all arms | One specific window is absent from every arm; no concentration by sector | Document only |
| L3 | R_37 is a 37-feature research reference, not a production replay; `obv_slope` formula changed 2026-10-05; production serves 400 bars | No R_37 result is model-2 performance | Exact comparison only as a separate read-only audit from a trusted source in an isolated environment; production joblib not loaded; implementation not changed |
| L4 | Training windows are 81-94% bullish; folds 0-18 never saw a -10% NIFTY drawdown | Results say little about falling markets | Market-type split is descriptive; forward test needed |
| L5 | Effective sample size about 246 (5-day) and 95 (10-day) independent days | INCONCLUSIVE is the expected outcome; 10-day especially | S-9 computation; do not read a null as proof of no effect |
| L6 | HINDUNILVR fresh fetch pending (windows excluded) | 187 rows absent; HUL missing from test days late in the period | Do the fetch and compare adjusted prices; reissue hashes if re-included |
| L7 | Ledger exposure: holdout-period prices were used in earlier diagnostics | Holdout is untouched only for SX models and labels, not for prices | Record in the exposure ledger; a forward shadow test is the real confirmation |
| L8 | Survivor-biased 47 stocks; ASIANPAINT and BHARTIARTL not covered; static sector labels; thin sector groups | Generalisation beyond today's large caps | Map the two stocks once an official index is verified |
| L9 | LightGBM results may differ across platforms and builds | A different machine may not reproduce scores bit-for-bit | Pinned environment; recipe hash includes versions |
| L10 | Registry tamper evidence is procedural (hash chain plus a local guard) | A determined owner could rewrite git history and the guard | Accept as designed, or add an external timestamp later |
| L11 | About 43-46% chance of at least one lucky pass across the 11-12 programme comparisons | A PASS can only justify a forward shadow test | Keep the register honest; never call a pass proof |
| L12 | The two SX horizons overlap with other work (SX5 with h05 draft economics; SX10 with td-v2 B1 inputs) | Double counting if evidence is shared | Keep protocols independent (B16) |
| L13 | Daily bars cannot order target and stop inside a day; no liquidity modelling | Economic diagnostics are optimistic or approximate | Diagnostics only |

## What stays unchanged

The h05 trial and lane, the sealed 15-day trial, active models 2, 16, 17, the signed protocols (`wf-protocol-v1`, `fd-protocol-v1`, `td-protocol-v1`), `ml/features.py`, `ml/predict.py` and everything fingerprinted in `backend/tests/trial_freeze.json`, and the 129 held-back stocks. Nothing here touches production, orders, Kite or the database beyond SELECT.

Owner decision recorded: ______________________  Date: ____________
