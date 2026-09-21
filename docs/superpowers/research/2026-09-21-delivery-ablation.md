# Delivery-% features: ablation result

Date: 2026-09-21. Script: `scripts/delivery_ablation.py` (research only, writes nothing).

## Question
Does adding NSE delivery-% features to the barrier-label model (+8% before -4%,
15 trading days) improve walk-forward results?

## Setup
- Same rows, same 5 expanding walk-forward folds (purged by label window), same
  LightGBM recipe. Only the feature list differs.
- Rows restricted to those with delivery history (Sep 2022 - Aug 2026), so both
  variants see identical data. Universe: each tier's production symbol list.
- Four features, each a stock against its own history: today's delivery % vs its
  20-day norm; 5-day vs 60-day delivery %; delivered shares vs 20-day norm;
  delivery % on up days minus down days (5 days).
- Delivery for day t is public after close t, the same moment the candle is, so
  there is no look-ahead.

## Result (ROC AUC, mean of 5 folds)
| Tier | Baseline | With delivery |
|---|---|---|
| Large | 0.5313 | 0.5298 |
| Mid | 0.5624 | 0.5644 |
| Small | 0.5311 | 0.5267 |

Paired over 15 folds: mean AUC change **-0.0013**, improved in **5/15** folds,
fold-to-fold std 0.0056. Precision at the confidence threshold: mean -0.0005,
improved in 7/15. **No effect.**

## What this means
- Delivery % as designed adds nothing to the price model. Do not wire it in.
- Same conclusion as the 2026-09-15 ablation for sector, breadth and VIX: more
  context columns on top of price features do not lift this model.
- The data stays stored (cheap, dated); it may still serve as a human-readable
  explanation or a filter, but it is not a model input.

## Not tested
- Bulk/block deals and FII/DII: no history yet (NSE publishes only the latest
  day), so they cannot be tested until months of snapshots accumulate.
- Delivery inside a playbook (e.g. only breakouts) rather than pooled across all bars.

## Observation worth checking next (not a finding)
The hit rate at the confidence threshold is 0.21 (large), 0.35 (mid), 0.34 (small)
against a 2:1 payoff (+8% / -4%). Unresolved trades end near zero at the time stop,
so break-even is somewhere below one in three, not exactly one in three. Large caps
sit well under that mark. The label is a fixed +8%/-4% for every stock while the
strategy's stops and targets are volatility-based (ATR); a volatility-scaled label
would make label and trade agree, and lets a calm large cap and a jumpy small cap
face equally hard questions. Needs a simulated P&L before drawing any conclusion.
