# SX5 / SX10 pre-signing investigation: findings and proposed protocol text

Status: **findings for owner review. Nothing here is signed.** Read-only investigation on the local database (SELECT only); only
development-period labels were used (decision days up to 2026-01-31); no model was fitted; no holdout-period outcome was computed.
Labels: VERIFIED = computed or read in that session; INFERRED = reasoned from verified facts; UNKNOWN = not knowable from local data.
The investigation was run when the challenger was still called C_57 (53 + 4 sector inputs). It is now C_56 (53 + 3), see the
C_56 decision file; none of the findings below depends on the dropped input.

## Blockers for signing versus items that can wait

| # | Item | Finding | Blocks signing? | Action |
|---|---|---|---|---|
| 5 | Statistics | Row-level and day-iid intervals are far too narrow for repeated, overlapping top-5 picks. Synthetic: standard error 0.44-0.60 of the true value; false "lower bound above 0" 15-20% against a nominal 5%. The drafts used block = horizon and no multiplicity rule. | **Yes** | Put S-1 to S-9 in the signed text |
| 4 | Folds and training coverage | Folds 0-3 train on under one year. Folds 0-18 never trained through a NIFTY drawdown worse than -10%. Every training window is 81-94% bullish. | **Decision before results** | Choose the burn-in rule (below) before any result exists |
| 3 | Holdout label maturity | All holdout labels have matured, but the drafts' wording hides that the labels of the last decision days use bars after 2026-08-15 | **Text fix** | Replace the "Final holdout" bullet |
| 1 | Breadth survivorship | Two inputs use today's 49-stock watchlist for every past date | No | Add the caveat |
| 2 | Input-gap rows | One 5-week window (VIX rank undefined) plus 22 MFI rows; identical across arms; no concentration | No | Document only |

## 1. Historical market breadth (VERIFIED unless marked)
- Exactly two of the 53 existing inputs use breadth: `breadth_pct_above_sma50` and `breadth_advance_pct`. A_53 and C_56 carry both
  identically. R_37 carries neither (it also lacks `vix_change_5d`, `vix_percentile_rank` and 14 other inputs), so A_53 vs C_56 is
  matched for breadth, while any comparison against R_37 is not.
- The breadth universe is the 49 watchlist stocks (`instruments.is_watchlisted`) on every date; 257 of the 306 stocks with candles
  never enter breadth. All 49 have identical history (1,262 bars, 2021-08-06 to 2026-09-07), so 49 stocks count on every date after
  the 50-bar warm-up (first value 2021-10-18). A "stocks with a candle on that date" rule changes nothing (max difference 0.0).
- The real bias is index membership: today's 49 applied to 2021-2026. Historical membership is not in the database (UNKNOWN).
- Size: above_sma50 computed over the 49 vs all 306 stocks: Pearson 0.895, mean absolute difference 0.082; advance: 0.876 / 0.087.
  The 49 differ from the rest by more than random sampling does (0.082 vs 0.050). Swapping 10 of 49 members for non-members (100 draws,
  real prices): correlation 0.979, mean absolute difference 0.036, daily breadth tercile agrees on 91% of days.
- Breadth is one number per day, the same for every stock; by itself it cannot change which stocks rank first on a day, it acts only
  through tree interactions (INFERRED). Production breadth also uses the current watchlist, so this is about backtest realism, not
  train/serve skew.
- **Proposed text (section 4 caveat (a) of both drafts):** "Market breadth (`breadth_pct_above_sma50`, `breadth_advance_pct`) is
  computed over today's 49 watchlist stocks for every past date. It is present in A_53 and C_56 identically and absent from R_37.
  Point-in-time index membership is not available locally. The comparison C_56 minus A_53 is unaffected by this construction.
  Comparisons involving R_37 are confounded by it and by VIX, and are descriptive only."

## 2. The input-gap rows (VERIFIED)
- 1,103 rows (both horizons) were removed for all arms: 893 rows with both `volatility_percentile_rank` and `vix_percentile_rank`
  missing (2022-08-11 to about 09-08, all 47 stocks), 188 with `vix_percentile_rank` only (to 2022-09-14), 22 with `mfi_14` only
  (11 distinct months, 8 stocks).
- Cause: INDIA VIX starts 2021-09-13, so its 252-session rank is first valid on 2022-09-15, while stock warm-up ends about 2022-08-08.
  It is not "the first year": it is the 23 or so sessions between the two (23-29 rows per stock, 45 distinct dates). MFI is undefined
  when the 14-day negative money flow is zero (14 straight up days): 0.05% of rows.
- No concentration: sector shares of removed and retained rows are within 0.7 percentage points for every sector. The 1,081 rows are
  one 5-week rally (breadth 0.87 in the window against 0.60 for all development rows), so it removes one specific window.
- Label base rates (development period only): SX5 hit rate 25.1% in the gap rows vs 25.6% retained in the same quarter and 27.3% for
  all retained development rows; SX10 19.9% vs 18.7% and 19.9%. The gap rows are one window of about 23 correlated days; no
  significance test was run.
- 1,088 of the 1,103 rows are before the first test fold (2023-07-01); 15 MFI rows fall in test folds (15 of 30,116 test rows).
  The removal is identical across arms, so it cannot move a comparison.
- **Proposed text (section 3 gap bullet):** "The 1,103 rows are 1,081 rows of one window (2022-08-11 to 2022-09-14, all 47 stocks, no
  VIX rank yet) and 22 rows where MFI is undefined after 14 straight up days. They are removed for all arms. 1,088 are before the
  first test fold and 15 are in test folds. The removal does not enter any comparison."
  (After the C_56 change the counts of the sector-gap rows moved from 15 to 10; the input-gap counts did not change.)

## 3. Holdout label maturity (calendar facts only)
- 2026-08-15 is a Saturday. Holdout decision days run from 2026-02-01 to 2026-08-14: 133 days and 6,118 rows for both horizons.
- Every holdout label has matured. The latest bar any holdout label uses is 2026-08-21 (SX5) and 2026-08-28 (SX10); holdout rows whose
  label window uses bars after 2026-08-15: 230 (5 decision days) for SX5 and 460 (10 decision days) for SX10; no label uses a bar
  after the data end 2026-09-07.
- No feature uses a bar after its decision day. Mirror image at the start: 230 (SX5) / 460 (SX10) rows of the last development fold
  have label windows reaching into February 2026. They are purged from the holdout training set and scored as development test rows.
- The exposure ledger lists every period up to 2026-09-07 as development data (the holdout prices were used in earlier diagnostics),
  so the holdout is untouched only for the SX models and labels, not for the prices.
- **Proposed text (replace the "Final holdout" bullet in section 5):** "**Final holdout (SX models only).** Decision days 2026-02-01 to
  2026-08-14 (the last session on or before 2026-08-15), scored once. The labels of the last 5 (SX5) or 10 (SX10) of these decision
  days use bars dated up to 2026-08-21 (SX5) or 2026-08-28 (SX10). Every such bar exists, and no label uses a bar after 2026-09-07.
  No feature uses data after its decision day. Decisions after 2026-08-14 are not scored. Development decisions in the last 5 (SX5)
  or 10 (SX10) sessions before 2026-02-01 have labels reaching into February 2026. They are scored in the last development fold and
  removed from the holdout training set. These prices are not untouched in the exposure ledger; the period is a holdout only for the
  SX models."

## 4. Embargo, purging and training coverage (VERIFIED)
- Purged rows per fold: SX5 230-235, SX10 458-470, with 0 mismatches against an independent recount. The embargo of h sessions
  removes no further row (the purge already removes the last h decision days). The holdout fit applies the same rule against
  2026-02-01. Training rows grow from about 8,955 (fold 0) to about 38,478 (fold 33) for SX5 (SX10: 8,720 to 38,243).
- Folds 0-3 have under 12 months of training history (fold 0: 280 calendar days); one year first appears at fold 4, two years at
  fold 17. The first fold whose training window includes a -10% NIFTY drawdown is fold 19 (-15%: fold 22). Every training window is
  81-94% bullish (NIFTY 50-day average at or above its 200-day average).
- Overlapping labels: per-stock label autocorrelation at lag 1: 0.57 (SX5), 0.68 (SX10); same-day cross-stock correlation 0.157 /
  0.113; effective days of the daily mean return about 246 (5D) and about 95 (10D) of 838; about 7,860 (SX5) and 3,930 (SX10)
  independent-equivalent training rows out of about 39,000.
- Each fold's fit uses the first 80% of the purged rows in the earlier harness design (the recipe draft records the open question
  of 100% vs 80%).
- **Proposed text (section 5):** "The purge removes every training row whose label window ends on or after the test start. This equals
  the last h decision days; the embargo of h sessions removes no further row. The holdout fit uses the same rule against 2026-02-01.
  Folds 0-3 have under 12 months of training history, folds 0-18 never trained through a NIFTY drawdown worse than 10%, and every
  training window is at least 81% bullish. **[PROPOSED, owner to accept] R1 and R2 use folds 4-33; folds 0-3 are reported but
  excluded from the 60% count.** Per-fold intervals are not computed."
  Dropping the first four folds is a protocol revision, not a change to signed row eligibility; it must be decided before signing,
  because deciding it after results would be a choice made with outcomes in view.

## 5. Statistics (blocks signing)
Current state (VERIFIED): drafts use a block bootstrap over days with block 5 (SX5) and 10 (SX10), 2,000 draws, seed 7, 5th percentile;
td-v1 block 10, Phase B 15, five_day 21 and 5, h05 block_range 5. The multiple-testing paragraph is only an illustration; there is no
correction in the pass rule. Daily mean 5-day return autocorrelation: 0.79, 0.57, 0.34, 0.10 at lags 1-4, then about -0.15 at lags
5-7; for 10 days 0.88, 0.77, 0.65, 0.52, 0.38, 0.27, 0.16, 0.07, 0.

Synthetic demonstration (synthetic data only, 300 simulations per case; 642 days, 47 stocks, iid returns with a market factor, random
score, top 5 a day, true edge zero; phi = how much picks repeat day to day; SE ratio = reported SE divided by the real spread of the
mean, 1.0 is honest; false pass = share of lower bounds above 0, nominal 5%):

| Case | Method | SE ratio | False pass |
|---|---|---|---|
| 5D, phi 0 | rows / day-iid / block 5 / 10 / 15 | 1.03 / 0.98 / 0.97 / 0.96 / 0.96 | 4.3% / 4.3% / 5.3% / 5.3% / 5.7% |
| 5D, phi 0.9 | pick rows / day-iid | 0.59 / 0.57 | 14.7% / 16.3% |
| | block 5 / 10 / 15 | 0.86 / 0.92 / 0.94 | 9.7% / 7.0% / 7.7% |
| 5D paired A vs C | day-iid / block 5, 10, 15 | 0.60 / 0.83, 0.88, 0.89 | 15.3% / 9.3%, 8.7%, 8.0% |
| 10D, phi 0.9 | pick rows / day-iid | 0.47 / 0.44 | 19.3% / 20.0% |
| | block 10 / 20 / 30 | 0.83 / 0.87 / 0.88 | 8.0% / 7.3% / 8.0% |
| 10D paired | day-iid / block 10, 20, 30 | 0.53 / 0.87, 0.91, 0.92 | 15.7% / 7.0%, 7.0%, 6.7% |

Row-level or day-iid intervals are about 1.7x (5D) to 2.2x (10D) too narrow when picks repeat. Block = horizon removes most of that
(false pass 8-10%); block 2h gets to about 7%; block 3h adds little at a cost in power (small-edge power 0.88 naive vs 0.79 / 0.76 /
0.75 for blocks h / 2h / 3h at 5D; 0.87 vs 0.70 / 0.69 / 0.66 at 10D). Caveats: iid returns in time, assumed score persistence, the
paired rows use day-iid as the naive proxy, about +/-1.3 points of simulation noise on each rate. Arithmetic: rule R1 under a
fair-coin null: P(at least 21 of 34 folds) = 11.5% (neighbouring folds share data, so the real tail is fatter, R1 is a consistency
check, not a test); multiplicity: 1 - 0.95^11 = 43%, 1 - 0.95^12 = 46%, 1 - 0.95^2 = 9.75%.

**Recommended procedure (revision proposal for sections 6-8 of both drafts; signed eligibility rules untouched):**
- **S-1 Unit.** The decision day. The daily value is the top-5 forward return minus the every-eligible-stock mean. Pooled rows, picks
  or folds are never the unit of an interval. Days with fewer than 10 eligible stocks are left out, as now.
- **S-2 Paired series.** For the primary pair, D_t = (C_56 daily value minus A_53 daily value) on the same day, over the pooled
  contiguous development test days of the folds counted.
- **S-3 Interval.** Moving-block bootstrap of D_t: non-circular blocks of consecutive days; block length 2 x horizon (10 days for SX5,
  20 days for SX10); ceil(n / block) blocks per draw, 2,000 draws, seed 7; report the mean and the one-sided lower bounds at 5% and
  2.5%. Report block = horizon, block = 3 x horizon and day-iid as sensitivity only, never for pass/fail.
- **S-4 One primary comparison per horizon.** C_56 minus A_53 on daily top-5 excess over every eligible stock. Everything else is
  secondary or descriptive and carries no pass/fail weight: A-R, C-R, IC, hit rates, random-5, NIFTY, economics, splits, h05 shadow
  trade. Nothing is added after results.
- **S-5 Multiplicity.** The family is the two primaries (SX5, SX10). Use Holm: the smaller p-value must clear the 2.5% one-sided bound
  and the other the 5% bound. A PASS needs R1 and R2 at that level. The programme-wide count (11-12 comparisons on the same prices,
  about 43% chance of at least one lucky pass) is recorded in the register; it is the reason a PASS only proposes a forward shadow test.
  No programme-wide Bonferroni is applied.
- **S-6 Folds.** R1 uses per-fold means of D_t over eligible folds (at least 10 test days and 20 ideas). R1 is a consistency check;
  R2 carries the inference.
- **S-7 No peeking.** Block length, draws, seed, bounds, folds counted and the primary quantity are fixed at signing. The analysis is
  computed once from the immutable records. The holdout is scored once. No change to block, metric, fold set or threshold after any
  result. Any change needs a new protocol id, and the old result stays on record.
- **S-8 Holdout.** Report the paired difference on the 133 holdout days with the S-3 interval. It is a sign-consistency check (R4),
  not a second chance.
- **S-9 Minimum detectable edge.** Compute it before approval on a synthetic series with the measured dependence (about 246 effective
  days for 5D, about 95 for 10D). State that INCONCLUSIVE is the expected outcome for any realistic edge, especially 10D.

Why 2h: overlap dependence ends at lag h-1, but picks repeat and the daily series turns negative after lag h, so a block of exactly h
leaves residual dependence (SE ratio 0.83-0.86); 2h reaches 0.87-0.92 without the power cost of 3h, and it reuses the repo's existing
procedure (day blocks, seed 7, 2,000 draws), so only block length and bound level change.

Scripts and raw outputs of the investigation are not in the repository (they were scratch files); the numbers above are the record.
