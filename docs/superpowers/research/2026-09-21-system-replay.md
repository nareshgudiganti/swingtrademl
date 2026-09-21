# Point-in-time replay of the real strategy

Date: 2026-09-21. Script: `scripts/system_replay.py` (research only).

## What was run
For each of 5 expanding walk-forward windows (about 8 months each, May 2023 - Aug 2026):
train LightGBM only on data that ended before the window (label-purged), then run the
production `ml_swing` strategy code through the production backtester on Rs 10 lakh:
0.60 confidence threshold (+0.10 in a NIFTY downtrend), liquidity / volatility /
falling-knife filters, +8% / -4% levels, exit on confidence <= 0.35, account-size limits,
risk-based sizing, half-out at first target, time stop, drawdown brake, full cost model.
Only the model and feature lookup are swapped; nothing else is changed.
Stress case: 35 bps slippage instead of 5 (standing in for next-open gaps).
Benchmarks: the SMA-crossover strategy through the same backtester, and holding NIFTY.

## Result (mean return per ~8-month window on Rs 10 lakh)
| Tier | ML strategy | ML, worse fills | SMA benchmark | Hold NIFTY |
|---|---|---|---|---|
| Large | -0.4% (2/5 windows up) | -1.0% (0/5) | +0.2% | +6.0% |
| Mid | -0.2% (3/5) | -1.3% (0/5) | +0.1% | +6.4% |
| Small | -0.1% (2/5) | -1.4% (0/5) | -0.0% | +6.1% |

Trades: 579 / 979 / 1,091. Win rate 40-45%. Worst drawdown 2.3-2.6% (4% stressed).

## Conclusion
**In a realistic replay the strategy has no edge after costs.** Roughly break-even at
best; negative once fills are a little worse. It does not beat the simple SMA
benchmark and captures almost none of NIFTY's +6% per window. It is safe (small
drawdowns) but it does not make money. Not ready for real capital.

## Why this disagrees with the earlier +0.22 R "top 5%" result
That test simply followed each label barrier and cut the top 5% of scores using each
fold's own score distribution (mild look-ahead). The real strategy differs in ways
that plausibly matter:
1. **Half is sold at the first target and the rest is trailed** (decided 14 Sep), while
   the model was scored on "+8% before -4%". A different trade from the one it predicts.
2. Exit whenever confidence falls to 0.35 and a 30-day time stop.
3. A fixed 0.60 threshold picks a different, larger set of trades than the best 5%.
4. Position caps: at Rs 10 lakh each trade risks about 0.4% of the account, so even a
   real 0.2 R edge would move the account very little; a zero edge shows as zero.
5. Costs and slippage in the full model.

None of these is yet isolated. Next: replay with (a) scale-out off, (b) signal-exit
off, (c) higher thresholds, one at a time, to find which change destroys the edge.

## Caveats
Survivorship: the symbol lists are today's production watchlists. Entry fills at the
signal-day close in the base case. Sector cap, cash floor and regime-based deployable
percentage are not replayed. 5 windows only.
