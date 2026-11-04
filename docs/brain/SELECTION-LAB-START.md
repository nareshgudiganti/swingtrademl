# Starting the 15-day selection lab

Start the lab only through the wrapper. It checks every start condition, writes an audit line, and then calls the
frozen runner with your arguments unchanged.

```
python -m swing_trade_ml.brain.selection_lab_start S0             # real start
python -m swing_trade_ml.brain.selection_lab_start S0 --check-only  # run the checks, never start
selection-lab-start S0 --check-only                                 # same, after `pip install -e backend`
```

Any other argument (for example `--technical-rerun`) is passed to the runner as is.

## What it checks (all must pass; a check that cannot be verified counts as a failure)

1. **Date.** Today in India time (IST) is 5 December 2026 or later (Amendment 2, item 2).
2. **Phase B is finished and recorded.** Phase B is complete when its terminal record exists, whether a
   survivor was chosen or not. The wrapper requires all of:
   - annotated git tags `evidence-defs-v1`, `evidence-defs-v2`, `phase-b-settings` and `phase-b-result`, all in
     this commit's history (a lightweight tag is refused); `phase-b-result` was created by 4 December 2026 IST;
   - `docs/brain/evidence/phase_b/PHASE_B_RESULT.json` is present, is the same file as at the tag, and its sha256
     equals the `result_sha256` in the tag message and the one in the single "Phase B result" row of
     `docs/brain/EXPOSURE-LEDGER.md` (read at the tag);
   - the record (written by `brain/phase_b_finish.py`) has schema `phase-b-result-v1`, outcome
     `SURVIVOR_SELECTED` or `NO_SURVIVOR`, a `written_at_ist` no later than 4 December 2026 IST, and all of B1, B2,
     B3. The tag message must repeat `outcome=`, `survivor=` (`none` after NO SURVIVOR) and
     `ledger_row=Phase B result record`. Each candidate's `survives` must agree with its stored check labels
     (the signed rule), and the `selection` block (method `phase-b-completion-v1`, survivors, ranking) must agree
     with the outcome;
   - every result file listed per candidate, and each `MANIFEST_Bn.json` (schema
     `phase-b-candidate-manifest-v1`), exists, is unchanged since the tag and matches the sha256 in the record;
     the manifest's file hashes, split hash and ledger row agree with the record and the ledger. Each candidate's
     `evidence_commit` is in this history, holds that candidate's two result files, its manifest and the ledger,
     and the commits form a strict chain in ledger-row order (each candidate committed before the next run);
   - the ledger (read at the tag) has exactly one row per candidate and exactly one "Phase B result record" row
     holding the record's sha256;
   - `SURVIVOR_SELECTED`: the named survivor is marked as surviving and ranked first, and the annotated tag
     `wf-protocol-v2` is in history with `survivor=` that candidate and `result_tag=phase-b-result`.
     `NO_SURVIVOR`: no candidate survives and `wf-protocol-v2` must NOT exist (if it does, the records contradict
     each other and the wrapper refuses).
   Passing this check does not promote anything automatically: a NO SURVIVOR lab start still needs the owner's
   Amendment 3, evidence and readiness gates, which are outside this wrapper.
3. **Protocol tag.** `sl-protocol-v1` exists and is an ancestor of HEAD.
4. **Clean tree.** No uncommitted or untracked changes.
5. **Frozen files.** Each file the runner lists as frozen is byte-identical at HEAD and at the tag. A file missing
   at both is allowed with a warning (the design document is not on `main` today); missing at only one is a refusal.
6. **The runner's own guard**, called not copied: tag in history, frozen files unchanged, clean tree, amendment signed.
   (The runner still checks gap classification, earlier runs and comparison results itself, with the database.)

## Audit log

Every attempt, allowed or refused (and `--check-only`), adds one JSON line to `backend/data/lab_start_audit.jsonl`:
time in UTC and IST, candidate, arguments, git HEAD, tag commit, each check's result and reasons, and the decision.
After a real start a second line records the runner's exit code. The file is git-ignored so it never dirties the
tree. If it cannot be written, the wrapper refuses and the runner is not called.

## Limitation: this is not a hard lock

Someone can still run the frozen runner directly (`python -m swing_trade_ml.brain.selection_lab_run S0`) and skip
the wrapper. The runner has its own guard, but not the date or Phase B checks. Direct execution is therefore
restricted by rule, not by code: the lab is started only through the wrapper, with the owner supervising.
A test fails if any non-frozen code, script or workflow in the repo calls the runner directly.
