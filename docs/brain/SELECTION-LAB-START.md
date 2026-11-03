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
2. **Phase B is locked.** Phase B writes no "finished" file, so the wrapper checks the closest real evidence:
   the git tags `evidence-defs-v1`, `evidence-defs-v2`, `phase-b-settings` and `wf-protocol-v2` are all in this
   commit's history, and `docs/brain/EXPOSURE-LEDGER.md` has a row for each of Phase B's candidates B1, B2, B3.
   `wf-protocol-v2` is the tag the evidence plan says locks the single best survivor by 4 December. No code creates
   it, so the owner creates it by hand when locking.
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
