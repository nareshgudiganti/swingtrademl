# Starting the 15-day selection lab

Start the lab through the wrapper. It checks every start condition, writes an audit line, and then calls the
runner with your arguments unchanged. **The runner repeats the same checks itself** (see "What this prevents" below), so
starting it directly is refused for the same reasons; the wrapper is the documented, supervised way, not the only guarded one.

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

## What this prevents, and what it does not

**The runner enforces the start conditions itself.** `selection_lab_run.main` (the command line) and
`selection_lab_run.run` (a direct call) both call `selection_lab_start.guard_for_runner` before any data is read. That
function runs the same `evaluate` as the wrapper, so the two cannot drift: the date (2026-12-05 IST or later), the Phase B
terminal record and tags, the protocol tag, a clean tree, unchanged frozen files and the runner's own helpers. So
`python -m swing_trade_ml.brain.selection_lab_run S0`, and `run(...)` called from any script, are refused before 2026-12-05
and without the Phase B record, exactly like the wrapper. Every such attempt writes one `runner_start_check` line to the
audit log (with `via` = `cli` or `run`). There is no environment variable, flag or argument on the command line that
turns the checks off. `selection_lab_start.py` is in the runner's frozen-file list, so editing the guard after the
signing tag is itself caught.

**What is technically prevented:** starting a candidate from the command line (wrapper or runner) or through `run()` on
any day before the lock, without the verified Phase B record, from a dirty tree, or after a frozen file changed.

**What is not prevented (be honest about it):**
- Someone with write access to the repository can edit the files before running them. The tag and the frozen-file check
  detect an edit after the tag (the run then refuses); they cannot stop an edit before it.
- `run()` has a `start_check` parameter that exists only so unit tests can run it on a synthetic repository. Code that passes it
  skips the guard. No production code passes it, and a test fails if the command line or the default path stops using the guard.
- The library functions in `brain/selection_lab.py` can be called directly by a person writing new code; they are not a start path
  (they write no ledger row and no run folder).
- The audit log is a local, git-ignored file; it records attempts, it does not lock anything.

A test also fails if any non-frozen code, script or workflow in the repo calls the runner directly, so no scheduled job or
documented command bypasses the wrapper by habit.
