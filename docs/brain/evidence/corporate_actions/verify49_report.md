# Corporate-action verification: the three mechanical steps among the 49 primary stocks

Date of work: 2026-11-03. Status: **preliminary evidence, read-only. It changes no price, no signed result, no sealed record and no model.**
Source of this file: the verification run's final report, copied here so it is durable. Scripts and raw output are in this folder
(`verify49_scripts/`). Labels: V = verified (external record, or our database/code read), I = inferred, U = unknown.
Local database only (SELECT), no production call, no `.env` read.

## Bottom line

1. **No additional price correction is required for RELIANCE or ITC.** Their stored pre-ex history is already adjusted by
   Zerodha with the company's published cost-of-acquisition (COA) factor. RELIANCE matches to the paisa: our
   2 x 1354.40 = 2708.80 against RIL's own notice 95.32% x 2841.85 = 2708.85. The leftover step is the gap between the
   COA split and the market's price discovery. It is not a missed or wrong adjustment. Adding our own factor would duplicate
   Zerodha's.
2. **HINDUNILVR is stored UNADJUSTED** (stored / actual = 1.000). Only about 1.6% of its -5.0% step is mechanical (special
   session 2422.00 against previous close 2462.20); the other -3.4% is real trading. Whether Zerodha has since applied its COA
   adjustment is U: it needs a fresh historical fetch.
3. **Measured performance impact is negligible.** Excluding every affected stock-day moves the every-stock 5D average per trade
   on the fd_v1 / wf_v1 sample (-0.2738%) by at most 0.005 pp (variant C), and by at most 0.04 pp in any window. Worst-case
   bound on model picks is 0.03 pp (best-5) and 0.012 pp (buy rule), against published -0.37% / -0.42%. No pass/fail verdict can
   flip (I). This is a scorer-level sensitivity, not a model rerun.
4. **No other flagged row among the 49 is mechanical.**
5. **Positions held across an ex-date are not handled anywhere in code.** No local position, tracked idea or signal touched any
   of the three dates. Production around 2025-12-05 is U.

## 1. Per-event findings

### RELIANCE, ex-date 2023-07-20 (Jio Financial Services demerger, 1:1)

| Item | Finding | Label |
|---|---|---|
| Official source | Record date 20 Jul 2023, one JFS share per RIL share. RIL apportionment notice: RIL 95.32% / JFS 4.68%, worked example "95.32% of 2841.85 = 2708.85" on the 19 Jul close (rilstaticasset.akamaized.net .../SEIntimation_ApportionmentofCost_0.pdf). NSE circular on the special session, 17 Jul 2023 (nsearchives.nseindia.com .../PR_cc_17072023.pdf). NSE index treatment page. | V (search snippets; PDFs not opened) |
| Exchange reference price | JFS discovered at 261.85. RIL ex-price 2580.00 (= 2841.85 - 261.85). | Partial (secondary report, consistent with arithmetic) |
| Stored prices (x2 to undo the Oct 2024 bonus) | 07-19 close 2708.8. 07-20 open 2580.0, high 2631.0, low 2580.0, close 2619.8. 07-21 close 2538.8. | V (DB) |
| Adjustment status | Stored 07-19 / actual 2841.85 = 0.9532 = the COA factor. Market factor would be 0.9079. Stored 07-20 open equals the exchange ex-price, so post-ex bars are unscaled. **ADJUSTED with COA factor 0.9532.** | V |
| Why a step remains | Open gap 2580/2708.8 - 1 = -4.75% = market factor / COA factor (0.9079/0.9532). Close step -3.3% = that gap plus +1.6% real intraday. | V (arithmetic) |
| More correction needed? | **No.** Moving to a market-value adjustment would replace Zerodha's factor, not add to it. That would be an owner decision and is not required. | V |

### ITC, ex-date 2025-01-06 (ITC Hotels demerger, 1 ITC Hotels per 10 ITC)

| Item | Finding | Label |
|---|---|---|
| Official source | Record-date filing 18 Dec 2024 (nsearchives.nseindia.com/corporate/ITC_18122024125536_SE_Recorddate_.pdf). COA letter 28 Jan 2025: ITC 86.49% / ITC Hotels 13.51% (.../ITC_28012025004206_SE_COA_.pdf). | V (search; PDFs not opened) |
| Exchange reference price | Special session discovered 455.60. Previous close about 482 to 482.60. The 6 Jan close was 442.50 (-2.75%) per Business Standard. | Partial (secondary; outlets differ by a few rupees) |
| Stored prices | 01-02 403.3. 01-03 close 397.2. 01-06 open 434.4, close 422.05. 01-07 close 420.6. | V (DB) |
| Adjustment status | Stored 01-03 / actual about 482 = 0.824 = COA 0.8649 x 0.953. Post-ex bars are also about 0.954 of actual. Pre/post ratio equals the COA factor exactly. **ADJUSTED with COA factor 0.8649, plus an unexplained uniform factor of about 0.954 on all ITC bars.** | V numbers; cause U |
| About the 0.954 factor | Numerically close to ITC dividends since Jan 2025 (7.85 + 6.5 + 8 = Rs 22.35 on a 482 base). RELIANCE shows no dividend adjustment, so this is unconfirmed. A uniform scale does not change returns. | U |
| Why a step remains | Open gap +9.4% = market factor 0.944 / COA 0.8649 = +9.2%. The rest is -2.8% real intraday. | V (arithmetic) |
| More correction needed? | **No** for the demerger. Open item (not a demerger): confirm the 0.954 factor with one fresh fetch (low priority, levels only). | I |

### HINDUNILVR, ex-date 2025-12-05 (Kwality Wall's demerger, 1:1)

| Item | Finding | Label |
|---|---|---|
| Official source | HUL record-date notice (hul.co.in .../intimation-of-record-date-21-11-2025.pdf). HUL investor page lists a cost-apportionment filing dated 13 Dec 2025. Scheme effective 1 Dec 2025. COA reported as 98.09% HUL / 1.91% KWIL from secondary news only; the 30 Dec 2025 KWIL COA letter was not read. | Partial |
| Exchange reference price | Special session 2422.00 against previous close 2462.20 (Samco). Another outlet gives a BSE close of 2464.10. Our DB reproduces 2462.20 and the 2286.70 low exactly. | Partial |
| Stored prices | 12-04 close 2462.2. 12-05 open 2422.0 (special-session price), low 2286.7, close 2338.6. 12-08 close 2314.0. | V (DB) |
| Adjustment status | Stored 12-04 / actual 2462.20 = 1.000. A COA adjustment would show about 2415. **UNADJUSTED.** | V |
| Mechanical part of the -5.0% | The -1.63% open gap (KWIL worth about Rs 40) is mechanical. The other -3.4% is real trading. | I |
| More correction needed? | **No** from our side. Whether Zerodha has applied its COA adjustment since is U (needs a fresh fetch; see the HINDUNILVR check in this folder if present). Most likely cause: ingestion never refetches old bars (section 6). | U |

## 2. Affected windows, if a correction were ever needed

- Feature windows (`ml/features.py`): returns over 1/5/10/20 bars; sma/ema 10/20/50/200; vol20; bollinger 20; `high_52w_dist` and
  `days_since_52w_*` over 252 bars.
- Label windows: 5/10/15 bars forward (`five_day_train.py`, embargo equal to the horizon). `selection_lab.py` and `ten_day.py`
  windows were not read in that run (U).

| Event | Feature rows (252 / 200 / 50 / 20) | Label rows (5 / 10 / 15) | Trade-path rows (30-day hold) |
|---|---|---|---|
| RELIANCE 2023-07-20 | 252 / 200 / 50 / 20 | 5 / 10 / 15 | part of 6 in the fd window |
| ITC 2025-01-06 | 252 / 200 / 50 / 20 | 5 / 10 / 15 | part of those 6 |
| HINDUNILVR 2025-12-05 | 187 (data ends 2026-09-08) / 187 / 50 / 20 | 5 / 10 / 15 | 8 (horizon_grid B window, hold variant) |

For the 49: 691 feature stock-days (1.12% of 61,838) and 45 label rows.

## 3. Other flagged rows among the 49

- Split/bonus: NESTLEIND, BAJFINANCE, DRREDDY, RELIANCE bonus and TATASTEEL show no price step and no inverse volume step (V).
- Genuine moves (V): the Hindenburg-period ADANIENT/ADANIPORTS rows, the 2024-06-04 election-day rows (ADANIENT, ADANIPORTS, NTPC,
  ONGC) and INDUSINDBK 2025-03-11.
- Still UNVERIFIED but not mechanical (I): ADANIPORTS 2023-02-01 and 2023-12-05; ADANIENT 2023-03-03, 2023-05-22, 2023-12-05 and
  2024-11-21; INDUSINDBK 2024-10-25. Volume 1.9x to 25x the median, no price-ratio signature with an inverse volume step. They
  coincide with known Adani-group news and INDUSINDBK results. They were not looked up individually and are not treated as errors.
  The 355 unverified moves elsewhere are untouched.

## 4. Sensitivity of historical results (nothing overwritten)

What could not be rerun: fd_v1, wf_v1, horizon_grid, walk_forward and h05 retrain a model per fold; the result JSON files hold no
per-trade rows; td_v1 and the 15D lab were not in that checkout. What was done instead: the real trade scorer
(`five_day.outcomes_prod`) was run on every stock-day of the 49 for each result window with no model exit, so absolute levels differ
from published and only the deltas matter. The affected stock-days were then excluded in three steps: A = trades spanning the
ex-date; B = A plus the 5 label rows; C = B plus the 252 feature rows. Figures are the average net per trade, percent.

| Window | Variant | Original | Excl A | Excl B | Excl C |
|---|---|---|---|---|---|
| fd_v1 / wf_v1 2023-07 to 2025-01 (RELIANCE, ITC) | 30-day hold | -0.2738 (19404 trades) | -0.2748 | -0.2751 | -0.2787 (19122) |
| same | day-5 close | -0.3433 | -0.3443 | -0.3446 | -0.3473 |
| horizon_grid A 2025-02 to 06 | hold / day5 | -0.4255 / -0.3788 | same | same | -0.4211 / -0.3737 |
| horizon_grid B 2025-08 to 12 (HUL) | hold / day5 | +0.0845 / -0.0866 | +0.0899 / -0.0833 | same | +0.0989 / -0.0724 |
| horizon_grid C 2026-05 to 08 | hold / day5 | -0.4831 / -0.4384 | same | same | -0.4605 / -0.4262 |
| walk_forward / portfolio_replay 2025-10 to 2026-08 | hold / day5 | -0.3654 / -0.3734 | -0.3632 / -0.3720 | same | -0.3516 / -0.3632 |
| scoreboard s1 2025-02 to 2026-08 | hold / day5 | -0.3912 / -0.3860 | -0.3900 / -0.3852 | same | -0.3823 / -0.3786 |
| scoreboard s2 2026-07-13 to 09-08 | hold / day5 | -0.6485 / -0.4354 | same | same | -0.6108 / -0.4139 |

Published for comparison: fd_v1 every stock -0.36%, best 5 -0.37%, buy rule -0.42%, daily edge -0.011% (lower bound -0.155%).
wf_v1 verdict "No evidence of skill and no profit". Largest shift anywhere: 0.04 pp. Bound for model picks (I): only 10 affected
rows exist among 19,404 (A+B), so about 1 in 1,980 best-5 trades is hit by chance and at most 10; worst swing per trade about 6 pp
(-4.35 to +1.63); so at most 0.03 pp on best-5 and 0.012 pp on the 4,884 buy-rule trades, against a 0.37 pp distance to break-even.
Fold counts "7 of 21" and "10 of 21" could change only in the 2 folds containing these dates (not recomputable, U). No corrected
series run was made because no correction is required. h05, td_v1 and the 15D lab were not rerun; the same rows and dates apply.

## 5. Simulated trade accounting

Nothing in the code handles corporate actions (V). Grepped: `services/execution.py`, `tester_paper.py`, `brokers/paper.py`,
`services/portfolio.py`, `exit_policy.py`, `brain/portfolio_sim.py`, `replay_scoring.py`, `pit_replay.py`. Only `services/split_check.py`
(report-only) and M01 quality (excuses recorded split days) know about them.

- Entry price and quantity are fixed at entry (`services/execution.py:122`, `:147`).
- Value is (price - entry_price) x quantity (`services/portfolio.py:118`, `:78`; `execution.py:473`).
- Prices come from the cached live quote or the paper broker's `_reference_price` (`brokers/paper.py:66-96`); after the ex-date that
  is the raw exchange price.
- Exit: `execution.py:1489` (`price <= position.stop_loss`) fires STOP_LOSS_HIT on the raw drop; `trail_stop` (`execution.py:1286`)
  works from the pre-ex highest price.
- What a held position would show (I, from code; no live case exists): a false loss equal to the demerged value (roughly 9% for a
  RELIANCE-type, 5.6% for an ITC-type, 1.6% for a HUL-type event); a stop-out if that loss crosses the stop; no credit for the new
  company's shares (no entitlement row, no new position).
- Backtests and replays read stored daily candles only, so they inherit whatever scale those candles have: COA-adjusted for RELIANCE
  and ITC, unadjusted for HUL.
- Local DB: positions start 2026-08-05, brain_track 2026-09-07, signals 2026-08-05; nothing on ITC, RELIANCE or HINDUNILVR near any of
  the three dates (V, local only). Production around 2025-12-05 is U.

## 6. Nightly ingestion risk for future splits and demergers

Yes (code V, consequence I). `services/ingestion.py:362-376`: incremental runs use `from_date = max(from_date, latest_stored - 1 day)`
and upsert with ON CONFLICT (line 325; changes logged to `candle_corrections`). When Kite restates old bars after a split or bonus, or
later once COA arrives for a demerger, only the last day plus new bars are refetched, so older bars keep the old scale and a raw step
appears at the ex-date. That likely explains why HUL (Dec 2025, ingested nightly) is unadjusted while RELIANCE and ITC (loaded in a
backfill after the event) are adjusted.

Detector sketch (now being built as a separate change): (a) refetch about 10 trading days of overlap and compare stored against
fetched closes; a difference over 0.5% means Kite restated history, so queue a full refetch of that stock and log it; (b) flag a
close-to-close move of 7% or more with volume below 3x the 20-day median, and a price ratio within 1% of 1/2, 1/3, 1/4, 1/5, 1/10 or
2/3 with an inverse volume step; (c) cross-check `upcoming_events` and Kite instrument-list changes. Each hit gets a manual
single-announcement lookup, never a bulk NSE scrape (`docs/superpowers/specs/2026-10-29-nse-feed-licensing-inventory.md`).

## Owner decisions recorded (2026-11-03)

No bulk price migration and no model retraining is justified by the current evidence. Preserve raw historical records, signed tests,
the sealed trial and active models. Nothing here was deployed or applied to production data.
