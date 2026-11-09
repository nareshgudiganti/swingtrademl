# Phase B signature package v2 (owner summary)

Status: **for the owner's decision. Nothing here is signed, tagged, pushed, merged to `main` or deployed.** This replaces the older
`phase-b-signature-package.md`, whose blob ids predate 5 Nov and are wrong. Text to sign:
`2026-11-05-phase-b-completion-protocol-FINAL-DRAFT.md` (same folder). Signature and date lines are blank on purpose.

## 1. What you sign

One text, fixed before any Phase B result exists: how the best survivor is chosen (highest `edge_low`, then a fixed tie ladder, only among
candidates that pass both survival rows), B1 then B2 then B3 with each candidate's results committed before the next, the result record
(`PHASE_B_RESULT.json` + readable `PHASE_B_RESULT.md`), an idempotent separate finish tool, fail-closed handling of interruptions, and
the rule that a NO SURVIVOR outcome allows the 5 Dec lab only as independent experimental research, never promoting a failed model.
Section 13a discloses ALL known price-data steps found by the 7 Nov impact check (the 49, B2's extra training stocks and the reject set, with counts and worst-case bounds); it changes no setting or rule and nothing is corrected or re-fetched.

Owner decisions already given on 2026-11-07 and now written into the text (your signature confirms them): (a) "mandatory gates" = exactly the two
survival rows of the signed sentence (section 2a); (b) accept and disclose the price-data steps, no fresh fetch for HINDUNILVR or BAJAJELEC required
(section 13a); (c) D8 confirmed: the 15-day runner enforces the date and the Phase B record itself (section 12, "Runner guard").
Still open, one item: the tag name `phase-b-completion-v1` (keep it or rename it before signing).

## 2. Code binding (git blob ids; correct values, re-verified 2026-11-07 on `release/nov-completion` aa9ad47)

| File | Git blob id |
|---|---|
| `backend/src/swing_trade_ml/brain/phase_b_finish.py` | `e34e0e42a35ed4fadb4ba5769c1e603e9ffbbb12` |
| `backend/tests/test_phase_b_finish.py` | `db6a3bb3b0316f0d86ba40930a98715949e6a509` |
| `backend/src/swing_trade_ml/brain/selection_lab_start.py` | `8d5225c78b113c2e168f8d45d3f322c91b847284` |
| `backend/tests/test_selection_lab_start.py` | `855330abb14d70a5c19b00cee6df3f0e6e8a6d14` |
| `backend/src/swing_trade_ml/brain/phase_b.py` (= tag `phase-b-settings`, not edited) | `a64f99a9040ddfed477c7d3a7d98a59191b3d17f` |
| `docs/brain/evidence/phase_b/.gitattributes` | `fa1385d99a319b43c06f5309d1aae9fdd3adea46` |
| `docs/brain/PHASE-B-FINISH.md` | `46d3d7f83aafa2de0b40b255ec462cff1605829d` |
| `docs/brain/SELECTION-LAB-START.md` | `d051cb00d5635f2a50410f93a5f4ad3bff942ff2` |
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
| 1 | Read the protocol, sections 2a, 12 (Runner guard) and 13a; confirm or rename the tag name | by Sat 2026-11-07 | no |
| 2 | Push `release/nov-completion` (it contains Phase B, the lab wrapper and runner guard, Amendment 3 and SX5 preparation) and open ONE pull request to `main`; CI, including the secret scan, must be green | Sat 2026-11-07 | no |
| 3 | Merge the PR with **"Create a merge commit"** (never squash or rebase), **only after 16:30 IST** (or on a weekend) | Sat 2026-11-07 or Sun 2026-11-08 | **yes, restarts api/worker; no behaviour change**. Needs your explicit approval |
| 4 | Wait for the deploy to finish green; run the read-only prod checks of `docs/DEPLOY.md` by hand | same day | no |
| 5 | Verify the nine blob ids on merged `main` (section 2) and write the merge hash into the protocol (section 11) | Sun 2026-11-08 | no |
| 6 | **Sign** (name and date in the protocol, sections 11/14) and merge that documents-only change, again after 16:30 IST | by **Sun 2026-11-08** | yes (docs only) |
| 7 | Create annotated tag `phase-b-completion-v1` on that merge commit and push it alone: `git tag -a phase-b-completion-v1 <merge> -m "signed=<name, date>" -m "finish_blob=e34e0e42a35ed4fadb4ba5769c1e603e9ffbbb12" -m "lab_wrapper_blob=8d5225c78b113c2e168f8d45d3f322c91b847284" -m "phase_b_blob=a64f99a9040ddfed477c7d3a7d98a59191b3d17f"`, then `git push origin phase-b-completion-v1` | Sun 2026-11-08 | no |
| 8 | Cut branch `phase-b-run` from the tag, run gates G1 to G15 (protocol section 11), write "start" | Mon 2026-11-09, before B1 | no |
| 9 | Run B1, then B2, then B3 per protocol section 7 | from 2026-11-09, record by 2026-12-04 | no |

Rules that stay: paper only; no deployment without your explicit approval; deploys only after 16:30 IST; no retraining or replacing
production models; sealed trial and h05 rules untouched; tags are never moved or deleted; `phase-b-result` and `wf-protocol-v2` are not
created early; Phase B does not run before 2026-11-09.

## 4. Residual risks you accept by signing

Section 9d of the protocol: the tools cannot detect an unauthorised removal of a never-committed ledger row (your gate G14 checks git
history). Price-data steps (section 13a) are disclosed, not corrected. Phase B results are development-data evidence only.

Owner: ______________________   Date (IST): ______________

Tag name: ______________________  (the commit cannot be written here before the merge exists; it is the merge commit of the signing PR and is recorded in the tag annotation; see the note under the signature lines in the protocol)
