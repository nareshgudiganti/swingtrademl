# Point-in-time portfolio replay: brain vs simpler choices on the same rules (ps12)

Protocol: `ps12-pit-replay-v1`. **Diagnostic on development data, not proof** (EXPOSURE-LEDGER.md).
25 decision days, 2026-07-13 to 2026-08-14; the account runs 40 trading days (2026-07-13 to 2026-09-04) so the last buys can finish.
Start money ₹979,792. Model `swing_classifier_asof_20260710` (trained before these days). Buy level 0.60; slippage 5 bps a side plus charges.

| Strategy | Money at the end | Return | Worst fall from peak | Trades finished | Reached +8% first | Average per trade after costs | Days NO NEW TRADES / DEFENSIVE |
|---|---|---|---|---|---|---|---|
| Brain (full) | ₹972,755 | -0.7% | -1.3% | 16 | +25% | -0.97% | 0 / 25 |
| Rules only (flat model score) | ₹977,754 | -0.2% | -1.5% | 25 | +16% | -0.15% | 0 / 25 |
| Model only (score ≥ buy level) | ₹975,561 | -0.4% | -2.8% | 27 | +30% | -0.17% | - |
| Random, same count a day (200 draws: median, 5th to 95th) | ₹976,047 | -0.4% (-1.7% to +0.8%) | -1.0% (-0.5% to -1.8%) | 15.0 | +19% | -0.50% | 0 / 25 |
| NIFTY 50 bought and held | ₹969,706 | -1.0% | -3.7% | 1 | - | - | - |
| Cash | ₹979,792 | +0.0% | 0.0% | 0 | - | - | - |

## Why picks were not bought

- Brain (full): none skipped; still open at the end: 0; exits {'stop': 11, 'target': 4, 'timeout': 1}
- Rules only (flat model score): none skipped; still open at the end: 0; exits {'target': 4, 'stop': 11, 'timeout': 10}
- Model only (score ≥ buy level): {'no_free_slot': 460, 'already_held': 73, 'too_small_or_no_cash': 1}; still open at the end: 0; exits {'stop': 15, 'target': 8, 'timeout': 4}
- Modules dropped in the Brain (full) runs (their fallback answered): none
- Modules dropped in the Rules only (flat model score) runs (their fallback answered): M02 on 1 days, M14 on 1 days

## How to read it

- Every account has the same start money, days, next-open fills, exits (+8% / -4%, half at +5%, 15 days), costs and limits. Only the choice of stocks differs.
- 'Random' bought as many stocks a day as the brain did, with the brain's market banner, so it shows what the brain's timing and caution are worth without its stock choice.
- Development data: a better result here is not evidence that the brain is good; a worse one is a real warning.

## Limits

- One 25-day window, one market. Few trades, so the numbers are noisy.
- The replay account does not apply: the owner's pause switch, the avoid list, the cool-down after a stop, the per-strategy slot share, the share-price cap, cap tiers, the liquidity ceiling and the market-conditions ceiling (same as portfolio_sim).
- Brain EXIT / REDUCE words on holdings are recorded but not acted on: every account exits by the same fixed rules.
- Fills are at the next open with fixed slippage; a gap past the entry zone is still bought.
- The stock list is each day's watchlist snapshot (survivor bias); sectors are today's map.

## Reading by the fixed rule (PROTOCOL.md, written before the run)

- **Stock choice vs chance:** the brain's return of -0.7% sits inside the random accounts' 5th to 95th range (-1.7% to +0.8%), so its picks were **no better than chance** on these days. Its average per trade (-0.97%) was worse than the random median (-0.50%).
- **What the model adds (Brain minus Rules only):** -0.5% in return and -0.82% per trade. On these days the model's opinion **made results worse** than giving every stock the same flat score.
- **What the brain's rules add (Brain minus Model only):** -0.3% in return and -0.80% per trade, but with a smaller worst fall (-1.3% vs -2.8%) and fewer trades (16 vs 27).
- **Safety:** the worst fall was 1.3%, far from the 15% halt. The banner was DEFENSIVE on all 25 days (at most 2 buys a day, half size), with no NO NEW TRADES days.
- **Against the market:** the brain lost less than NIFTY bought and held (-0.7% vs -1.0%) but did worse than cash (0%).
- Run note: the rules-only runs dropped M02 on 1 day and M14 on 1 day (slow machine; their fallbacks answered). The brain runs dropped nothing.
- ps1 on this replay (`module_ablation --pit`) passed a smoke check on 2 days (base and M14; M14 changed no decision). It is not a result. The full run needs its own protocol.

Recorded as-is. Nothing in the brain, its settings or the trial changes because of it.
