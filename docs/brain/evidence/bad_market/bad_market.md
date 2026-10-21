# Bad-market test (ps2)

Protocol: `ps2-bad-market-v1`. Diagnostic on development data, not proof (EXPOSURE-LEDGER.md). 49 watchlist stocks, NIFTY data to 2026-09-07.
Windows chosen by rule: the 4 worst 20-day NIFTY falls (not overlapping) and the longest NIFTY fall.

## Did the banner turn careful in time?

| Window | NIFTY fall | Banner at the peak | First careful day | Fall by then | First NO NEW TRADES | Careful falling days |
|---|---|---|---|---|---|---|
| 20-day fall: 2026-02-26 to 2026-03-30 (20 days) | -12.4% | NORMAL | 2026-03-04 (day 3) | -4.0% (32% of it) | never | 18 of 21 |
| 20-day fall: 2024-09-26 to 2024-10-25 (20 days) | -7.8% | NORMAL | 2024-10-17 (day 14) | -5.6% (72% of it) | never | 7 of 21 |
| 20-day fall: 2024-12-13 to 2025-01-13 (20 days) | -6.8% | NORMAL | 2024-12-17 (day 2) | -1.7% (26% of it) | never | 18 of 21 |
| 20-day fall: 2025-02-04 to 2025-03-04 (19 days) | -7.0% | DEFENSIVE | 2025-02-04 (day 0) | +0.0% (0% of it) | never | 20 of 20 |
| longest fall: 2024-09-26 to 2025-03-04 (109 days) | -15.8% | NORMAL | 2024-10-17 (day 14) | -5.6% (35% of it) | never | 91 of 110 |

## One ₹1,000,000 account, model's best 5 a day: with the banner vs always NORMAL

| Window | Worst fall (banner) | Worst fall (always NORMAL) | Return (banner) | Return (always NORMAL) | Trades (banner / NORMAL) | 15% halt reached (banner / NORMAL) |
|---|---|---|---|---|---|---|
| 2026-02-26 to 2026-03-30 | -5.6% | -9.6% | -2.0% | -1.2% | 70 / 71 | no / no |
| 2024-09-26 to 2024-10-25 | -5.3% | -7.1% | -3.6% | -4.8% | 66 / 69 | no / no |
| 2024-12-13 to 2025-01-13 | -5.9% | -10.2% | -4.5% | -8.1% | 70 / 70 | no / no |
| 2025-02-04 to 2025-03-04 | -4.4% | -8.9% | -1.1% | -2.5% | 79 / 85 | no / no |
| 2024-09-26 to 2025-03-04 | -8.9% | -16.4% | -5.6% | -14.9% | 154 / 149 | no / yes |

## Ideas on careful days, each scored on its own

| Window | Ideas | Hit the stop (losses avoided) | Hit +8% (gains missed) | Average result |
|---|---|---|---|---|
| 2026-02-26 to 2026-03-30 | 260 | 148 | 66 | -0.32% |
| 2024-09-26 to 2024-10-25 | 185 | 113 | 15 | -1.60% |
| 2024-12-13 to 2025-01-13 | 330 | 224 | 50 | -1.44% |
| 2025-02-04 to 2025-03-04 | 350 | 212 | 103 | -0.48% |
| 2024-09-26 to 2025-03-04 | 605 | 361 | 119 | -0.80% |

## Limits

- Development data only: a good result here is not evidence; a bad one is a real warning.
- FII flows have no local history before 28 Sep 2026, so the FII rule (which only adds caution) is off: the live banner can be more careful than this replay.
- The banner is the market judge (M10) alone. If M10 fails live, a backup judges instead; the 4 'bolder on bad data' bugs found in qa6 were fixed in PR #33.
- One model per window, trained before the report period starts, so it is older by the end.
- Universe is today's watchlist (survivor bias); shares are whole; ₹10 lakh account.
