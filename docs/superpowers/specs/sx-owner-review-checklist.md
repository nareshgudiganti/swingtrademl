# SX5 / SX10: owner review checklist (plain English)

Prepared: before signing (date set at signing). Status: **for your decision. Nothing is signed, nothing is trained, no authorisation exists.** Companions: `sx5-research-protocol-FINAL-DRAFT-for-review.md` and `sx10-research-protocol-FINAL-DRAFT-for-review.md`. Rule that never changes: **no training before 2026-12-04, and none after without a separate explicit approval. Signing is not a go.**

**The short story.** The data, checks and code are ready. The test is a screening test: it can reliably see a gain of about 0.16 percentage points per trade (5-day) or 0.24 (10-day), while a realistic gain from three sector inputs is probably 0.02 to 0.13. So a PASS is far from certain even if the inputs help, and the most likely printed word is FAIL (which only means "a gain that big is unlikely"). A PASS would only allow you to propose a no-money forward test.

## (a) Decisions you must make before signing

"NEW" = not in the last summary (blockers B1 to B19). B1 to B14 and B16 to B19 are taken as accepted on their recommended defaults; they are signed as one text and are not repeated here.

| # | Decision | Recommended default | If you choose otherwise | |
|---|---|---|---|---|
| 1 | **MDE_H**: the smallest gain (pp per trade) the test is said to be able to see. The code refuses to run without it. | Central S-9 value: **SX5 0.16, SX10 0.24** (code value 0.0016 / 0.0024) | Smaller: FAIL becomes rarer and stricter (needs the estimate near zero). Larger: FAIL becomes more common and means less. Never changed after a result. | NEW |
| 2 | **E\***: the gain below which you no longer care. | **Your number.** (Starting point from the power note: 0.10 SX5, 0.13 SX10.) The code does not use it; it only words the plain-English reading and the decision to propose a forward test. | Leaving it blank: the reading sentence cannot say "too small to matter". | NEW |
| 3 | **SX10 primary quantity (D-Q10).** Earlier text says "10-day trade result (+6% / -3.5%)"; the code uses the **raw 10-day return**. | (a) Raw 10-day return is primary; the barrier trade result is a labelled diagnostic. | (b) Change the harness to the barrier result: code change, new tests and hashes, new power run. Not started. | NEW |
| 4 | **What FAIL and INCONCLUSIVE mean** (rule: FAIL only if the 5% upper bound is below MDE_H, else INCONCLUSIVE). **Finding:** with MDE_H = central, a quick check shows that at a true gain of 0 to 0.05 pp the usual word is **FAIL (60% to 90%)**, not INCONCLUSIVE as earlier summaries said. | Accept; every FAIL report carries "this does not show the inputs do nothing". | Want INCONCLUSIVE to be the usual word: sign a smaller MDE_H, or change the outcome rule (a code change). | NEW |
| 5 | **One-horizon Holm timing.** SX5 and SX10 may be read at different times. | Each is read alone at the strict **2.5%** bound; the 5% relaxation is never used. | Joint reading (smaller p at 2.5%, other at 5%) needs both horizons read together and a new signed text. | NEW |
| 6 | **R4 (holdout agrees)**: holdout mean above zero **and** development mean above zero, strictly. | As written. | "Same sign" only: the code does not implement it; zero and ties stay ambiguous. | NEW |
| 7 | **PENDING_HOLDOUT**: the interim word when development checks pass but the holdout has not run. | Keep; it is not an outcome. | Hide it: a development-only result would then print a word it cannot back. | NEW |
| 8 | **When is the holdout run (D-H)?** | Only if development says PENDING_HOLDOUT; otherwise it stays unrun. Test the separate holdout run on synthetic data first (not yet verified). | Run it every time: it is consumed in every case, and exposed even when not needed. | NEW |
| 9 | **Is SX10 worth running?** Power at a realistic gain is only 7% to 20% (SX5 15% to 45%); SX10 is about 1.5x harder. | Your programme choice; my lean: run SX5, decide SX10 after reading it, or fold SX10 into SX5 as a descriptive extension. | Run both: no technical problem, but a likely FAIL/INCONCLUSIVE with little information. | NEW |
| 10 | **"Ideas per fold"**: picks are counted as 5 per day before any no-repeat rule, so the "20 picks" test never bites. | Keep (it is only a data-sufficiency test). | Count after a no-repeat rule: not implemented; needs code. | NEW |
| 11 | **Lock file** `backend/requirements-research.lock` with exact versions, hash named in the text. | Create it from the signing machine's `pip freeze`. | Without it only five libraries are checked by code; the rest can drift. | NEW |
| 12 | **Signed git tags** over each registry commit (after authorisation, after start, after completion). | Yes, publish the tag hashes. | Without them the registry only deters accidents; history can be rewritten. | NEW |
| 13 | **Limitation U** (47 fixed survivors; no generalisation) signed verbatim. | Accept verbatim. | Any weaker wording is a claim the data cannot back. | basis |
| 14 | **Economics** (after-cost trade result) is a no-weight diagnostic forever. | Yes, fixed. | "Unless I sign it later" leaves a door open after results. | basis |
| 15 | **HINDUNILVR**: keep its 187 rows excluded; fresh fetch pending. | Keep excluded. | If the fetch changes anything, every hash is reissued. | basis |
| 16 | **Files with assumed dates**: rename/redate before signing (section e). | Yes, in one commit, before the code is hashed. | Signing with wrong dates in names and code comments invites a later "which one is real" dispute. | NEW |
| 17 | **Who signs.** | You, personally. No session or subagent signs. | None acceptable. | basis |

## (b) Already verified (evidence files in `docs/brain/evidence/sector_prep/` unless noted)

| What | Evidence |
|---|---|
| 45,935 / 45,700 rows; reconciliation raw to final; assembler equals reconciliation | `reconciliation_v3.md`, `final_verification_v3.md` |
| Complete hashes: row lists, configs, folds, exclusions, manifests, recipe | `final_hashes_v3.json`, `feature_manifests_v3.json` |
| 5 restored APOLLOHOSP rows: point in time, mutation test with power at 1 to 60 sessions, matured labels, training only | `apollohosp_mutation_check_v1.md`, `final_verification_v3.md` |
| Purge recount: 0 mismatches in 35 folds; test rows unchanged | `final_verification_v3.md`, `final_verification_v3_folds.csv` |
| The 53 existing inputs show no look-ahead (1,225 stock-days, 0 mismatches) | `feature_audit_53.json` |
| C_56 decision (dropped input is a difference of two existing inputs) | `c56_decision_v3.json` |
| R_37 names/order equal production model 2; `obv_slope` difference documented | `model2_saved_features_v1.json`, `r37_semantic_drift_v1.json` |
| Minimum detectable gain and power (S-9) | `sx_s9_power_v1.json` |
| Survivorship (47 are today's survivors; no point-in-time list available locally) and rule audit | survivorship-and-rule-audit note (`docs/superpowers/specs`) |
| Holdout registry: empty; exposure gate; recovery rules; races, kills, torn writes tested on synthetic data | holdout-registry-security-review note (`docs/superpowers/specs`); `final_verification_v3.md` section 1c |
| Mechanical verdict code and its tests | verdict-code-spec note; `ml/sx_verdict.py` |
| Re-run while preparing these drafts: `test_sx_verdict.py`, `test_sx_recipe.py`, `test_sector_walkforward.py`: **65 passed** (4 database-named tests deselected) | this session; not the full suite |

## (c) Outstanding technical work before signing

1. **Rename/redate** the assumed-date files (section e) in one commit, then update the code docstrings that name them (this changes the code hash, so do it first).
2. **Commit** the registry, harness, recipe, registry code, verdict code and the two final protocol files; the code-version string is the **full commit hash**. Replace `sx_verdict_v0_PROPOSED` by a final name.
3. **Regenerate the hash sheet** on that commit (clean tree required): `cd backend; PYTHONPATH=src python scripts/final_hash_sheet.py <FULL-40-HEX> --out <sheet.json> --protocol SX5=<path> --protocol SX10=<path> --prior-sheet ../docs/brain/evidence/sector_prep/final_hashes_v3.json`. Every value must equal the protocols except the commit, the protocol hashes and the environment. Fill the **matrix hash** (needs the signing environment's pandas) and the verdict parameter and code hashes.
4. **Clean full-suite result** recorded on that commit (not run here; only the SX tests above were re-run).
5. **HINDUNILVR fresh fetch** (or accept the exclusion as final).
6. Test that a **holdout-only run** after a development-only run works on synthetic data (decision 8).
7. Create the **lock file** (decision 11) and decide the tag procedure (decision 12).
8. Write the **experiment-register row** at signing (record the final hashes; "no outcome read").

## (d) Order of operations, signing to any training

1. You decide the table above (1 to 17). 2. Rename/redate; commit; regenerate the hash sheet; run the full suite. 3. You sign both protocols (blank signature lines; MDE_H and E\* written in) and a signed git tag marks the commit. 4. Experiment-register row written. 5. Approval file created by you (complete `config_sha256`, never a prefix). 6. **Nothing is trained before 2026-12-04.** 7. On or after that date, only with a **separate explicit training authorisation** from you: dry-run first, then the development folds. 8. Verdict computed once, development-only call. 9. Only if it says PENDING_HOLDOUT: you sign the holdout authorisation in the registry, tag it, run the holdout once, tag again, then the final verdict call. 10. Outcome recorded with equal prominence; PASS only proposes a separately signed forward shadow test. No re-runs, no extensions under the same protocol id.

## (e) Files whose names or text carry assumed dates

The dates 2026-11-05 to 2026-11-08 and the "Update 2026-11-0x" headings in earlier files were assumptions, not real dates (they lie in the future of the real preparation date). Recommended step, before signing: `git mv` each file to a date-free name (for example `sx5-research-protocol-superseded.md`, `sx-s9-power-analysis.md`), replace "Date: 2026-11-0x" lines by "Prepared: before signing", rename "Update 2026-11-0x" headings to "Update 1 / 2", fix every cross-reference in the other documents and in the code docstrings, then hash. Keep the seed 20261108 in the power script and its JSON **unchanged**: it is a recorded number, not a date to correct.

| File (under `docs/superpowers/specs` unless noted) | Where the assumed date is | Action |
|---|---|---|
| `2026-11-05-sx5-research-protocol-DRAFT.md`, `2026-11-05-sx10-research-protocol-DRAFT.md` | name; "Date: 2026-11-05"; headings "Update 2026-11-06", "Update 2026-11-07"; many "2026-11-0x" decisions | superseded by the FINAL-DRAFT files: rename to `...-superseded.md` or move to an archive folder |
| `2026-11-05-sx10-vs-tdv2-b1-differences.md` | name; "(2026-11-05)"; "Owner decision 2026-11-05/06" | rename, redate text |
| `2026-11-06-sx-model-recipe-FINAL-DRAFT.md` | name; "(UNSIGNED, 2026-11-06)" | rename |
| `2026-11-06-sx-presigning-findings.md` | name; "(2026-11-06)" | rename |
| `2026-11-07-sx-blockers-summary.md`, `2026-11-07-sx5-approval-package.md`, `2026-11-07-sx10-approval-package.md` | name; "(2026-11-07)", "Owner decision 2026-11-0x" | rename (packages are superseded by the final drafts) |
| `2026-11-08-sx-s9-power-analysis.md`, `2026-11-08-sx-survivorship-and-rule-audit.md`, `2026-11-08-sx-verdict-code-spec.md`, `2026-11-08-holdout-registry-security-review.md`, `2026-11-08-sx-hash-convention-and-environment.md` | name; "Date: 2026-11-08", "(2026-11-08)" | rename |
| `docs/brain/evidence/sector_prep/apollohosp_mutation_check_v1.md` | text "Date: 2026-11-08" | redate text |
| `.../final_verification_v3.md`, `.../final_hashes_v3.json` (key "date": "2026-11-07") | text only (names are fine) | redate text; the JSON is only read for the carried matrix hash, but regenerate the sheet anyway |
| `.../c56_decision_v3.json`, `.../model2_saved_features_v1.json`, `.../r37_semantic_drift_v1.json`, `.../index_availability_v2.md` | text dates 2026-11-05/06 | redate text |
| `docs/brain/SECTOR-FEATURES-SPEC.md` (existing file, edited on this branch) | "added 2026-11-07", "owner, 2026-11-07", "2026-11-06" | redate text |
| Code comments/docstrings: `ml/sx_verdict.py` (names the 2026-11-08 spec file), `ml/sx_recipe.py` (2026-11-06 recipe file), `ml/holdout_registry.py` (2026-11-08 review file), `ml/sector_research.py`, `ml/sector_walkforward.py`, `ml/sector_features.py`, `ml/exclusion_report.py`; tests `test_holdout_registry*.py` | file-name references and comment dates | update after the renames; **this changes the code hash** |
| `backend/scripts/sx_power_analysis.py` MASTER_SEED = 20261108 | a seed | **do not change** |
| Other docs that matched the pattern but are not SX files: `2026-10-15-evidence-and-pilot-plan.md`, `2026-10-24-evidence-plan-amendment-2-DRAFT.md` | not examined | leave |

The two FINAL-DRAFT files and this checklist carry no calendar date of their own; they refer to the older files by description, and those names are in this table.
