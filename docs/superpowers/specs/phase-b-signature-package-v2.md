# Phase B signature package v2 (owner summary)

Status: **for the owner's decision. Nothing here is signed, tagged, pushed, merged to `main` or deployed.** This replaces the older
`phase-b-signature-package.md`, whose blob ids predate 5 Nov and are wrong. Text to sign:
`2026-11-05-phase-b-completion-protocol-FINAL-DRAFT.md` (same folder). Signature and date lines are blank on purpose.

## 1. What you sign

One text, fixed before any Phase B result exists: how the best survivor is chosen (highest `edge_low`, then a fixed tie ladder, only among
candidates that pass both survival rows), B1 then B2 then B3 with each candidate's results committed before the next, the result record
(`PHASE_B_RESULT.json` + readable `PHASE_B_RESULT.md`), an idempotent separate finish tool, fail-closed handling of interruptions, and
the rule that a NO SURVIVOR outcome allows the 5 Dec lab only as independent experimental research, never promoting a failed model.
Section 13a (added 6 Nov) discloses known price-data steps; it changes no setting or rule.

Two things to confirm when signing: (a) "mandatory gates" = exactly the two survival rows of the signed sentence (protocol section 2a, marked inferred);
(b) the tag name `phase-b-completion-v1`.

## 2. Code binding (git blob ids; correct values, re-verified 2026-11-06 on `release/phase-b-code` a73b938)

| File | Git blob id |
|---|---|
| `backend/src/swing_trade_ml/brain/phase_b_finish.py` | `e34e0e42a35ed4fadb4ba5769c1e603e9ffbbb12` |
| `backend/tests/test_phase_b_finish.py` | `db6a3bb3b0316f0d86ba40930a98715949e6a509` |
| `backend/src/swing_trade_ml/brain/selection_lab_start.py` | `6f6f1fb73d0b70007fda4b7f5c6694444f035867` |
| `backend/tests/test_selection_lab_start.py` | `66d4d744480c164395aeb79dbbad243196343753` |
| `backend/src/swing_trade_ml/brain/phase_b.py` (= tag `phase-b-settings`, not edited) | `a64f99a9040ddfed477c7d3a7d98a59191b3d17f` |
| `docs/brain/evidence/phase_b/.gitattributes` | `fa1385d99a319b43c06f5309d1aae9fdd3adea46` |
| `docs/brain/PHASE-B-FINISH.md` | `46d3d7f83aafa2de0b40b255ec462cff1605829d` |
| `docs/brain/SELECTION-LAB-START.md` | `4e9da17af561aba3ae2afeb5411d57840101df34` |
| `backend/tests/trial_freeze.json` (frozen, not edited) | `8997b469c1b6697b70337c1a7c1473639bcb5584` |

Re-verify after merging (from a checkout of `main`); the nine ids must print in this order:

```bash
git rev-parse HEAD:backend/src/swing_trade_ml/brain/phase_b_finish.py HEAD:backend/tests/test_phase_b_finish.py \
  HEAD:backend/src/swing_trade_ml/brain/selection_lab_start.py HEAD:backend/tests/test_selection_lab_start.py \
  HEAD:backend/src/swing_trade_ml/brain/phase_b.py HEAD:docs/brain/evidence/phase_b/.gitattributes \
  HEAD:docs/brain/PHASE-B-FINISH.md HEAD:docs/brain/SELECTION-LAB-START.md HEAD:backend/tests/trial_freeze.json
git diff --exit-code phase-b-settings HEAD -- backend/src/swing_trade_ml/brain/phase_b.py   # exit 0
```

Merge-commit hash on `main` carrying all of the above (full 40 hex, you fill it in at signing): `______________________________________`

## 3. What you must do, and when (nothing is done for you)

| # | Step | When | Deploys? |
|---|---|---|---|
| 1 | Read the protocol and section 13a; decide the two confirmations above | by Sat 2026-11-07 | no |
| 2 | Push `release/phase-b-code` and open ONE pull request to `main`; check CI is green | Sat 2026-11-07 | no |
| 3 | Merge the PR with **"Create a merge commit"** (never squash or rebase), **only after 16:30 IST** (or on a weekend) | Sat 2026-11-07 or Sun 2026-11-08 | **yes, restarts api/worker; no behaviour change**. Needs your explicit approval |
| 4 | Wait for the deploy to finish green; run the read-only prod checks of `docs/DEPLOY.md` by hand | same day | no |
| 5 | Verify the nine blob ids on merged `main` (section 2) and write the merge hash into the protocol (section 11) | Sun 2026-11-08 | no |
| 6 | **Sign** (name and date in the protocol, sections 11/14) and merge that documents-only change, again after 16:30 IST | by **Sun 2026-11-08** | yes (docs only) |
| 7 | Create annotated tag `phase-b-completion-v1` on that merge commit and push it alone: `git tag -a phase-b-completion-v1 <merge> -m "signed=<name, date>" -m "finish_blob=e34e0e42a35ed4fadb4ba5769c1e603e9ffbbb12" -m "lab_wrapper_blob=6f6f1fb73d0b70007fda4b7f5c6694444f035867" -m "phase_b_blob=a64f99a9040ddfed477c7d3a7d98a59191b3d17f"`, then `git push origin phase-b-completion-v1` | Sun 2026-11-08 | no |
| 8 | Cut branch `phase-b-run` from the tag, run gates G1 to G15 (protocol section 11), write "start" | Mon 2026-11-09, before B1 | no |
| 9 | Run B1, then B2, then B3 per protocol section 7 | from 2026-11-09, record by 2026-12-04 | no |

Rules that stay: paper only; no deployment without your explicit approval; deploys only after 16:30 IST; no retraining or replacing
production models; sealed trial and h05 rules untouched; tags are never moved or deleted; `phase-b-result` and `wf-protocol-v2` are not
created early; Phase B does not run before 2026-11-09.

## 4. Residual risks you accept by signing

Section 9d of the protocol: the tools cannot detect an unauthorised removal of a never-committed ledger row (your gate G14 checks git
history). Price-data steps (section 13a) are disclosed, not corrected. Phase B results are development-data evidence only.

Owner: ______________________   Date (IST): ______________

Tag name and commit: ______________________
