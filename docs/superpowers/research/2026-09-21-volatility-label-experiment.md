# Volatility-scaled barrier label vs fixed +8% / -4%

Date: 2026-09-21. Script: `scripts/vol_label_experiment.py` (research only).

## Question
Would stops and targets set from each stock's own volatility (ATR) beat the fixed
+8% / -4%, judged by simulated profit per unit of risk after costs?

## Setup
- Same features, same 5 expanding walk-forward folds (purged by label window), same
  LightGBM recipe, same 2:1 payoff shape and 15-bar horizon. Only the barrier differs.
- `fixed_8_4`; `atr_2x` (stop = 2 x ATR%, clipped 2-8%); `atr_1.5x` (stop = 1.5 x ATR%,
  clipped 1.5-6%). Target is always 2 x stop.
- Metric: expectancy in R (profit / distance to stop) after estimated round-trip costs
  (~0.32% incl. slippage and the flat depository fee), for the model's top 5% of scores
  in each test fold. Unresolved trades exit at the horizon close.

## Result: R per trade after costs (model's top 5%)
| Tier | fixed 8/4 | atr 2x | atr 1.5x |
|---|---|---|---|
| Large | +0.224 | +0.030 | +0.209 |
| Mid | +0.283 | +0.115 | +0.164 |
| Small | +0.245 | +0.256 | +0.324 |

Folds with positive expectancy (of 5): fixed 4/4/4; atr_2x 2/2/2; atr_1.5x 4/2/4
(large/mid/small). Taking every row instead of the model's picks: about 0 (+0.04 large,
+0.02 mid, -0.03 small under the fixed label).

## Conclusions
1. **Volatility-scaled labels do not beat the fixed label.** Fixed wins on large and
   mid; atr_1.5x is ahead only on small, by a margin inside fold-to-fold noise. Keep
   +8% / -4%. Do not change the label or the strategy's exits.
2. **The model's selection is worth something.** Under the current setup its top 5% of
   picks earn +0.22 to +0.28 R per trade after costs, positive in 4 of 5 folds for every
   tier, while unfiltered entries earn about zero. This is the first simulated
   profit-and-loss evidence of edge, and it is consistent with the modest AUC.
3. This retires the earlier worry that the large-cap hit rate (0.21) was below
   break-even: unresolved trades close near zero, so the low hit rate on the target
   itself does not imply a loss.

## Caveats: this is not yet a backtest of the live system
- "Top 5% of the fold" uses the fold's own score distribution; live trading uses a
  fixed confidence threshold. Mild look-ahead in the cut-off choice.
- Entry at the signal-day close. Live entry is the next open, so gaps will cost more.
- No portfolio limits: no 10-position cap, sector cap, cash floor or regime-based
  deployable percentage, and trades on the same day are correlated.
- Only 5 folds over ~4 years; fold results vary a lot (individual folds are negative).
- Cost model is an estimate.

## Next
Replay the real system: fixed 0.60 confidence threshold, next-open entry, all portfolio
limits, through `services/backtest.py`, and compare with the SMA benchmark.
