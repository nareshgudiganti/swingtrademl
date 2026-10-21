# Which modules really help? (ps1)

Protocol: `ps1-module-ablation-v1`. Diagnostic on development data, not proof (EXPOSURE-LEDGER.md).
25 replayed days, 2026-07-13 to 2026-08-14, model `swing_classifier_asof_20260710` (trained before these days).
With every module: 7600 stock-days judged, 561 ideas liked, 561 finished, average -0.99% per idea after costs.

| Module switched off | Decisions changed | Liked ideas added / dropped | Liked ideas | Avg / idea | Reading |
|---|---|---|---|---|---|
| M01 | 0 | 0 / 0 | 561 | -0.99% | adds nothing on these days (no decision changed) |
| M02 | 0 | 0 / 0 | 561 | -0.99% | adds nothing on these days (no decision changed) |
| M03 | 0 | 0 / 0 | 561 | -0.99% | adds nothing on these days (no decision changed) |
| M04 | 0 | 0 / 0 | 561 | -0.99% | adds nothing on these days (no decision changed) |
| M07 | 0 | 0 / 0 | 561 | -0.99% | safe fallback: no TRADE without the risk gate |
| M08 | 0 | 0 / 561 | 0 | n/a | makes every idea: without it the brain wants none |
| M10 | 0 | 0 / 0 | 561 | -0.99% | adds nothing on these days (no decision changed) |
| M11 | 0 | 0 / 0 | 561 | -0.99% | adds nothing on these days (no decision changed) |
| M13 | 0 | 0 / 0 | 561 | -0.99% | adds nothing on these days (no decision changed) |

## Not tested

| Module | Why |
|---|---|
| M05 | in shadow mode: it cannot change a decision |
| M06 | in shadow mode: it cannot change a decision |
| M09 | learns after the decision; it changes no word in the same run |
| M12 | in shadow mode: it cannot change a decision |
| M14 | reads today's account in a replay, not the account of the replayed day |
| M15 | follows holdings; a replay has no holdings from the past |

## Limits

- Development data only. 'Helps' here is not evidence; 'adds nothing' or 'hurts' is a real warning.
- In a replay the risk check uses today's account, so no replayed idea is ever approved; 'liked' counts the ideas the brain wanted before that check.
- One switch at a time: two modules that do the same job would each look useless.
- Only one as-of model exists locally, so only the days after its cutoff whose ideas have finished.

## What this means (plain English)

- Only M08 (the decision maker) changed which ideas the brain wanted. Turning off any other tested module
  changed nothing on these 25 days.
- Turning off the risk gate (M07) was safe: the brain then says TRADE to nothing.
- This does not prove the other modules are useless. Most of them work through the account (room, slots, risk)
  or through the market banner, and this replay cannot see the account as it was on each day. That needs ps12
  (replay with the day's own account), after which this test should be run again.
