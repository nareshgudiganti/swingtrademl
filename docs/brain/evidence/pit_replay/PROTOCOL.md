# ps12 point-in-time replay — protocol `ps12-pit-replay-v1`

Written and committed 2026-10-21, **before** the run. One run. No retuning afterwards.
Diagnostic on development data (EXPOSURE-LEDGER.md), not proof.

## Question

If the brain had run every evening on an account that really existed (the money, positions and limits it
would have had on that day), would its picks have done better than simpler ways of choosing, on exactly the
same rules?

## Why a new replay

In an ordinary replay the risk gate (M07) and the modules that read the account (M03, M14, M15) see
today's account, so no replayed idea is ever approved (ps1 found only M08 changing anything; M07 could not
be judged). Here each replayed day the brain reads a **simulated account as it stood at that day's close**
(`brain/pit_replay.py`):

- `PointInTimeReader`: an ordinary replay reader (every price read bounded by the day), whose holdings,
  account numbers and owner-pause answers come from the simulated account.
- `PointInTimeRiskGate`: M07's own candidates, market-mode policy and batch allocator; only the account and
  the entry check come from the simulated account. Used only in this replay (a registry passed in).
- No frozen file is changed (tests/trial_freeze.json); nothing is written to the database; live runs use
  the same code as before (tests in `tests/test_brain_pit_replay.py`).

## Fixed settings

| Setting | Value | Why |
|---|---|---|
| Decision days | every trading day 2026-07-13 to 2026-08-14 (25 days) | the only window after the one local as-of model's cutoff whose trades finish inside local data; the same days as ps1, so the two read together |
| Model | `swing_classifier_asof_20260710` (cutoff 2026-07-10) | trained before every decision day |
| Account days | decision days, then 15 more trading days (to about 2026-09-04) with no new buys | so the last buys can finish; local prices end 2026-09-07 |
| Start money | ₹9,79,792 | the paper trial's clean starting balance (2026-09-28) |
| Fill rule | the brain decides after the close; a TRADE is bought at the **next trading day's open**, slipped, with charges (`services/costs.py`) | no look-ahead: the decision day's close is never used as a fill |
| Exits | +8% target, -4% stop, half out at +5%, 15 trading days; a bar touching the stop counts as the stop | the settled rule (`portfolio_sim`) |
| Limits | capital ladder (`services/limits.py`) by the account's value that day, one stock per sector / 25% sector cap, 15% drawdown halt, at most 5 new buys a day (2 on DEFENSIVE, none on NO NEW TRADES) | `portfolio_sim`, same for every variant |
| Sizing | 1% of the account at risk at the 4% stop, capped by the ladder, half size on DEFENSIVE | `portfolio_sim` |
| Buy level | `ML_MIN_CONFIDENCE` as configured for the run (0.60, the code default, in this worktree) | the level the as-of replay reader already uses |
| Random draws | 200 accounts, seeds 12 to 211 | evidence-defs-v1 (200 seeded portfolio runs) |

## Variants (one account each, identical days, money, fills, exits, costs and limits)

1. **Brain**: the whole brain on the point-in-time account. Its TRADE words, in the order the risk gate
   approved them, are the buys; its banner is the day's market mode.
2. **Rules only**: the same brain, but the model's score is replaced by one flat score equal to the buy
   level for every stock with a price, through the reader the fallback already uses. Every stock is
   "liked" equally, so only the brain's rules, modifiers (sector, setup, events, portfolio), banner and
   risk gate choose; ties fall to alphabetical order. (Literally "no model opinion" is not a useful
   variant: `opinions.py` never lets a stock with no model opinion be bought, so it would be cash.)
3. **Model only**: every stock the as-of model scores at or above the buy level, best first; no banner, no
   brain rules, only the account limits above.
4. **Random, same count a day**: each day as many random stocks as the brain bought, from that day's same
   stock list, with the brain's banner; 200 seeded accounts (median and 5th to 95th percentile).
5. **NIFTY 50 bought and held**: the whole money at the first fill day's open, sold at the last account
   day's close, one round trip of the stock cost model.
6. **Cash**: 0%.

Reported per variant: money at the end, return, worst fall from peak, trades finished, share that reached
+8% first, average result per trade after costs, days the banner said NO NEW TRADES / DEFENSIVE.

## Reading rule (fixed now)

- **Stock choice vs chance:** the brain's return against the random accounts. Above the 95th percentile:
  "better than chance on these days". Inside: "no better than chance". Below the 5th: "worse than chance"
  (a warning). Development data, so the first is never called evidence.
- **What the model adds:** Brain minus Rules only (return and average per trade).
- **What the brain's rules add:** Brain minus Model only.
- **Safety:** the brain's worst fall against the 15% halt; the count of NO NEW TRADES / DEFENSIVE days.
- **Against the market:** Brain against NIFTY and cash, stated plainly.
- Recorded as-is. Nothing in the brain, its settings or the trial is changed because of it.

## Module on/off on this replay (ps1 follow-up)

`python -m swing_trade_ml.brain.module_ablation ... --pit` runs ps1 on this replay, where M07, M14 and
M15 become judgeable. This run does only a **smoke check** (base and M14 on 2 days) that it works; the
full ps1-on-replay needs about 9 variants x 25 days x 2.5 min, about 9 hours, and its own protocol and
ledger row before it is run.

## Commands

```
cd backend
python -m swing_trade_ml.brain.pit_replay --from 2026-07-13 --to 2026-08-14 \
    --asof-model swing_classifier_asof_20260710
```

Resumable: each brain day is saved in `checkpoint_<variant>.json` as it finishes; the same command picks
up where it stopped.

## Known limits (stated before the run)

- One window of 25 days, one market; few trades, so noisy.
- Not simulated: the owner's pause switch, the avoid list, the cool-down after a stop, the per-strategy slot
  share, the share-price cap, cap tiers, the liquidity ceiling and the market-conditions ceiling (as in
  portfolio_sim). The brain's EXIT / REDUCE words on holdings are recorded, not acted on.
- Fills at the next open with fixed slippage; a gap past the entry zone is still bought.
- Stock list: each day's watchlist snapshot (survivor bias); sector map is today's.
- The local `.env` of the main checkout overrides some settings (for example the buy level); by the
  secrets rule it was not read, so this run uses the code defaults. A rerun with other settings is a new run.
