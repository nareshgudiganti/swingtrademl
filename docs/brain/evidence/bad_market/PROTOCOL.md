# ps2 bad-market test — protocol `ps2-bad-market-v1`

Written and committed 2026-10-20, **before** the run. One run. No retuning afterwards.

## Question

In the worst markets in our data, did the brain's banner turn careful (DEFENSIVE / NO NEW TRADES) in time,
and how far did an account fall compared with the 15% halt?

## Windows (fixed rule, `brain/bad_market.py`)

- The 4 worst NIFTY falls over 20 trading days whose spans do not overlap, only where the market judge has
  at least 220 days of NIFTY history (its 200-day average). Peak = highest close in the span, trough = lowest
  close after it.
- The longest NIFTY fall: most trading days from a peak to its lowest close before a new high.
- Local data to 2026-09-07. The rule was previewed for its dates only (no results):
  2026-02-26→03-30 (−12.4%), 2024-09-26→10-25 (−7.8%), 2024-12-13→2025-01-13 (−6.8%),
  2025-02-04→03-04 (−7.0%), longest 2024-09-26→2025-03-04 (−15.8%, 109 days).

## Method

- Report period per window: 20 trading days before the peak to 30 after the trough.
- Banner: the market judge (M10) replayed each day on NIFTY, India VIX and watchlist breadth cut at that day.
  FII flows have no local history, so that rule is off (it only adds caution).
- One model per window, trained with cutoff the day before the report period; best 5 a day.
- One ₹10 lakh account (`portfolio_sim.simulate`, settled exits and costs, 15% halt, sector cap), run twice:
  with the replayed banner and with "always NORMAL".
- Ideas on careful days scored on their own: hit the stop (losses avoided) vs hit +8% (gains missed).

## Reading rule (fixed)

Per window: the first careful day and how much of the NIFTY fall had happened by then; worst account fall with
and without the banner vs 15%. Recorded as-is. Nothing in the brain, its rules or the trial is changed because
of the result (owner, 2026-10-20 plan section 5 point 4).

## Command

```
cd backend
python -m swing_trade_ml.brain.bad_market --upto 2026-09-07
```
