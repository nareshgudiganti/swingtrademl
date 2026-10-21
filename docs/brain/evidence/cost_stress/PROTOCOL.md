# ps3 cost stress — protocol `ps3-cost-stress-v1`

Written and committed 2026-10-20, **before** the run. One run. No retuning afterwards.

## Question

Does the result survive dearer trading? Same picks, scored again at higher costs.

## Settings (fixed)

| Setting | Meaning |
|---|---|
| normal costs | The settled strict rule (`replay_scoring.strict_score`): next-day open, +8% / -4%, half out at +5%, 15 trading days, real charges, 0.05% slippage per fill |
| 2x charges | Brokerage and taxes doubled |
| fills 0.30% worse | Every buy and sell 0.3% worse, on top of the normal slippage; target and stop follow the dearer buy |
| 2x charges, fills 0.30% worse | Both. **The answer is read here.** |

A measured slippage from ps4 is added as a fifth row later, if it exists; it does not change the answer row.

## Data (all development data, EXPOSURE-LEDGER.md)

1. Walk-forward 2023-07-01 to 2025-01-31: the period of the frozen wf-protocol-v1 run (already spent).
   Same folds (28 days), same 49 watchlist stocks, model's best 5 a day, every-stock and momentum baselines.
   Each fold's model is trained once; only the scoring changes per setting.
2. Stored as-of replay ideas `asof_replay_2026-07-13_2026-08-14.json` (561 ideas), re-scored from prices.
   At normal costs each idea must reproduce its stored result; mismatches are reported.

## Reading rule (fixed)

One sentence per source: at "2x charges, fills 0.30% worse", the model's average result per trade
**stays above zero** or **does not**, and (walk-forward) its edge per day over every stock stays above zero
or does not. A pass is not evidence (development data). A fail is recorded as a weakness.
Nothing in the brain, its rules or its trial is changed because of the result.

## Command

```
cd backend
python -m swing_trade_ml.brain.cost_stress --wf-from 2023-07-01 --wf-to 2025-01-31 \
    --replay ../docs/brain/evidence/asof_replay_2026-07-13_2026-08-14.json
```

## Result (run 2026-10-20, one run)

- Reproduction: at normal costs the walk-forward re-run equals the frozen wf-protocol-v1 result exactly
  (1,980 ideas, -0.204% per trade, edge -0.187% a day); all 561 stored replay ideas reproduced exactly.
- **Answer: the edge does not stay above zero** — it was already below zero at normal costs.
  At 2x charges and fills 0.3% worse: walk-forward -1.09% per trade (edge over every stock -0.17% a day),
  replay ideas -1.81% per trade. Every 0.3% of worse fills costs about 0.6% per trade (buy and sell).
- Nothing changed in the brain, its rules or the trial. Full tables: `cost_stress.md`.
