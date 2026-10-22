# Phase B candidate settings (`phase-b-settings`)

Status: **LOCKED 2026-10-22 by the owner, before any Phase B result exists.** Tag `phase-b-settings` goes on
the commit that adds this file. The runner (`backend/src/swing_trade_ml/brain/phase_b.py`,
`swingtrade brain phase-b`) refuses a real run without this tag, `evidence-defs-v1`, `evidence-defs-v2`
and the locked stock split, and never before 2026-11-09 (IST).

Builds on: the evidence plan (`2026-10-15-evidence-and-pilot-plan.md`, sections 2-4, `evidence-defs-v1`)
and Amendment 1 (`2026-10-21-evidence-plan-amendment-1.md`, `evidence-defs-v2`). Where those fix a rule,
they win; this file only fills in what they left open. Tracker: Atlas → Evidence plan → ev18.

Changing anything below after the tag is a new settings version with its own tag, recorded here, and only
before that candidate's one run. A candidate that has run is never re-run with new settings.

## Owner decisions (2026-10-22)

| # | Question | Decision |
|---|---|---|
| 1 | B1 "trade only when score ≥ 0.80": which stocks on a day? | **Every stock scoring 0.80 or more.** The portfolio replay still buys at most 5 a day |
| 2 | B2 (train on 49 + 128 = 177, score the 49): daily rule | **The model's best 5 a day**, as wf-protocol-v1. So B2's model-only comparison is B2 itself (said in its report) |
| 3 | Which score, for all three | **The raw per-window model score** (the trained model of each test window), as every earlier test. Not the brain's M06 chance |
| 4 | Lock the settings with their own tag | **Yes: `phase-b-settings`**, required by the runner |

## Defaults kept as the runner has them (not changed by the owner)

| Topic | Setting |
|---|---|
| Rules-only comparison | Whole brain replayed with M06 removed and no as-of model, counting the ideas it liked (as ps1). Labelled with its known limit: the replay sees today's account, not each past day's |
| Guard reading | All conditions at all times: date ≥ 9 Nov 2026 IST **and** all three tags **and** the split hash |
| "Survives Phase B" | Point averages, gated at ≥ 30 trading days with ideas; an INCONCLUSIVE reject-set check counts as "does not survive" (cautious) |
| Ranges on net return / confidence | FAIL only when the whole range is below zero; a range that spans zero is INCONCLUSIVE |
| Portfolio replay | ₹10 lakh start; random-5 accounts use seeds 7-206 (200 runs); every day treated as NORMAL market mode |
| NIFTY buy and hold | Uses the stock cost model (`services/costs.py` has no ETF rates) |
| Risk-matched random | May draw the idea's own stock; volatility = standard deviation of the last 20 daily returns, split into thirds across the day's list |
| Breadth (B3) | Share of the 49 above their 50-day average, counting only stocks with a bar that day; weak = under 30% |
| Coverage | Ideas per calendar week |
| "No stock > 20% of profit" | Uses summed returns (every trade is the same size) |
| A2 comparisons | No pass rule of their own; reported without a label |
| Exposure ledger | The runner writes the candidate's row **before** results; the row is also its one-run lock. If a run crashes after the row, the owner edits the ledger before that candidate can run |
| Windows | Development data 2025-02-01 to 2026-08-15; the last window ends 2026-08-14 (08-15 is a Saturday) |
| Reject set | Stocks with fewer than 220 bars of history cannot be scored; the report's data-quality section says how many |

## Still open (not a setting)

- Owner confirmation of the 7th pass rule (consistency), plan section 4. Needed before the first run.
