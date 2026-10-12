# Experiment A: does buying after weakness help? (2026-10-12)

Pre-registered before running. Same for every strategy: 49 watchlist stocks, 15 trading days, +8% target,
-4% stop, entry at the next open, real costs and slippage, no half-out, the same five test periods
(Aug 2024 to Aug 2026, 438 trading days). Models trained only on outcomes known by each period's cutoff.
Everything is decided from information known at the decision day's close.

- **Market weak:** fewer than 30% of the 49 stocks above their 50-day average. The 30% line came from the
  earlier look at the same data, so it is NOT out-of-sample. 20% and 40% are shown as a check.
- **Stock weak:** in the bottom 20% of the 49 by 20-day return that day.
- **A** the model's best 5 stocks a day. **B** every stock on market-weak days. **C** every weak stock, any
  day. **D** both weak. **B5** A on market-weak days only. **E** every stock.

## Pooled result (after costs)

| Strategy | Ideas | Days | Reached target | Average per idea (+/- error) | Avg win | Avg loss |
|---|---|---|---|---|---|---|
| A model best 5 | 2,250 | 438 | 20% | -0.25% (0.35) | +5.19% | -3.95% |
| B market weak | 3,038 | 62 | 23% | -0.09% (0.80) | +5.77% | -4.08% |
| C stock weak | 3,942 | 438 | 16% | -0.30% (0.37) | +4.61% | -3.69% |
| D both weak | 558 | 62 | 21% | -0.60% (1.04) | +6.13% | -3.96% |
| B5 model best 5, market weak | 310 | 62 | 29% | +0.28% (0.79) | +6.25% | -4.20% |
| E every stock | 21,462 | 438 | 16% | -0.27% (0.29) | +4.61% | -3.77% |

The error is a standard error on 15-day blocks, because neighbouring days share outcomes.

## By period (average per idea)

| Strategy | Aug-Dec 24 | Feb-Jun 25 | Aug-Dec 25 | Feb-Jun 26 | May-Aug 26 |
|---|---|---|---|---|---|
| A | -1.36% | +0.81% | +0.59% | -1.26% | -0.74% |
| B | -1.13% | +1.74% | +2.62% | +0.38% | no weak days |
| C | -1.28% | +0.06% | +0.39% | -0.41% | -0.25% |
| D | -2.12% | +0.54% | +2.94% | +0.77% | no weak days |
| B5 | -1.41% | +2.43% | +1.97% | +1.79% | no weak days |
| E | -0.84% | -0.01% | +0.50% | -0.79% | -0.37% |

## Checks

- Threshold: below 20% breadth +0.70% (34 days, error 1.12), below 30% -0.09%, below 40% -0.23%.
  Weaker market, better result, in order. Still inside the error.
- Time split: market-weak days vs every stock were -0.42% vs -0.37% in the first half and +0.55% vs -0.17%
  in the second. The advantage appears only in the second half.

## Reading

- Nothing is proven. B and B5 are above the baseline in most periods that had weak days, but every gap is
  smaller than its error, there are only 62 weak days, and the first period goes the other way.
- Stock-level weakness (C) adds nothing. Combining both (D) is worse, so the two effects do not stack.
- The model's selection (A) is no better than taking every stock (E).
- Not enough to change any rule. Expert-plan items #3 and #4 stay unbuilt and nothing is switched on.
- The limit is days, not stocks: weak-market days are the sample. A wider stock universe adds ideas per day,
  not more market regimes. More history, or waiting for live days, is what would settle this.
