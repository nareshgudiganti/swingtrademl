# Proposal: better model inputs (PROPOSAL, not approved, nothing built or run)

Written for the owner, 2026-11-02. Plain English first; detail below.

## Why

Three tests of the chart-based score have not shown ranking skill: the 5-day check, the 15-day trial evidence, and the
10-day history test (2023-07 to 2025-01: best-5 picks lost 0.34% per trade, worse than random 5 and NIFTY 50). The
15-day lab (S0 to S2, S0M to S2M) changes the question asked and the training set, but not what the model looks at. If
the inputs carry no signal, no new question will rescue them.

## The idea

Test whether adding *new kinds of information* helps the ranking, in one pre-registered experiment, separate from the
sealed trial, Phase B and the lab.

| Family | Examples | Data we already hold? | Risk |
|---|---|---|---|
| Market breadth | share of stocks above their 50-day average, advancers vs decliners | Yes (306 stocks local) | Low |
| Sector strength | each sector's recent return vs NIFTY | Yes | Low |
| Macro | NIFTY trend and volatility, USD/INR, crude, rates | Partly | Medium: timestamps must be checked |
| Company data (profit, debt) | S3 in the lab design | No verified timestamps | **Blocked** until reporting dates and licensing are verified (owner, 2026-10-29) |
| News | headlines and sentiment | No | Needs a source, licence and timestamps; no paid data (Q7) |

## Proposed first step (smallest, cheapest, no new data)

**Breadth plus sector strength only**, built from prices already in the database.

- Same stocks, same 15-day labels, same cost-free ranking verdict (R1 to R4) as the lab, so results are comparable.
- One candidate (call it B1) compared with the lab's S1 on identical folds, "better" bound as in R4.
- Features computed only from data available at the close of the decision day (no look-ahead; replay-checked).
- The 129 held-back stocks stay untouched. Label at most "NO WARNING (diagnostic)". Ranking only, no money figures.

## What it cannot do

It cannot prove a model works, cannot promote anything, and may well show nothing. A "no gain" result is a useful
answer: it would say price-derived inputs are exhausted and the next step is licensed company or news data, which needs
your decision on cost.

## Order and timing

1. Wait for the lab's S0/S1/S2 results (from 5 Dec). If S1/S2 already pass, B1 is a "can it do better" test.
2. If they fail, B1 is the next test, pre-registered before it runs: tag, evidence-plan amendment, one run, no retune.
3. Company data (S3) and news only after you approve the data source and cost.

## Decisions for the owner (nothing is built until you answer)

- [ ] P1 Write B1's pre-registration (tag + amendment) after the lab results arrive.
- [ ] P2 Keep company data and news parked until you approve a source and cost.
- [ ] P3 Macro features: allowed only if timestamps are verified first.
