# Cost stress test (ps3)

Protocol: `ps3-cost-stress-v1`. Diagnostic on development data, not proof (EXPOSURE-LEDGER.md).
Same picks, scored again with dearer trading. Normal costs = the settled strict rule.

## Walk-forward 2023-07-01 to 2025-01-31 (model's best 5 a day)

| Costs | Model ideas | Model avg / trade | Every stock avg | Edge / day | Edge low (5%) | Profit part |
|---|---|---|---|---|---|---|
| normal costs | 1980 | -0.20% | -0.02% | -0.19% | -0.51% | fail |
| 2x charges | 1980 | -0.48% | -0.29% | -0.19% | -0.51% | fail |
| fills 0.30% worse | 1980 | -0.81% | -0.64% | -0.18% | -0.48% | fail |
| 2x charges, fills 0.30% worse | 1980 | -1.09% | -0.91% | -0.17% | -0.48% | fail |

**Answer (walk-forward):** at 2x charges, fills 0.30% worse, the model's average result per trade does not stay above zero (-1.09%); its edge over every stock does not stay above zero (-0.17% a day).

## Stored replay ideas: `asof_replay_2026-07-13_2026-08-14.json`

561 ideas; 561 reproduced exactly at normal costs, 0 did not, 0 had no prices.

| Costs | Finished ideas | Hit +8% first | Avg / trade |
|---|---|---|---|
| normal costs | 561 | 19% | -0.99% |
| 2x charges | 561 | 19% | -1.26% |
| fills 0.30% worse | 561 | 18% | -1.54% |
| 2x charges, fills 0.30% worse | 561 | 18% | -1.81% |

**Answer (replay ideas):** at 2x charges, fills 0.30% worse, the average result per trade does not stay above zero (-1.81%).

## Limits

- Development data only: a pass here would not be evidence; a fail is a real warning.
- Under worse fills the target and stop follow the dearer buy price, as a live order would.
- 0.3% is a round number, not measured. ps4 (real fill quality) will give a measured one.
