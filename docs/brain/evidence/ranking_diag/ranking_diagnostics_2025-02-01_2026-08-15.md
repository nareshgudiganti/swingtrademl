# Score ranking diagnostics (development data, not a pass or fail)

Test days 2025-02-01 to 2026-08-15, 20 folds. Same rule and costs as wf-protocol-v1. Nothing was retrained or tuned. The confirmation sample is not used.
Every stock: 18565 finished stock-days, average -0.27%, hit 16%.

## 1. Do higher scores do better? (fifths of each day's stocks, 1 = best)
| Fifth | Ideas | Average | Hit target |
|---|---|---|---|
| 1 | 3790 | -0.23% | 17% |
| 2 | 3790 | -0.31% | 16% |
| 3 | 3784 | -0.22% | 16% |
| 4 | 3790 | -0.14% | 16% |
| 5 | 3411 | -0.50% | 13% |

## 2. By absolute score
| Score | Ideas | Folds | Average | Hit target | |
|---|---|---|---|---|---|
| 0.0-0.3 | 7334 | 20 | -0.21% | 14% |  |
| 0.3-0.4 | 3015 | 20 | -0.27% | 15% |  |
| 0.4-0.5 | 2590 | 20 | -0.44% | 14% |  |
| 0.5-0.6 | 2104 | 20 | -0.47% | 15% |  |
| 0.6-0.7 | 1571 | 20 | -0.40% | 19% |  |
| 0.7-0.8 | 1066 | 18 | -0.50% | 21% |  |
| 0.8-1.0 | 885 | 12 | 0.62% | 33% |  |

## 3. Does the score rank stocks on the same day?
Average daily rank correlation +0.011 over 379 days (lower bound -0.015 using 15-day blocks); positive on 52% of days. Zero means no ranking information.

## 4. Best 5, middle 5, worst 5 each day
Best -0.14% | middle -0.40% | worst -0.75% over 379 days.
Random picks of 5 on the same days averaged -0.28%; the model's best 5 averaged -0.14%. Random did at least as well in 5% of draws.

## 5. Each fold and market type
| Fold start | Market | Ideas | Rank corr | Best fifth | Worst fifth | Spread |
|---|---|---|---|---|---|---|
| 2025-02-01 | falling | 980 | +0.005 | -1.85% | -2.18% | 0.33% |
| 2025-03-01 | rising | 931 | -0.018 | 0.12% | 0.09% | 0.03% |
| 2025-03-29 | rising | 784 | +0.065 | 0.86% | 0.22% | 0.64% |
| 2025-04-26 | sideways | 931 | -0.026 | -0.26% | -0.24% | -0.01% |
| 2025-05-24 | sideways | 980 | +0.188 | 1.91% | 0.04% | 1.87% |
| 2025-06-21 | sideways | 980 | +0.117 | -1.33% | -2.50% | 1.17% |
| 2025-07-19 | sideways | 931 | +0.048 | 0.00% | -0.44% | 0.44% |
| 2025-08-16 | sideways | 929 | +0.058 | 0.27% | -0.31% | 0.58% |
| 2025-09-13 | sideways | 931 | -0.015 | 1.08% | 1.22% | -0.14% |
| 2025-10-11 | sideways | 882 | -0.020 | -0.21% | 0.12% | -0.33% |
| 2025-11-08 | sideways | 976 | -0.029 | -0.62% | -0.37% | -0.26% |
| 2025-12-06 | sideways | 931 | -0.128 | -0.43% | 1.11% | -1.54% |
| 2026-01-03 | sideways | 882 | +0.029 | -0.43% | -1.28% | 0.85% |
| 2026-01-31 | rising | 1029 | +0.002 | -1.45% | -2.35% | 0.90% |
| 2026-02-28 | falling | 882 | -0.020 | -1.90% | -1.74% | -0.17% |
| 2026-03-28 | rising | 833 | -0.063 | 1.00% | 1.36% | -0.36% |
| 2026-04-25 | sideways | 931 | -0.092 | -1.24% | -0.76% | -0.47% |
| 2026-05-23 | sideways | 931 | +0.053 | 0.09% | -0.94% | 1.03% |
| 2026-06-20 | sideways | 931 | +0.055 | 1.20% | 0.54% | 0.66% |
| 2026-07-18 | sideways | 980 | -0.006 | -0.99% | -0.93% | -0.06% |

| Market | Folds | Rank corr | Mean spread | Folds with positive spread |
|---|---|---|---|---|
| falling | 2 | -0.007 | 0.08% | 1 |
| rising | 4 | -0.004 | 0.30% | 3 |
| sideways | 14 | +0.017 | 0.27% | 7 |

## 6. Integrity checks
- Duplicate stock-days: 0.
- Average share of tied scores per day: 0.00%.
- Folds whose model cutoff is missing or not before the fold: none.
- Scored stock-days 18565, with a finished outcome 18565; the rest are too recent to have finished.
- Universe: 49 stocks. Survivorship: universe is today's watchlist: stocks that were later dropped are absent.
