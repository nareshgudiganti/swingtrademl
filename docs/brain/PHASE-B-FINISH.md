# Phase B finish tool (`brain/phase_b_finish.py`)

Status: built and tested on synthetic fixtures only. Never run on real data. It does not edit `phase_b.py`
(which must stay byte-identical to tag `phase-b-settings`). The rules it applies are in the signed
Phase B completion protocol (draft: `2026-11-05-phase-b-completion-protocol-FINAL-DRAFT.md`).

## What it does

- `python -m swing_trade_ml.brain.phase_b_finish` : DRY RUN. Checks everything, prints the outcome
  (`SURVIVOR_SELECTED` or `NO_SURVIVOR`) and what it would write. Writes nothing.
- `... --apply` : writes `docs/brain/evidence/phase_b/PHASE_B_RESULT.json` and ONE ledger row
  ("Phase B result record"), then prints the `git add`, `git commit` and `git tag -a phase-b-result` commands.
  It never commits, tags, pushes or creates `wf-protocol-v2`. For `NO_SURVIVOR` it never prints any
  `wf-protocol-v2` command.
- `... --manifest B1 [--apply]` : after a candidate has run, writes that candidate's evidence manifest
  `MANIFEST_B1.json` (sha256 of its `.md`, `.json`, its ledger row, tags, split hash). Commit it together
  with the candidate's outputs and ledger row BEFORE running the next candidate.

## It refuses (exit 2, writes nothing) unless all hold

IST date 2026-11-09..2026-12-04; tags `evidence-defs-v1`, `evidence-defs-v2`, `phase-b-settings` exist, are
annotated and are ancestors of HEAD; split file hash matches its note and every result; clean tree; for
B1, B2, B3 the `.md`, `.json`, manifest and exactly one ledger row exist; each result is complete and
self-consistent (labels, `survives` re-derived with `phase_b.survives`, figures agree between `checks` and
`trade_level`, same window / trading days / folds, run on a clean tree); `phase_b.py` equals the settings tag
at HEAD and at each run commit; each manifest matches its files; each candidate's outputs were committed
together, unchanged since, and before the next candidate's; no `PHASE_B_RESULT.json`, no `phase-b-result`
tag, no result ledger row.

## Choosing a survivor (no discretion)

Survivors = candidates whose stored labels satisfy the signed rule. Highest wins on, in order:
`trade_level.candidate.edge_low` (lower 5th-percentile bound of the mean day edge over every-stock),
`edge_per_day`, `avg_net`, `edge_vs_momentum.edge_low` (all rounded to 6 decimals; a missing value ranks
last); remaining tie: lower candidate id (B1 < B2 < B3).

## Tests

`PYTHONPATH=backend/src env -u API_KEY -u DATABASE_URL -u JWT_SECRET_KEY -u TRADING_MODE
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_phase_b_finish.py` (pure; no DB).
