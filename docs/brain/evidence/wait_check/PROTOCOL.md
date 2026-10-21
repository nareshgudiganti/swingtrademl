# ps11 was WAIT / AVOID the right call? — protocol `ps11-wait-check-v1`

Written and committed 2026-10-21, **before** the run. One run. No retuning afterwards.

## Question

When the brain said WAIT or AVOID, would buying anyway have lost money? And did the ideas it wanted do
better than the ones it waited on?

## Data (development data, EXPOSURE-LEDGER.md)

- The whole-brain replay from ps1 (`ps1-module-ablation-v1`, variant "all modules"): every trading day
  2026-07-13 to 2026-08-14, model `swing_classifier_asof_20260710`, 7600 stock-days with the brain's final
  word. Copied unchanged to `judged_all_modules.json` so this run can be repeated.
- Known before the run (counts only, no results): 561 stock-days wanted (a TRADE the replay's risk check
  lowered), 7039 WAIT, 0 AVOID. AVOID is reported but has nothing to judge here.
- Prices up to 2026-09-07 (local data end).

## Method (`brain/wait_check.py`)

Every stock-day is scored as if it had been bought: the settled strict rule (next-day open, +8% / -4%,
half out at +5%, 15 trading days, real charges and slippage), normal costs. Groups: wanted, WAIT, AVOID,
every stock-day. Per group: finished, -4% first, +8% first, ran out of time, average result after costs,
share that lost money.

## Reading rule (fixed)

- "Good WAIT rate" = the share of finished WAIT stock-days whose result after costs is below zero
  (buying would have lost money). Same for AVOID when it has any.
- WAIT was the right call on average if its average result after costs is below zero.
- The brain separates good from bad if the wanted ideas' average is above WAIT's; otherwise the report
  says the wanted ideas did no better than the ones it waited on.
- Per day (both groups with at least one finished idea): on how many days the wanted ideas did better
  than WAIT, so one bad week cannot decide the answer alone.

Recorded as-is; nothing in the brain or its trial is changed because of it.

## Command

```
cd backend
python -m swing_trade_ml.brain.wait_check
```
