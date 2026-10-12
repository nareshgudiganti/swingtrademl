# Do extra inputs or market mood fix the score? Two quick spikes (2026-10-12)

Throwaway scripts, local database, 49 watchlist stocks, 15 trading days, +8% target, -4% stop, entry at the
next open, real costs and slippage, no half-out. Models trained only on outcomes known by each cutoff.
Treat as direction, not proof: five test periods, overlapping 15-day outcomes, one model per period.

## 1. Extra inputs (best 5 stocks a day, average result per idea after costs)

The model already has about 52 inputs, including market breadth, VIX, strength against Nifty and sector.
Two untried inputs were added: delivery share (five years of history exist, lagged one session so no
look-ahead) and each stock's rank against the other stocks on the same day.

| Test period | Current inputs | + ranks | + delivery | + both | Every stock |
|---|---|---|---|---|---|
| Aug-Dec 2024 | -1.36% | -1.56% | -1.45% | -1.44% | -0.84% |
| Feb-Jun 2025 | +0.81% | +0.73% | +0.79% | +0.21% | -0.01% |
| Aug-Dec 2025 | +0.59% | +0.32% | +0.66% | +0.28% | +0.50% |
| Feb-Jun 2026 | -1.27% | -0.98% | -0.91% | -1.25% | -0.79% |
| May-Aug 2026 | -0.53% | -0.06% | -0.44% | -0.19% | -0.37% |
| **Mean** | **-0.35%** | **-0.31%** | **-0.27%** | **-0.48%** | **-0.30%** |

Mean AUC stays at 0.56 for every variant. No variant is clearly better than taking every stock, and none
beats it in more than 2 of 5 periods. These inputs do not lift the edge.

## 2. Does market mood explain when it pays? (taking every stock)

| Stocks above their 50-day average on the decision day | Days | Average result per idea | Reached target |
|---|---|---|---|
| under 30% | 69 | +0.04% | 24% |
| 30-50% | 141 | -0.24% | 17% |
| 50-70% | 195 | -0.25% | 15% |
| over 70% | 142 | -0.54% | 13% |

Buying everything did worst when most of the market looked strong and best after a broad sell-off. That is
the opposite of "only buy when the market looks healthy". Same direction at +5%/-4% and 10d +5%/-3%.
Cautions: 69 days in the best bucket, overlapping outcomes, and one market cycle.

## What it means

- The settings (target, stop, horizon) and these inputs are not the missing piece. The score has little
  skill on these stocks and this data.
- Gating by a healthy market is not supported by this data. Plan items #3 and #4 in EXPERT-TRADER-PLAN.md
  (strong stocks only in a falling market; wait for an "all clear") need a replay test before they are built.
- Taking any stock at +8%/-4% over 15 days loses a little after costs on average (-0.30% across these
  periods). The rule only pays when the picks are clearly better than that, and they are not yet.
