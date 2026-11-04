# SX5 / SX10 verdict code: specification of `ml/sx_verdict.py`, 2026-11-08

Status: **PROPOSED code and text. Not signed. Not committed.** Built to close audit item M1 (`2026-11-08-sx-survivorship-and-rule-audit.md`, Part B). Tested on synthetic records only (30 tests). No real arm, holdout, model, database, prod, Kite or `.env` was touched.

## Plain-English summary

The module reads only the saved per-arm, per-fold result files of the walk-forward harness, plus one signed parameter set, and prints one outcome: PASS, FAIL or INCONCLUSIVE, with every number behind it. There is no choice left after the results exist: block length, number of draws, seed, which folds count, the Holm level and the "minimum detectable edge" are all in the parameter set, which has a fingerprint (sha256). The code has its own fingerprint too. The signed text names both. PASS never means a model works; it only proposes a separately signed forward shadow test. INCONCLUSIVE is reachable in two ways (too little data, or an interval that cannot tell "no edge" from "a useful edge"). The holdout files are never opened until the registry says the holdout run is COMPLETED, and then only if the answer depends on them.

## Inputs and the quantity (S-1)

Records: dicts as written by `sector_walkforward.run_walkforward`: `arm`, `fold{index,kind}`, `status`, `daily[]` with `date`, `n_stocks`, `top_symbols`, `excess_vs_all`.

Daily value x_t = `excess_vs_all` = mean `forward_return` of the 5 highest-score stocks minus the mean `forward_return` of all eligible stocks that day (`_day_metrics`). **VERIFIED in code: `forward_return` is the raw h-session close-to-close return for both horizons.** For SX5 the endpoint label (`target` = return >= +2%) is used only for training and for `top_hit`; for SX10 the barrier label is training only. So the verdict quantity is the literal harness quantity for both horizons. (The SX10 draft text "10-day trade result" is wrong for this quantity: owner/text decision, see open questions.) D_t = x_t(C_56) minus x_t(A_53) on the same day. Function: `_paired_days`.

## Rules, numbers and code names

| Rule | Number | Code |
|---|---|---|
| Parameters, hash | frozen dataclass; canonical JSON (sorted keys, includes code version); sha256 | `VerdictParams`, `.canonical_json()`, `.sha256()` |
| Code hash | sha256 of module bytes, CR/CRLF normalised to LF | `verdict_code_sha256()` |
| MDE_H | REQUIRED positive number, no default; `VerdictRefused` otherwise | `VerdictParams.__post_init__` |
| Fold numbering | 0-based. Default counted 4..33 (30 folds); `burn_in_folds=0` counts all 34 | `counted_folds` |
| Days | days with `n_stocks` < 10 left out; dates must be unique across folds; ordered by date; blocks run over this retained list | `_paired_days`, `_fold_table` |
| R0 | both arms must have the same days and `n_stocks` per day, same status per fold; else VOID (exception, no result) | `_paired_days` |
| Eligible fold (S-6) | status ok, >= 10 retained days, >= 20 picks (picks = `len(top_symbols)` per retained day, i.e. 5 per day, before any no-repeat rule) | `_fold_table` |
| Bootstrap (S-3) | non-circular blocks of 2h (10 or 20), ceil(n/b) blocks per draw, `random.Random(7).randrange(n-b+1)`, 2,000 draws, one generator; mean of picked values; same as `walk_forward.bootstrap_low` (a test asserts equal output); not computable if n < max(5, 2b) | `block_bootstrap_means` |
| Lower bound | sorted means, 0-based index floor(alpha x 2000): alpha 0.05 -> 100, 0.025 -> 50 | `lower_bound` |
| Upper bound (5%) | index 2000 - 100 - 1 = 1899 | `upper_bound` |
| p-value (S-5) | (1 + #resampled means <= 0) / 2001 | `p_value` |
| Holm | `single_horizon`: 2.5% (PROPOSED, conservative). `two_horizon`: needs the other horizon's p; smaller p gets 2.5%, the other 5%; tie -> SX5 gets 2.5% | `compute_verdict` -> `out["holm"]` |
| R3 data | eligible counted folds >= 12, picks over eligible folds >= 100, pooled days >= 2h, every counted fold status ok | `out["r3"]` |
| R2 | lower bound at the Holm alpha, strictly > 0 | `out["r2"]` |
| R1 | folds with mean D_t strictly > 0 >= ceil(0.6 x eligible); exactly 0 is not a win; no eligible folds -> not met | `out["r1"]` |
| R4 | holdout mean D_t > 0 AND dev mean D_t > 0 (strict); all holdout folds status ok; holdout interval reported, no weight | `_r4` |
| R5 | per-fold mean D_t, min and max; flagged `no_weight` | `out["r5_descriptive"]` |
| Sensitivity | block h, 3h and 1 (day-iid), same code and seed; labelled `sensitivity_NO_WEIGHT` | `out["sensitivity_NO_WEIGHT"]` |

## Order of evaluation (fixed)

0. Parameters valid, MDE_H present (else refuse). 1. Inputs: record completeness, R0, duplicates (else VOID/refuse). 2. Data sufficiency (R3). 3. Pooled paired series, bootstrap, Holm alpha, R2. 4. R1. 5. Outcome:

1. **INCONCLUSIVE (data)** if any R3 reason.
2. else if R2 and R1 both met: needs R4. If the holdout is not COMPLETED: outcome word `PENDING_HOLDOUT` (not a protocol word; dev signals met, R4 unread). If COMPLETED: **PASS** if R4 met, else **INCONCLUSIVE** (signals disagree).
3. else if R2 not met and the 5% upper bound < MDE_H: **FAIL**.
4. else if R2 not met: **INCONCLUSIVE** (upper bound >= MDE_H).
5. else (R2 met, R1 not met): **INCONCLUSIVE**.

## Holdout discipline and call order

The module has no import of the registry. `compute_verdict(dev_records, params, holdout_records=<list or loader>, holdout_completed=<bool or callable>)`. Call order: (1) dev-only call, which returns FAIL, INCONCLUSIVE or PENDING_HOLDOUT without ever touching holdout input; (2) after the registry shows COMPLETED for the run, repeat the call with `holdout_completed=True` and the holdout records. The loader is invoked only if completed AND the outcome depends on R4 (so for FAIL / data-INCONCLUSIVE the holdout is never opened). Tests use a loader that raises to prove it. Dev input containing `holdout` kind records is refused.

## Output

`compute_verdict` returns a dict with all intermediates and a `record_sha256` over its canonical JSON. `render_json(verdict)` adds `verdict_code_sha256`; `render_plain_english(verdict)` writes the paragraph (never says a model "works"). Same input in any file order gives identical text (tested). Write-once of the output file is NOT in this module (see open questions).

## PROPOSED markers: what the signed text must still decide

1. **Single-horizon Holm uses the 2.5% bound** (audit B3 S-5; conservative). PROPOSED.
2. **Strict > 0** for R1 wins and R4 on both dev and holdout. PROPOSED (audit wording).
3. **R4 = holdout mean > 0 and dev mean > 0, no bound required.** The packages say only "same sign (reported; not a second chance)". PROPOSED reading, from audit S-8/R4 replacement.
4. **PENDING_HOLDOUT** as an interim word. PROPOSED.
5. **FAIL needs R2 not met and upper bound < MDE_H**, with the upper bound at 5% (index 1899). `fail_upper_alpha` is a parameter. PROPOSED.
6. **Index convention** m(floor(alpha x draws)+1) (audit S-3), identical to `bootstrap_low`.
7. Pooled T uses all days of counted ok folds (not only eligible folds); R1 and R3 use eligible folds only. In practice identical when every fold has >= 10 days.
8. Missing counted-fold records, duplicate records, R0 breaks, non-finite values: refuse (void), never a guessed outcome.

## Open questions and ambiguities needing an owner decision

1. **SX10 quantity.** The harness records the raw 10-session `forward_return`, not the +6%/-3.5% barrier trade result. The verdict follows the harness; the SX10 draft text must say so (audit S-1).
2. **SX5**: unambiguous in the records (raw 5-session return). The draft's mention of the endpoint label concerns training only.
3. **Picks.** `n_ideas` = 5 x days before no-repeat; the "20 picks" test then never binds beyond 4 days. Kept as the audit proposes; owner may prefer a different count.
4. **Two-horizon Holm timing.** If SX5 is read before SX10 exists, `single_horizon` (2.5%) must be used and not revised; the signed text must say which mode each run uses.
5. **S-9 / MDE_H** is not computed; the verdict refuses until a number is signed.
6. **Write-once verdict file and run id**: the caller must create the output with exclusive-create and name one run id; not implemented here (module is pure).
7. Holdout day count (133) is not enforced by the code; it uses whatever holdout-kind records are given (days with >= 10 stocks). The caller / registry should verify the count.
8. Zero eligible-or-ok holdout days -> R4 not met (INCONCLUSIVE), a case the text does not yet mention.
9. Test note: importing `brain.walk_forward` first triggers a repo-wide circular import; the test imports `brain.service` first. Not changed (no existing files edited).
