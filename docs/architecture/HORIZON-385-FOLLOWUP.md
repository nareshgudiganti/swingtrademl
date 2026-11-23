# #385 follow-up: the live Brain stamps a 5-day score as a 15-day plan

Proposal only. No code was changed for it. Status: for the owner's decision. Written 2026-11-24 (IST).
PR #449 and the horizon records do NOT fix this; they protect the new 5-session path only.

## The problem, in two places (verified in code; production values not re-verified)

1. Where the score comes from: one active model, `swing_classifier` (`brain/reader.py:42,467-470`), whatever horizon it was
   trained for. The project notes say production's is a +2% / 5-day model (NOT RE-VERIFIED today).
2. Where the 15 comes from. This corrects my audit (HORIZON-GAP-AUDIT.md), which named only the first:
   - the decision engine stamps `DecidePolicy.horizon_days = 15` (`brain/modules/m08_decide/policy.py:18`, used at
     `engine.py:165,177`) and writes "+8%, -4%, up to 15 trading days";
   - the fallback path stamps `RunRequest.horizon_days`, whose default is 15 (`brain/contracts.py:78`), and
     `brain/service.py:123` never sets it (`brain/fallbacks.py:228-231`);
   - `strategies/brain.py:144,159` copies that number onto the v1 `Signal`, so the signal matures after 15 sessions.

## Options

| | Change | Effect on decisions | Verdict |
|---|---|---|---|
| C. Carry | keep every decision exactly as is; add the score's real horizon to the idea's reasons ("this score is a 5-session forecast") | none: same words, levels, quantities | smallest; honest; recommended first |
| R. Refuse | when the scoring model's horizon differs from the run's, the score is not used: ideas become WAIT "no score for this horizon" | on production every TRADE idea stops | moves toward caution, but ends the sealed trial's evidence stream: owner decision |
| L. Relabel | stamp 5 sessions and the model's own +2% / -4% | changes levels and maturity | rejected: a behaviour change, not a label fix |

Recommended order: **C now, R only if the owner wants the trial to stop on a mismatch.** Both read the model's horizon from
`ml_models.prediction_horizon_days` and sit behind one switch `BRAIN_HORIZON_GUARD = off | label | refuse`, default `off`,
so a deploy is inert until the owner flips it, and rollback is flipping it back.

## Frozen files it touches (`tests/trial_freeze.json`)

- `brain/service.py` (read the scoring model's horizon once per run, hand it to the context),
- `brain/fallbacks.py` and `brain/modules/m08_decide/engine.py` (add the reason line; for R, withhold the score),
- not needed: `brain/contracts.py`, `brain/reader.py`, `policy.py`, `strategies/brain.py` (the default stays 15, so equal-horizon runs are unchanged).
Each touched file needs the owner's approval recorded through `scripts/approve_trial_change.py`. The sealed-trial journal must
note the date: decisions before and after the switch are not comparable if `refuse` is ever turned on.

## Owner approvals needed

1. Read-only production check of the active model's horizon and target (confirms the cause).
2. Option choice: C only, or C then R.
3. The freeze approvals for the three files, and the switch's default (`off`).
4. Merge and a separate manual deploy (a merge does not deploy). `review-risk` and an independent review before merge.

## Tests that would prove it

- The strict xfail `tests/test_horizon_385_mixup.py` turns into a pass and its marker is removed.
- Equal horizons (a 15-session model, 15-session run): decisions byte-identical to today, with the switch `off`, `label` and `refuse`.
- 5-session model, 15-session run: `off` identical to today; `label` identical words and levels plus the reason line; `refuse` gives WAIT and no score.
- The Signal's `horizon_days` and maturity are unchanged in `off` and `label`.
- `test_trial_freeze` passes with the re-pinned hashes only for the three approved files; the h05 lane tests are untouched.

## Rollback

Set `BRAIN_HORIZON_GUARD=off` (no deploy). Or revert the PR: code only, no schema, no data to repair. Reason lines already
written stay as history.
