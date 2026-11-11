# November implementation-completion report (as of 2026-11-07)

Branch: `release/nov-completion` (local; nothing pushed, merged to `main`, tagged, signed or deployed). Base: `origin/main` `cbdb3f6`.
Owner decisions applied: 10D deferred (no td-protocol-v2, no retrain); SX5 prepared on the recommended defaults (NOT training approval);
development ends 2026-11-30; December is testing and bug fixing only.

## What is in the branch (merge commits, no squash)

| Part | Source branch | Content | Status |
|---|---|---|---|
| Phase B | `release/phase-b-code` | finish tool, tests, evidence `.gitattributes`, FINAL-DRAFT protocol, disclosure section 13a, signature package v2, seal-leak test fix (`783c3dd`) | built, tested, UNSIGNED |
| 15D lab + Amendment 3 | `change/a3-wrapper-integration` | lab start wrapper, Amendment 3 implementation (`sl-protocol-v1.1`, ranking only), lane slots, horizon report wording | built, tested, UNSIGNED, no tag |
| SX5 | `change/sx5-final-prep` | date-free renames, `sx_verdict_v1`, research lock file, synthetic holdout test, guarded driver `scripts/sx5_run.py`, hash sheet fix + v5, decision record | built, tested on synthetic data, NOT trained |
| 5D forward lane (h05) | already on `main` | live on prod: run 1 active, 5 of 5 sessions recorded to 2026-11-06, 0 missed | nothing to merge |

## Merge order for the owner (after 16:30 IST, never force a weekday-window deploy)

One combined PR from `release/nov-completion` using "Create a merge commit" (never squash or rebase: evidence hashes and tags point at commits).
Blob ids of the nine Phase B code files are unchanged by the merge; re-verify with the protocol's gate G8 on the merged `main`.
Every push to `main` deploys; this PR is tools, tests and documents only (one new console-script line in `pyproject.toml`), so the only production effect is the restart.

## Test results

| Run | Result |
|---|---|
| Full backend suite, `origin/main` merged into the release branch | first run: 10 failed + 6 errors, all triaged: none caused by the merge (Windows process-launch failures under load x12, one stale CRLF checkout, one seal-leak test bug already on `main` fixed by `783c3dd`, one shared-DB counter test); after fixes: 4,673 passed, 31 skipped, 0 failed |
| Full backend suite, `release/nov-completion` before the SX5 driver merge | 4,700 passed, 31 skipped, 0 failed, 0 errors |
| Focused: SX5 driver, hash sheet, trial freeze, Phase B finish, lab wrapper, Amendment 3 (after the final merge) | 238 passed |
| Frontend | not re-run in this pass (no frontend code changed by the branch) |
| Real data | none: Phase B, the lab and SX5 have never run on real data; nothing was trained |

Known defects found and NOT fixed (development freeze, all outside signed rules): `python -m swing_trade_ml.brain.scoreboard` fails with a
circular import (workaround in the runbook); `h05_job.py` docstring still says "not wired into the scheduler" (it is); TMCV is not scored
by h05 (`invalid_features`) every day.

## Unchanged by this work

`phase_b.py` is byte-identical to tag `phase-b-settings`; `trial_freeze.json` unchanged; production models not retrained or replaced; sealed trial
and h05 rules untouched; no signed evaluation criterion changed (Amendment 3 changes only the protocol id string, ledger marker text, signed-check logic,
the frozen-file list and wording).

## Outstanding blockers (all need the owner)

| # | Item | Deadline |
|---|---|---|
| 1 | Sign the Phase B protocol; merge; tag `phase-b-completion-v1`; say "start" in writing (protocol sections 11 and 14) | 2026-11-08 |
| 2 | Amendment 3: answer D1-D10, instruct creation of the signed marker `docs/brain/evidence/sl_v1/EVIDENCE_PLAN_AMENDMENT_3_SIGNED.md`, merge, tag `sl-protocol-v1.1` | before 2026-12-05 |
| 3 | SX5: E* (your number), sign both SX5 protocol texts, signed tag, approval file (needs `code_commit`), separate training authorisation, refresh the signing commit hash and protocol/matrix/lock hashes | before 2026-12-04 |
| 4 | HINDUNILVR/BAJAJELEC fresh-fetch result (read-only script) or accept the exclusion as final | before signing SX5 |
| 5 | Confirm the "mandatory gates" reading (protocol section 2a, marked inferred) | when signing Phase B |
| 6 | Amendment 3 risk R1: check the local database for old `sl1_*` models or `research_lab_runs` rows (not checked) | before the lab |
| 7 | h05 runs 2 and 3 started by hand after 2027-01-28 | 2027-01-25 reminder |
| 8 | A clean full-suite run on the final signing commit | at signing |

## December run commands

See `docs/brain/DECEMBER-RUNBOOK.md` (Phase B, 15D lab, SX5, daily and weekly checks, h05 runs 2 and 3, failure table).
