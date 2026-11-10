# Weekly training-eligibility report

Read-only. It trains nothing, writes nothing to the database, makes no network call, and is not scheduled
(no job, no API route). Run it by hand:

```
cd backend
env -u API_KEY -u DATABASE_URL -u JWT_SECRET_KEY -u TRADING_MODE PYTHONPATH=src \
  .venv/Scripts/python.exe -m swing_trade_ml.brain.eligibility_report [--json]
```

It answers, per lane: how many outcomes have matured, how many the protocol needs, the earliest allowed
date, which protocol gates block, and one verdict word.

## Verdict words

| Word | Meaning |
|---|---|
| OBSERVE_ONLY | The lane is an evaluation. Its protocol never allows training a new candidate. Keep collecting. |
| BLOCKED_BY_PROTOCOL | A date, tag or signature gate is not met. Listed under "blocking". |
| ELIGIBLE_NOT_AUTHORISED | Every gate the report can check is met. The owner's own step (starting the lab, writing the SX5 authorisation) is still needed. The report never assumes it. |
| NOT_APPLICABLE | No slot. 10D is deferred (td-protocol-v1 failed its history gate). |

## Lanes and where each threshold comes from

| Lane | Needed | Source |
|---|---|---|
| 5D large / mid / small (h05) | 40 matured signal days per group per run | `lanes/h05_protocol.py` `RUN_VALUES["min_evidence_per_group"]` (U2); `docs/superpowers/specs/2026-10-30-h05-protocol-v1-DRAFT.md` U2 |
| 10D | none (deferred) | `docs/brain/PROJECT_COMPLETION_MATRIX.md`; `docs/brain/evidence/td_v1/` |
| 15D large / mid (selection lab) | not before 2026-12-05 IST, tags `phase-b-result` and `sl-protocol-v1.1`, Amendment 3 signed marker | `brain/selection_lab_start.py` `EARLIEST_START`; `brain/selection_lab_run.py` `TAG`, `AMENDMENT`; `docs/brain/SELECTION-LAB-START.md` |
| SX5 | not before 2026-12-04 IST, signed protocol, approval file, separate training authorisation | `backend/scripts/sx5_run.py` `EARLIEST_REAL_DATE`; `docs/brain/SX5-RUN.md` |

A test (`tests/test_eligibility_report.py::test_constants_match_the_code_they_mirror`) fails if any mirrored
constant drifts from its source.

## Reading the numbers

- **5D "matured"** counts signal days, not picks. A day counts when at least 10 stocks were scored in the group
  and at least one counted pick (selected, not a repeat) has a finished shadow trade (target, stop or expiry).
  This is the same rule the h05 report uses. The 5D lanes stay OBSERVE_ONLY even once 40 is reached: h05 is an
  evaluation of the existing models and forbids retraining. Reaching 40 only means a run can give a verdict.
  "blocking" for 5D lists lane switches that stop collection (lane enabled, protocol hash accepted, run 1 started).
- **n/a** for 15D and SX5 is deliberate. They are history evaluations with no forward picks, so there is no matured
  count to report.
- **"unknown (not zero)"**: if the database cannot be read the 5D count is left blank, never shown as 0.
- Tags are read with `git tag --list`. The report cannot see the SX5 approval or authorisation files, so SX5 stops
  at ELIGIBLE_NOT_AUTHORISED at best.

## Seal

Only status columns are read (group, day, scored, selected, repeat flag, trade status). No return, hit, score or
brain-trial outcome is selected, so nothing sealed by `services/trial_seal.py` is exposed, and the output has no
result figures.
