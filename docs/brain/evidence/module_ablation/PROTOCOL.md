# ps1 module on/off — protocol `ps1-module-ablation-v1`

Written and committed 2026-10-20, **before** the run. One run. No retuning afterwards.

## Question

Which modules really change the brain's decisions, and do those changes help?

## Method (`brain/module_ablation.py`)

- Days: every trading day 2026-07-13 to 2026-08-14, the only window after the one local as-of model's
  cutoff (`swing_classifier_asof_20260710`, cutoff 2026-07-10) whose ideas have all finished by 2026-09-07.
  (The plan said 40 sampled days; the data allows these ~24.)
- Base: the whole brain. Then one replay per module, with that module left out of the registry, so the runner
  uses its safe fallback as it would live if the module failed.
- Tested: modules switched ON locally (M01, M02, M03, M04, M07, M08, M10, M11, M13).
  Not tested: shadow modules (M05, M06, M12: cannot change a decision); M09 (learns after the decision);
  M14 and M15 (a replay sees today's account and holdings).
- M07 (mandatory risk gate) off is the fallback check: there must be no TRADE at all.
- Per variant against the base: decisions whose final word changed; liked ideas (TRADE or a lowered TRADE)
  added and dropped; liked ideas' result after costs (strict rule).

## Reading rule (fixed)

- No decision changed → "adds nothing on these days".
- Otherwise: the base's average result per liked idea minus the variant's → "helps" (> 0) or "hurts" (< 0).
- M07: zero TRADE words → "safe fallback"; any TRADE → "UNSAFE" (a bug to fix after the trial).
Recorded as-is; nothing in the brain or its trial is changed because of it.

## Command

```
cd backend
python -m swing_trade_ml.brain.module_ablation --from 2026-07-13 --to 2026-08-14 \
    --asof-model swing_classifier_asof_20260710
```

## Correction after the run (2026-10-21)

The fixed reading rule only looked at final words. In a replay the risk check uses today's account and refuses
every idea, so no final word is ever TRADE and "decisions changed" is 0 for every module, even M08, whose
removal dropped all 561 liked ideas. The rule then read M08 as "adds nothing", which is wrong. The reading now
also looks at the liked ideas (added / dropped). Only the wording of the reading changed: no replay was rerun,
no number changed, nothing in the brain or the trial changed.
