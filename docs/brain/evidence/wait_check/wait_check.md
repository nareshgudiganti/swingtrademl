# Was WAIT / AVOID the right call? (ps11)

Protocol: `ps11-wait-check-v1`. Diagnostic on development data, not proof (EXPOSURE-LEDGER.md).
Whole-brain replay 2026-07-13 to 2026-08-14 (the ps1 'all modules' run). Every stock-day scored as if it had been bought: next-day open, +8% / -4%, half out at +5%, 15 days, after costs.

**Answer:** WAIT was the right call on average (buying anyway averaged -0.40% after costs). The ideas the brain wanted did no better than the ones it waited on.

| Brain's word | Stock-days | Finished | -4% first | +8% first | Ran out of time | Avg after costs | Would have lost money |
|---|---|---|---|---|---|---|---|
| wanted | 561 | 561 | 317 | 106 | 138 | -0.99% | 63% |
| WAIT | 7039 | 7039 | 3561 | 1532 | 1946 | -0.40% | 58% |
| AVOID | 0 | 0 | 0 | 0 | 0 | n/a | n/a |
| every stock-day | 7600 | 7600 | 3878 | 1638 | 2084 | -0.44% | 58% |

Good WAIT rate (buying would have lost money): **58%**. AVOID: never said in this replay, nothing to judge.

Day by day: on 13 of 25 days the wanted ideas did better than WAIT.

## Limits

- Development data only, one replay, one model: a good result is not evidence; a bad one is a real warning.
- 'Wanted' means a TRADE the replay's risk check lowered (it reads today's account), so these are the ideas the brain would have bought.
- Stock-days overlap: the same stock is judged again the next day, so they are not independent.
- Universe is today's watchlist (survivor bias).
