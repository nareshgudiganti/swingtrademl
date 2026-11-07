# SX5 preparation: record of the owner's decisions on the review checklist

Recorded: 2026-11-06, from the owner's written instruction in the working session ("Proceed with SX5 preparation using the
recommended defaults, subject to reviewing all 17 decisions and preserving the existing safety and evaluation
requirements. This is not training approval."). Companion to `sx-owner-review-checklist.md` (not edited) and
`sx5-research-protocol-FINAL-DRAFT-for-review.md`.

## What this record is, and is not

- It records that the owner accepted the **recommended default** of each of the 17 decisions for SX5 **preparation**.
- It is **NOT a signature** on the protocol (decision 17: the owner signs personally, no session or subagent signs).
- It is **NOT training approval and NOT a go.** Signing is not a go either. **No training before 2026-12-04**, and none
  after that date without a separate explicit written authorisation from the owner. No holdout run, no registry
  authorisation, no approval file is created by this record.
- SX10 stays **DEFERRED** (owner, 2026-11-04). Nothing here revives it; a revisit needs a new protocol id.
- The owner asked for the decisions to be reviewed again; they are re-read at signing. Nothing is final until signed.

## The 17 decisions

| # | Decision | Recorded outcome | Status |
|---|---|---|---|
| 1 | MDE_H | **SX5: 0.0018 (0.18 pp per trade, a fraction)**; SX10: none (deferred). Never changed after a result. | accepted default |
| 2 | E\* (the gain below which the owner no longer cares) | **0.10 percentage points per trade, written as the fraction 0.0010 (SX5).** The owner chose the recommended value on 2026-11-07 (in the working session). The code does not use it; it only words the plain-English reading and the decision to propose a forward test. It is written into the protocol at signing and never changed after a result. | **decided 2026-11-07; written in at signing** |
| 3 | SX10 primary quantity (D-Q10) | Moot while SX10 is deferred. (a) raw 10-day return stays the code's primary. | accepted default, moot |
| 4 | Meaning of FAIL and INCONCLUSIVE | Accepted as written; every FAIL report carries "this does not show the inputs do nothing". | accepted default |
| 5 | One-horizon Holm timing | Each horizon read alone at the strict 2.5% bound; the 5% relaxation is never used. | accepted default |
| 6 | R4 (holdout agrees) | Holdout mean above zero **and** development mean above zero, strictly. | accepted default |
| 7 | PENDING_HOLDOUT interim word | Kept; it is not an outcome. | accepted default |
| 8 | When the holdout is run | Only if development says PENDING_HOLDOUT; otherwise it stays unrun. The separate holdout run after a development-only run is now tested on synthetic data: `backend/tests/test_sx_holdout_after_development.py`. | accepted default; synthetic test added |
| 9 | Is SX10 worth running | **SX10 DEFERRED** (no training, no holdout use, no registry authorisation). | decided 2026-11-04, unchanged |
| 10 | Ideas per fold | `no_repeat`, at least 20 ideas; fixed before any result and not changed to avoid INCONCLUSIVE. | accepted default |
| 11 | Lock file | `backend/requirements-research.lock` created from `pip freeze` of the project venv: 96 exact `==` pins, names and versions only (the editable self-install line is left out). sha256 of the file `eb06d191fcedaa54d02f480fced70b8f0f120171796630860439d86193bdf290`. The signing machine must re-create or confirm it (see below). | created; confirm at signing |
| 12 | Signed git tags over each registry commit | Accepted in principle. Tags are created **by the owner** (after authorisation, after start, after completion). None exists; none was created. | owner act, not done |
| 13 | Limitation U (47 fixed survivors, no generalisation) | Accept verbatim. | accepted default |
| 14 | Economics are a no-weight diagnostic forever | Accepted: the primary quantity is gross; costs only partly cancel. | accepted default |
| 15 | HINDUNILVR | Its 187 rows stay excluded, and this is final. The owner decided on 2026-11-07 (in the working session) to accept the exclusion: **no fresh fetch is required** before signing or for SX5. If a fetch were ever run and changed anything, every hash would be reissued under a new protocol version. | **decided 2026-11-07: exclusion final, no fetch required** |
| 16 | Files with assumed dates | Renamed and redated in one commit before the code was hashed (mapping below). | done |
| 17 | Who signs | The owner, personally. Not done. | owner act, not done |

Blockers B1 to B14 and B16 to B19 were already taken as accepted on their recommended defaults in the checklist and
are not repeated.

## Decision 16: what was renamed (documents only, content otherwise unchanged apart from dates and cross-references)

| Old name | New name |
|---|---|
| `2026-11-05-sx5-research-protocol-DRAFT.md` | `sx5-research-protocol-superseded.md` |
| `2026-11-05-sx10-research-protocol-DRAFT.md` | `sx10-research-protocol-superseded.md` |
| `2026-11-05-sx10-vs-tdv2-b1-differences.md` | `sx10-vs-tdv2-b1-differences.md` |
| `2026-11-06-sx-model-recipe-FINAL-DRAFT.md` | `sx-model-recipe-FINAL-DRAFT.md` |
| `2026-11-06-sx-presigning-findings.md` | `sx-presigning-findings.md` |
| `2026-11-07-sx-blockers-summary.md` | `sx-blockers-summary.md` |
| `2026-11-07-sx5-approval-package.md` | `sx5-approval-package-superseded.md` |
| `2026-11-07-sx10-approval-package.md` | `sx10-approval-package-superseded.md` |
| `2026-11-08-sx-s9-power-analysis.md` | `sx-s9-power-analysis.md` |
| `2026-11-08-sx-survivorship-and-rule-audit.md` | `sx-survivorship-and-rule-audit.md` |
| `2026-11-08-sx-verdict-code-spec.md` | `sx-verdict-code-spec.md` |
| `2026-11-08-holdout-registry-security-review.md` | `holdout-registry-security-review.md` |
| `2026-11-08-sx-hash-convention-and-environment.md` | `sx-hash-convention-and-environment.md` |

"Date: 2026-11-0x" lines became "Prepared: before signing."; "Update 2026-11-06/07" headings became "Update 1 / Update 2";
other assumed dates in prose became "before signing". Cross-references in the documents, in the code docstrings
(`holdout_registry.py`, `sector_research.py`, `sx_recipe.py`, `sx_verdict.py`) and in `test_sector_c56_r37.py` were updated. The
seed 20261108 in the power script and its JSON was **not** touched. The two FINAL-DRAFT protocol texts and the checklist
itself were **not** edited. Some dated JSON evidence (`c56_decision_v3.json`, `r37_semantic_drift_v1.json`,
`model2_saved_features_v1.json` "read_on") and the title of `index_availability_v2.md` still carry 2026-11-05/06 and were not in
the checklist's table; they are data or evidence, left unchanged.

## Code-version name

`ml/sx_verdict.py` `VERDICT_CODE_VERSION` was `sx_verdict_v0_PROPOSED` and is now `sx_verdict_v1` (checklist section c, item 2).
The two FINAL-DRAFT protocols still quote the old string in their **illustrative** parameter-set hash, which the
protocols themselves say is recomputed at signing; the owner must expect that hash (and the illustrative verdict-code
sha256) to change. The run records' `code_version` is the full signing commit hash, not this string.

## Execution driver and hash sheet v5 (added after the first sheet)

* **Driver.** `backend/scripts/sx5_run.py` (commit `4f4077673f3842b24ec70cc5b035c3db41f35488`; tests `backend/tests/test_sx5_run.py`, 34 on synthetic data;
  guide `docs/brain/SX5-RUN.md`). No end-to-end SX5 command existed before it: only the library pieces (`run_walkforward`,
  assembler, recipe, verdict). It is a dry run by default; a real run needs `--run`, the date 2026-12-04 or later, the harness approval
  file (with an extra `code_commit` key), a SEPARATE training authorisation (schema `sx5-training-authorisation-v1`, development only,
  never the holdout), a clean tree, HEAD equal to both files' commit, and eight recomputed hashes equal to the authorisation's.
  It passes development folds only, calls the verdict once, never reads a holdout record, never writes the registry. It is a
  script (not under `src/`) so the "nothing in the app imports the harness" test and protocol section 12 stay true. It is not a
  training approval and nothing was trained.
* **Hash-sheet defect fixed** (commit `6ca1920114ef1174fc7e4c49099b90b33c52def1`). `scripts/final_hash_sheet.py` copied the `_status` text key over the
  matrix hash when a sheet that was itself carried was used as `--prior-sheet`, so v5 would have lost the carried matrix hashes
  (`d131c710...`, `ee5eba79...`). It now carries only a real 64-hex value from the exact key (or the v3 descriptive key); regression test added.
* **Sheet v5** `docs/brain/evidence/sector_prep/final_hashes_v5.json` is for commit `6ca1920114ef1174fc7e4c49099b90b33c52def1` (clean tree, `--protocol SX5_protocol=...
  --protocol SX10_protocol=... --protocol recipe_document=... --prior-sheet final_hashes_v4.json`). It differs from v4 in the commit
  only; every substantive hash and the carried matrix hashes are unchanged. Note that the `code_version` for the real run is the
  full commit hash of the SIGNING commit, so this sheet (and the record's commit hashes) is regenerated again at signing.

## Hashes that change at signing (protocol text and sheet)

| Item | Why it changes | Where |
|---|---|---|
| Full commit hash | the signing commit is later than `6ca19201...`; `code_version`, `code_commit` in both run files, the sheet's `commit` | both protocols, sheet, approval, authorisation |
| SX5 protocol file sha256 (now `4e54f614...`, LF) | the owner fills in protocol id, MDE_H, E\*, signature | sheet `protocol_file_sha256`, authorisation `protocol_sha256` |
| Illustrative parameter-set sha256 `324d7f7b...` and verdict-code sha256 `109661ca...` quoted in the protocols | code name is now `sx_verdict_v1`; real values: parameter set (MDE_H 0.0018, units fraction) `98f47feb...2d180`, verdict code `0454850d...237b1`; both move again if any byte of `ml/sx_verdict.py` or MDE_H changes | protocol section 11 |
| Matrix hash `dataset_sha256` (`d131c710...`, carried) | depends on the signing environment's pandas; `sx5_run.py --with-data` prints the real one | protocol, authorisation |
| Lock-file sha256 (now `eb06d191...f290`) | regenerate if the signing machine's `pip freeze` differs | authorisation |
| Authorisation text hash (`TO_BE_FILLED_AT_SIGNING`) | written at signing | sheet |

Unchanged by anything here: DatasetSpec config sha256 `fb5648bb...2371`, recipe sha256 `fa6b3e97...1233`, row-list sha256 `fdf0b566...9f04`, the feature-list and
fold hashes, the exclusion hashes.

## Still blocked on the owner

1. **E\*** (decision 2): decided, 0.10 pp per trade (0.0010); it is written into the protocol text at signing.
2. **Signing** both protocols (blank signature lines; MDE_H and E\* written in) and **signed git tags** (decision 12).
3. The **experiment-register row** at signing, and the **approval file** (complete `config_sha256`, never a prefix).
4. A **separate explicit training authorisation**, on or after 2026-12-04, then a dry run first.
5. ~~The HINDUNILVR fresh fetch result (decision 15)~~ Not required: the owner accepted the exclusion as final on 2026-11-07.
6. **Matrix hash** (needs the signing environment's pandas) and the **signing-environment lock file** (decision 11): the hash
   sheet carries the matrix hash from the prior sheet and labels it as carried.
7. A clean **full-suite** result on the signing commit (this preparation ran only the SX and registry tests).
8. The **approval file** now also needs the key `code_commit` (full 40-hex) and the **separate training authorisation** file (see `docs/brain/SX5-RUN.md`).
