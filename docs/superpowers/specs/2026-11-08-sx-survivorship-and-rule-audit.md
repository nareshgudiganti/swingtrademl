# SX5 / SX10: survivorship audit (Part A) and rule-determinism audit (Part B), 2026-11-08

Status: **audit findings and PROPOSED text for owner review. Nothing here is signed.** Read-only: SELECT on the local database, files read in the worktree `sector-prep-wt` (HEAD 53bb5fd). No model fitted, no holdout-period (2026-02-01 to 2026-08-15) outcome computed, no prod, no Kite, no `.env`. Every return or volatility figure below uses decision days 2022-09-15 to 2026-01-30 only.
Labels: VERIFIED = computed or read in this session; INFERRED = reasoned from verified facts; UNKNOWN = not knowable from local data; UNVERIFIED = general knowledge, not checked here, not to be used as a fact in any protocol.

---------------------------------------------------------------------------------------------------------------------------------

## PART A: SURVIVORSHIP AND UNIVERSE

### A1. How and when the 49 were chosen

| Question | Finding | Label |
|---|---|---|
| Is there a rule or a script that picked the 49? | No. The list never appears in any source file. `services/ingestion.set_watchlist(db, symbols)` takes a list given at call time and sets `instruments.is_watchlisted`; the only code default is `DEFAULT_WATCHLIST` = 5 names (RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK, `core/config.py:185`). The 49 symbols first appear in a source file on 2026-09-13 (`ml/sector_map.py`, commit 2bdb681) and as data in `stock_split_ev15.json` (`used_49`). | VERIFIED |
| When was it chosen? | Not recorded. Local `instruments` rows were created 2026-08-05 (the local database build date, not the selection date). Dated `watchlist_snapshots` exist only for 2026-10-05, 10-06, 10-09, 10-16 (49 names each). The 49 are the stocks with the longest local history (1,262 bars from 2021-08-06; the other 257 start 2021-08-13 or later), i.e. they were backfilled first. | VERIFIED |
| What kind of list is it? | Hand-maintained. The design note of 2026-09-25 (section 14) says the prod strategy symbol lists are "hand-maintained inside `strategy.symbols` and shaped like the NSE index lists (52 about NIFTY 50, 150 about NIFTY Midcap 150)" and "go stale at every NSE rebalance". The 49 are large caps. | VERIFIED (document) |
| Is it exactly the Nifty 50? | No, checked locally. TMPV (Tata Motors Passenger Vehicles, full history), TMCV (204 bars from 2025-11-12) and TRENT have 1,247 or 204 daily bars and are NOT on the watchlist; BEL, ETERNAL and JIOFIN exist in the instrument dump with **no candles at all**. The 49 hold names such as UPL, ASIANPAINT and HEROMOTOCO. Whether the Nifty 50 contained these names on any date is UNVERIFIED (no constituent data locally). | VERIFIED (local facts) / UNVERIFIED (index membership) |
| The memory note "user_stock_selection_criteria" (20-30 stocks, judgement) was not available to me. | The 49 therefore has no written, dated, rule-based selection criterion in the repo. | UNKNOWN |
| `brain/ten_day.collect` and `brain/five_day.collect` | Both read `Instrument.is_active AND is_watchlisted` at call time; `ten_day` refuses a run if the count is not the frozen 49 and writes "Survivor bias: the 49 stocks are today's watchlist, so stocks that were dropped or delisted are missing from the history" (`ten_day.py:76`). `ev15` split: universe = active, NSE, EQ, at least one daily candle, minus the 49 = 257; 306 = 49 + 257. | VERIFIED |

**The SX cohort (47) is the current watchlist applied to 2022-2026: CONFIRMED.** The 47 are the 49 minus ASIANPAINT and BHARTIARTL (no verified official sector index). The membership is a single static list; no date-dependent membership exists in any code path.

### A2. Delisted, merged, suspended or dropped names in the local data

| Check | Result (VERIFIED, local SELECT) |
|---|---|
| NSE equity instruments | 10,290 rows, **all `is_active = true`**, none has an expiry. The instrument table is a copy of today's dump: a name that left the exchange could not be in it. |
| Stocks with daily candles | 306 (49 watchlist, 257 others). Last candle: 303 end 2026-09-07 or 09-04 (HEG); **JSWINFRA and ICICIAMC end 2026-08-12** (710 and 159 bars; cause UNKNOWN: stale ingestion or suspension, not checked). Not one of the 306 stopped trading in 2021-2026 in a way that looks like a delisting. |
| Late starters among the 257 | 13 start after 2021-09-01, 6 after 2022-09-15 (recent listings such as ICICIAMC 2025-12-19, TMCV 2025-11-12). This is the opposite of survivorship (they enter the data when they list). |
| Internal gaps | 0 stocks with a gap of more than 10 calendar days between consecutive bars. |
| Symbol changes | Tata Motors appears under TMPV (full history) and TMCV (from 2025-11-12); there is no `TATAMOTORS` row. A renamed or demerged name exists only under its new symbol (INFERRED from the two series; the corporate event itself is UNVERIFIED). |
| Dropped from the dump | Unknowable locally. A stock delisted or merged before the 2026-08 dump is absent from `instruments`, and so is absent from the 306. **Earlier work found no delisted names; confirmed: none exist, and none could exist, in this data.** |

So the 306 are as survivor-biased as the 49: both groups are names alive and listed in August 2026.

### A3. Index membership 2021-2026

Local index candles: NIFTY 50 (from 2021-08-09), INDIA VIX, 15 sector indices (from 2021-09-13, NIFTY CHEMICALS only from 2025-11-24). **No constituent history exists locally** and no Nifty 100, Nifty Next 50 or large-cap index series. Therefore **no statement about which names entered or left the Nifty 50 or any large-cap index during 2021-2026 can be verified here.** Anything said from memory (for example that some of the 49 joined or left the Nifty 50 in 2022-2026, or that TRENT, TMPV, BEL, ETERNAL, JIOFIN are recent members absent from the 49) is **UNVERIFIED** and must not appear in a protocol as a fact. The only locally verified fact is that the 49 is not equal to any list of the 50 largest names one could build today (A1 row 5).

### A4. Realised development-period performance: the 47 against the other 257 (descriptive)

Decision days 2022-09-15 to 2026-01-30 (838 sessions; NIFTY 50 closed 17,877.40 to 25,320.65, +41.6%). Total return = last close / first close - 1 on the **raw stored closes**; annual volatility = standard deviation of daily returns x sqrt(252). Four of the 257 (ABFRL, ALLCARGO, BAJAJELEC, NMDC) have a one-day move above 35% that looks like an unadjusted corporate action; they stay in the table, which is why medians are the primary statistic.

| Group | Stocks | Median total return | Mean total return | Share below 0 | Share below -50% | Median annual vol | Mean annual vol |
|---|---|---|---|---|---|---|---|
| 47 mapped (SX cohort) | 47 | **+56.5%** | +62.6% | 8.5% | 0% | 23.2% | 24.3% |
| 49 watchlist | 49 | +56.5% | +62.5% | 10.2% | 0% | 23.1% | 24.1% |
| Other 257 (full window, 251 stocks) | 251 | **+57.1%** | +111.6% (inflated by outliers, max +2,263%) | 23.5% | 4.8% | 33.4% | 34.8% |

- Median annualised: watchlist 14.2% against 14.3% for the others. Permutation test of the median difference (49 v 251, 5,000 shuffles, seed 7, descriptive only): difference -0.5 points, p = 0.94. Mean difference -49 points, p = 0.10 (outlier driven). The watchlist's median rank among the 300 full-window stocks by total return is 152 of 300 (the middle).
- Equal-weight daily-rebalanced index of each group (single-day moves above 35% dropped, a rough guard against unadjusted bars): watchlist +64.0%, others +91.8% over the period; annualised volatility 12.3% against 16.2%.

**Reading (INFERRED, not a test of survivorship):**
1. **No sign that the 47 were chosen because they won in 2022-2026.** Their median return equals the median of the other 257, and the equal-weight index of the others did better. A winner-picking list would show a clear lead.
2. **There is a left-tail difference.** None of the 47 lost more than 50% (the worst was -44%); 4.8% of the others did, and their volatility is a third higher. That fits "large, established names", and also fits survivorship, and **the data cannot separate the two**: large size and survival come together, and the 257 are survivors too, so this comparison understates the survivorship bias (it compares survivors with survivors). A real test needs the names that died, which are not here.
3. Absolute levels (hit rates, base rates of "+2% in 5 days", model scores, excess over NIFTY) are therefore not representative of a point-in-time large-cap universe. The cohort also averages above NIFTY 50 (+56% median against +42%), but equal-weight against cap-weight is not like-for-like.
4. **Direction of bias for SX5/SX10 (INFERRED).** A universe made of names that are large in 2026 over-represents stocks that grew relative to their sector and the market since 2022 (a look-ahead on the universe). That favours strength and relative-strength features, which is what the three sector inputs measure. The paired difference C_56 minus A_53 is matched on rows, but it is **not guaranteed unbiased**: a gain could come from the sector inputs recognising stocks the universe was selected to contain. The drafts' sentence "The comparison C_56 minus A_53 is unaffected by this construction" is true only of the breadth inputs (identical in both arms), not of the universe, and should be narrowed (see A7).

### A5. Effect of the fixed cohort on the two breadth inputs

From `2026-11-06-sx-presigning-findings.md` section 1 (VERIFIED there; re-read, not recomputed): `breadth_pct_above_sma50` and `breadth_advance_pct` are computed over today's 49 on every date. Against the same inputs over all 306: Pearson 0.895 and 0.876, mean absolute difference 0.082 and 0.087; 49-stock breadth differs from the rest by more than random sampling (0.082 against 0.050); swapping 10 of 49 members for non-members gives correlation 0.979 and the same tercile on 91% of days. Both inputs sit in A_53 and C_56 identically and are absent from R_37, so breadth cannot create a C_56 minus A_53 difference by itself; it acts only through tree interactions. Production breadth also uses the current watchlist (no train/serve skew). Comparisons against R_37 are confounded and descriptive only (R_37 lacks 16 inputs including VIX and breadth).

### A6. Conclusions

**(i) What the evidence shows.** (a) The cohort is today's watchlist, hand-picked, undocumented, applied to 2022-2026: confirmed. (b) No delisted, merged, suspended or dropped name exists in the database or the 306, and none can exist, because the instrument dump is today's. (c) Index membership history is not available, so constituent changes cannot be assessed. (d) The development-period median return of the 47 equals that of the other 257 (+56.5% against +57.1%), so there is no sign of return-based winner selection; but the 47 have no deep losers and lower volatility, which survivorship would also produce, and the comparison group is itself survivors, so the survivorship bias is **not measured and cannot be measured from local data**. (e) Breadth: the fixed 49 correlates 0.88-0.90 with the 306-stock version; it is matched across A_53 and C_56.

**(ii) Is historical constituent reconstruction available? NO, not locally.** What is needed: dated constituent lists of at least the Nifty 50 (better Nifty 100 or 200 and the 15 sector indices) for every reconstitution since 2021, plus daily candles for every name that left the exchange (delisted, merged, suspended), with corporate-action adjustment. Possible sources, all UNVERIFIED as to content and terms: NSE Indices reconstitution circulars or index methodology files, a paid data vendor, or exchange bhavcopy archives. Licensing: `2026-10-29-nse-feed-licensing-inventory.md` section 2.4 records that **no production feed calls niftyindices.com**, that its terms forbid "systematic or automated data collection (including scraping ...)" and storing or redistributing content "without prior written permission of NSE"; the NSE archive files (N1-N2) are "NO-without-consent" for scripted collection; Kite (K1) gives candles only for instruments still in the dump and storing them is already UNCLEAR. So reconstruction would need written NSE consent or a licensed vendor feed, and that decision belongs to the owner. Until then, the universe limitation is permanent for this research.

**(iii) What a forward test would and would not fix.** A forward shadow test on the same cohort fixes: look-ahead on feature construction and on model fitting (every score is made before the outcome exists), data-snooping on the 2021-2026 prices (new days nobody has looked at), and the multiplicity problem for that candidate. It does **not** fix: the cohort itself (the 47 names stay fixed, so a name that gets dropped or delisted during the test has to be handled by a rule written in advance); the absolute level of returns, which stays specific to these large caps; coverage of other cap groups; or the survivor-only past that the model was trained on. Only a point-in-time universe (A6 ii) or a different, wider forward cohort removes the universe effect.

### A7. Proposed limitation text

**For both protocols (replaces "Limitation L1" and the survivor bullets in sections 9 and 11; ties to section 13 item 1 and 8 of the approval packages):**

> **Limitation U (universe and survivorship).** The conclusions of this protocol are limited to the **fixed historical cohort of 47 stocks**: today's watchlist (minus ASIANPAINT and BHARTIARTL) applied to 2022-09-15 to 2026-08-31. The list was hand-chosen, has no written selection rule, and contains only companies that are listed and active in 2026-08. Companies that were delisted, merged, suspended, renamed away or dropped from an index during 2021-2026 are not in the data, and point-in-time index membership is not available locally. The two market-breadth inputs are computed over the same 49 names. Results therefore **do not generalise** to the full market, to other cap groups (mid and small caps), to delisted or merged names, or to future changes in index constituents. Absolute levels (hit rates, returns, excess over NIFTY 50) are likely flattered relative to a universe that includes names that failed; the size of that effect is not measured. The paired comparison C_56 minus A_53 uses identical rows and identical breadth in both arms, but is not proved free of universe bias, because a universe of names that are large today favours stocks that kept strengthening, which is what sector-strength inputs describe. **A PASS would justify only a forward shadow test on the same cohort.** It would not justify any production change, any wider rollout, or any claim to customers. A forward test would remove look-ahead on the data and the repeated use of the same history for this candidate; it would not remove the fixed-cohort limitation.

**For the report header (every SX report, tables and plain-English summary, above the first number):**

> Cohort: 47 large stocks, today's list applied to the past (2022-09 to 2026-08). Survivors only: delisted, merged and dropped names are missing. Results apply to this cohort only. Not evidence about other stocks, other sizes of company, or the future market.

**Customer-facing statement (plain English, only if any SX result is ever mentioned outside the research record):**

> We tested this idea on 47 big, well-known Indian companies, using how they traded between 2022 and 2026. The list is the companies we follow today, so companies that fell out of the market or were merged away are not in the test, which can make past results look better than they really were. The test says nothing reliable about smaller companies, about other stocks, or about the future. Even a good result would only mean "worth watching live with no real money", not "this works".

Also insert, in the multiplicity paragraph of both protocols: "the forward shadow test, if ever proposed, must use a cohort rule fixed in advance for what happens when a cohort name is delisted, suspended or merged (count the idea as a loss at the last traded close, never drop it)." (PROPOSED.)

---------------------------------------------------------------------------------------------------------------------------------

## PART B: RULE DETERMINISM AUDIT

### B0. Method and headline

Files read: SX5 and SX10 protocol drafts (2026-11-05, with the 11-06 and 11-07 updates), SX5 and SX10 approval packages and blockers summary (2026-11-07), pre-signing findings S-1 to S-9 (2026-11-06), recipe FINAL DRAFT, `ml/sector_walkforward.py` (the harness), `td-protocol-v1` (`git show origin/main:...`), `brain/walk_forward.bootstrap_low`.

**Headline.**
1. The harness is deterministic and **it ends at the immutable per-arm per-fold JSON records.** Each record holds the per-day rows (`date`, `n_stocks`, `top_return`, `all_return`, `excess_vs_all`, `top_hit`, `all_hit`, `ic`, `random_return`, `net_*`). Every rule below can in principle be computed from those records. **But no code exists, anywhere in the repo, that computes the verdict:** no paired difference series D_t, no moving-block bootstrap with block 2h, no one-sided 2.5% bound, no Holm step, no fold-win count, no eligible-fold count, no outcome word. The only bootstrap in the repo (`brain/walk_forward.bootstrap_low`) is for a single series, block 15 default, always the 5th percentile, returns `None` below `max(5, 2 x block)` days. So every rule is "computable" and none is "computed by fixed code". The verdict code must be written, tested with synthetic data, hashed and signed BEFORE any model result (**MISSING item M1**).
2. The unsigned text mixes the old draft rules (R0-R5, block = horizon, 5th percentile, "if you accept") with the new S-1 to S-9 proposals; the packages say the S-rules "REPLACE" R2 but R1-R5 and the outcome words are not rewritten.
3. **The outcome word INCONCLUSIVE is currently unreachable** under the drafted rules (details B2, rule R3), while S-9 and the package text say INCONCLUSIVE is the expected outcome. A result whose interval straddles zero would be labelled "NO IMPROVEMENT" (a FAIL-like word). That is the main defect to fix (B3).
4. S-9 is not computed and it used 838 days; the counted series has fewer days.

### B1. Rule table

Key: quantity (a), source (b), formula and number (c), computing code (d), ambiguous words (e), remaining discretion (f), mechanical from records (g). Status: DETERMINISTIC / AMBIGUOUS / MISSING. "Code" refers to files in the worktree.

| Rule | (a) Quantity and (b) source | (c) Formula and threshold | (d) Code exists? | (e) Ambiguity | (f) Discretion | (g) From records | Status |
|---|---|---|---|---|---|---|---|
| **S-1 Unit** | daily value x_t = top-5 forward return minus mean forward return of all eligible stocks that day. Records: `daily[].excess_vs_all` | top 5 = highest `score`, ties broken by symbol order (`_day_metrics`: stable sort on symbol-sorted frame); days with fewer than 10 eligible stocks left out (`MIN_STOCKS=10`) | Yes, `sector_walkforward._day_metrics/evaluate_fold` | (1) "forward return": SX5 is the raw 5-session close-to-close return; **SX10 is also the raw 10-session close return (`forward_return`), not the +6%/-3.5% barrier trade result**, yet the SX10 draft section 6 says "10-day trade result" and td-v1 scores trades. (2) the tie rule is only in code, not in the text. (3) entry is the decision-day close, not the next open | none if fixed | Yes | **AMBIGUOUS** (SX10 quantity; tie rule) |
| **S-2 Paired series** | D_t = x_t(C_56) - x_t(A_53) | same day in both arms (guaranteed by `assert_identical_across_arms`); "pooled contiguous development test days of the folds counted" | **No** (join on date is a one-liner, not written) | "contiguous": days dropped for <10 stocks, fold boundaries; blocks run over the ordered retained days, not calendar days. "folds counted" depends on the burn-in rule being accepted | none if fixed | Yes | **AMBIGUOUS** |
| **S-3 Interval** | moving-block bootstrap of mean(D_t) | non-circular blocks; length 2h (10 for SX5, 20 for SX10); ceil(n/block) blocks per draw; 2,000 draws; seed 7; one-sided lower bound at 5% and 2.5% | **No** (`bootstrap_low` differs: single series, block 15, 5th percentile only) | (1) the random generator and draw order are unspecified (`random.Random(7)` + `randrange(n-block+1)` is the repo convention but is not written); (2) percentile index convention (`means[int(0.05*draws)]` is the repo one: for 2.5% index 50); (3) series shorter than the block; (4) how a one-sided bound is read off the bootstrap distribution | seed/method choices could be tried until one passes if not frozen | Yes | **AMBIGUOUS + code MISSING** |
| **S-4 Primary** | C_56 minus A_53 on daily top-5 excess over every eligible stock | one per horizon; everything else descriptive; "nothing is added after results" | n/a | SX10: see S-1 (which return). "descriptive" gives no outcome weight, but nothing says a reader may not cite them | low | Yes | **DETERMINISTIC** once S-1 is fixed |
| **S-5 Multiplicity** | Holm over {SX5, SX10} | smaller p must clear 2.5% one-sided, the other 5%; "A PASS needs R1 and R2 at that level" | **No** | (1) **no p-value is defined** (a bootstrap lower bound is not a p-value); (2) the two horizons are separate protocols that may run at different times, so "the smaller p" does not exist when one runs first; (3) R1 is a count rule and has no "level" | high: choosing which horizon gets 2.5% after seeing results | Yes | **AMBIGUOUS** |
| **S-6 Folds** | per-fold mean of D_t, eligible folds | eligible = at least 10 test days and 20 ideas | Partly (records have `n_days`, `n_ideas`) | **"ideas"**: in the harness `n_ideas` = 5 x days before any no-repeat rule, so 10 days already gives 50 and the "20 ideas" test can never bind; td-v1/fd-v1 mean finished ideas after the no-repeat rule, which the drafts say "is NOT computed". "Eligible fold" relative to the burn-in: folds 0-3 reported but excluded | none if fixed | Yes | **AMBIGUOUS** |
| **S-7 No peeking** | the freeze of block, draws, seed, bounds, folds, quantity | fixed at signing; analysis computed once from immutable records; holdout once; change needs new protocol id | holdout-once: Yes (registry, marker, STARTED/COMPLETED); analysis-once: **No** (nothing stops a re-computation, and the records are re-readable) | "computed once": a re-run of the analysis code on the same records is deterministic and harmless; the danger is changing the code. Needs: code hash in the signed text and the verdict file written once, exclusive create | medium | Yes | **AMBIGUOUS** (needs analysis-code hash and a write-once verdict file) |
| **S-8 Holdout** | mean D_t on the 133 holdout days | reported with S-3 interval; "sign-consistency check (R4)" | Records yes (kind "holdout"); analysis code No | R4 "same sign": sign of the mean of D_t over the 133 holdout days; zero? NaN? | low | Yes | **AMBIGUOUS** (zero and sign convention) |
| **S-9 Minimum detectable edge** | smallest true paired edge detectable with a stated power | "compute before approval on a synthetic series with the measured dependence (about 246 effective days for 5D, about 95 for 10D)" | **No. Marked NOT YET COMPUTED** | no power level, no alpha, no definition of "detectable"; the effective-day figures were measured on **838 days** (all eligible decision days), but the counted series has **642 days (34 folds) or fewer after burn-in**; scaled by 642/838 that is about 188 (5D) and about 73 (10D) (INFERRED, not computed) | n/a | n/a | **MISSING** |
| **Burn-in (B2)** | folds 4-33 only | R1 and R2 use folds 4-33; folds 0-3 reported but not counted | n/a | marked PROPOSED, "owner to accept". **Fold numbering is inconsistent**: the harness is 0-based (fold 0 to 33; fold 4 tests 2023-10-21 to 2023-11-17; fold 33 tests 2026-01-10 to 2026-01-31, a short 22-day window); the draft tables say "fold 1" to "fold 34" | high until accepted | Yes | **AMBIGUOUS** |
| **R0 Same rows** | row-list sha256 equal across arms | equal; harness refuses otherwise | Yes (`_check_arms`, `assert_identical_across_arms`) | none | none | Yes | **DETERMINISTIC** |
| **R1 Paired skill** | count of eligible folds where mean D_t > 0 | wins / eligible >= 60% (eligible = S-6; burn-in folds only) | **No** | (1) "beats": strict > 0 or >= 0 (a tie is possible only at 0.0); (2) rounding of 60% (18 of 30 passes; 17 of 29 fails); (3) "at that level" (S-5); (4) eligible folds under burn-in; (5) the whole rule is "borrowed" yet the drafts call it a consistency check, so its role in PASS is unclear | none if fixed | Yes | **AMBIGUOUS** |
| **R2 Paired lower bound** | S-3 lower bound of mean D_t | > 0 at the Holm level | **No** | still says "5th percentile ... block 5" in the draft body (R2 row and section 6 item 4), contradicted by S-3 in the packages | none if fixed | Yes | **AMBIGUOUS** (draft/package conflict) |
| **R3 Enough data** | eligible folds and ideas | at least 12 eligible folds and at least 100 finished best-5 ideas, else INCONCLUSIVE | **No** | "finished ideas" as in S-6. With every one of the 30 or 34 folds having 13-21 test days, R3 is always met, so **INCONCLUSIVE can never be produced** | none | Yes | **AMBIGUOUS (vacuous)** |
| **R4 Holdout agrees** | sign of mean D_t on the holdout | same sign as the development mean D_t | **No** | "same sign" of what; zero; development mean over which folds | low | Yes | **AMBIGUOUS** |
| **R5 No harm** | worst fold of C_56 vs A_53 (and R_37) | "shown; descriptive; no threshold" | **No** | "worst fold": by which metric (per-fold mean excess_vs_all?) and over which folds. Harmless if it has no weight, but a reader can use it after the fact | discretionary reading | Yes | **AMBIGUOUS**, but non-binding |
| **Outcome words** | IMPROVES / NO IMPROVEMENT / INCONCLUSIVE | IMPROVES = R0-R4; NO IMPROVEMENT = enough data and R1 or R2 not met; INCONCLUSIVE = R3 not met | **No** | Not the words in td-v1 (PASS/FAIL/INCONCLUSIVE). Case "R2 met, R1 not met" falls in NO IMPROVEMENT, which is a fail word for a case that is really mixed. INCONCLUSIVE is unreachable | medium | Yes | **AMBIGUOUS + MISSING** (replace, B3) |
| **Pass-rule inheritance** | "copied by reference" from fd-v1/td-v1 | fd-v1 section 6 and h05 rules | n/a | A rule by reference changes if that file changes; fd-v1 5-day text is not in the worktree I read | none if frozen | n/a | **AMBIGUOUS** (write the numbers into the signed text; td-v1 numbers verified: eligible fold >=10 days and >=20 ideas, >=12 folds and >=100 ideas, 60%, 2,000 draws, seed 7) |
| **Primary comparison** | C_56 - A_53 only | see S-4 | n/a | R_37 comparisons are descriptive | none | Yes | **DETERMINISTIC** |
| **After-cost result (SX5, A5)** | h05 `simulate_trade`, via injected `net_fn` | "diagnostic only; not a promotion criterion unless the owner signs it as one" | `net_fn` injected; h05 is an unaccepted draft | A5 is a yes/no still open; "unless you explicitly sign" leaves a door open after results | medium | Yes | **AMBIGUOUS** (must be a fixed NO) |
| **SX10 economics** | `ten_day.score_trade` | "reported beside the ranking result; the pass rule is ranking-based" | exists | none | low | Yes | **DETERMINISTIC** (diagnostic) |
| **Multiplicity count 11-12, 43%** | programme count | 1 - 0.95^11 | n/a | the count (Phase B 3 + lab 6 + td-v2 B1 + SX5 + SX10) is an illustration, not a rule | none | n/a | **DETERMINISTIC** (illustrative) |
| **Holdout window and its label wording** | decision days 2026-02-01 to 2026-08-14 (133 days, 6,118 rows) | replacement text of findings section 3 | harness constants | the old draft says "to 2026-08-15" (a Saturday); packages already say 08-14 | none after B3 of the blockers file | Yes | **DETERMINISTIC** once the replacement wording is adopted |
| **Eligible rows / hashes** | row-list, config, fold, recipe hashes | 45,935 (SX5), 45,700 (SX10), hashes in `final_hashes_v3.json` | Yes | A8 (HINDUNILVR fresh fetch) is still open and would change every hash | medium until A8 is closed | Yes | **DETERMINISTIC** after A8 |
| **Fit failure / skipped fold** | status of a fold | `skipped_not_enough_training_rows` or `skipped_no_test_rows` give metrics `None` | Yes (harness status) | no rule says whether a skipped fold is "ineligible" or "lost"; with 100+ train rows from fold 0 this is not expected | low | Yes | **MISSING** (add one line) |
| **Inputs of the verdict** | which records | all `dev` records of folds counted + the holdout records | n/a | not stated which run id and that only one `manifest.json` counts | medium | Yes | **MISSING** |

Defects not in the table but relevant: (1) `forward_return` is measured close-to-close from the decision-day close; fine as a ranking quantity but it is not an executable trade. (2) The text says "IMPROVES ... never activates anything" in one place and "A PASS" in another: one vocabulary is needed. (3) No rule says that the verdict file is written once and by signed code.

### B2. Do any rules depend on results (peeking)?

Findings, with the place where the drafts leave a choice open:

1. **Burn-in (B2)** is still "PROPOSED, owner to accept". If it stays open into the run, folds 0-3 could be included or dropped after seeing them. Must be signed as a fixed number.
2. **Block length.** The drafts' own body says block = horizon (5/10) and 5th percentile; the packages say 2h and Holm. Until the signed text removes the old wording, both exist. The findings add "report block = h, 3h and day-iid as sensitivity". Sensitivity results that disagree with the primary must not change the outcome (not stated now).
3. **Holm assignment.** Which horizon gets the 2.5% bound is decided by "the smaller p-value", i.e. by results.
4. **A5 economics** "yes or no" and "unless you explicitly sign it as one" leave the status of after-cost results open.
5. **R5 "shown"** and "worst fold" invite narrative use of an unthresholded number.
6. **HINDUNILVR (A8)** and **S-9 (A10)** are still open; both must be closed before training, since either changes inputs to the verdict.
7. **SX10 quantity** (raw 10-session return vs the barrier trade result) is not chosen in the text; if left, the choice could be made after the records exist.
8. **Wording "if you accept the burn-in rule"** inside R1 of the packages makes R1 conditional on a decision.
9. **Nothing in the protocols selects a model, a feature, a seed, a block or a hyper-parameter from results.** The recipe, seed 42, 100% of the purged training rows, `n_jobs=1` are fixed in the recipe hash; there is no early stopping, no tuning, no feature selection; the holdout is guarded by the registry. Those parts are clean.
10. **Dependence on results observed in earlier studies (not peeking within SX, but exposure):** the findings were produced from development labels only and the packages record that holdout prices were seen in earlier diagnostics (ledger exposure). The pre-signing investigation also used the earlier C_57; the C_56 decision was owner-made on a mathematical identity, not on a model result. No SX model has been fitted. Nothing in the rule thresholds was derived from an SX result.

### B3. Replacement text for every non-deterministic rule

All PROPOSED. Insert into section 6-8 of both protocol drafts and sections 7-8 of the packages (they must be identical for the shared rules). `h` = 5 (SX5) or 10 (SX10).

**S-1 (replace):** "The unit is the decision day. For each arm and day, among the stocks that day with a final score, take the five with the highest score (ties broken by ascending symbol, as in `sector_walkforward._day_metrics`). The daily value x_t is the mean of their `forward_return` minus the mean `forward_return` of all eligible stocks that day. `forward_return` is the close h trading sessions after the decision day divided by the decision-day close, minus 1, **for both horizons, including SX10** (the barrier label is used only to train the model; the +6% / -3.5% trade result is a diagnostic and never enters a pass/fail number). Days with fewer than 10 eligible stocks are left out of every arm. Pooled rows, picks or folds are never the unit of an interval."

**S-2 (replace):** "Let T be the list of decision days that (a) lie in the test windows of folds 4 to 33 (0-based fold index; test windows 2023-10-21 to 2026-01-31 in `default_folds`), (b) have at least 10 eligible stocks, in ascending date order. D_t = x_t(C_56) - x_t(A_53) for t in T. Blocks are runs of consecutive entries of T, not calendar days."

**S-3 (replace):** "Interval. Let n = |T|, b = 2h. One draw: for i in 1..ceil(n/b), pick a start s uniformly from 0..n-b with `random.Random(7)` (`rng.randrange(n - b + 1)`), append D[s:s+b]; the draw's value is the mean of all appended values (as in `walk_forward.bootstrap_low`). Use 2,000 draws from one generator seeded 7, no reseeding. Sort the 2,000 means m(1) <= ... <= m(2000). The one-sided lower bound at level alpha is m(floor(alpha x 2000) + 1), 1-based (alpha = 0.05 gives m(101), alpha = 0.025 gives m(51)). The one-sided upper bound at 5% is m(1900). If n < 2b, R2 is 'not computable' and the outcome is INCONCLUSIVE. The code is `sx_verdict.py` (to be written), signed by git hash; block 3h, block h and day-iid are computed by the same code as sensitivity and cannot change the outcome."

**S-5 (replace):** "Multiplicity. The family is {SX5, SX10}. p_H = (1 + number of bootstrap means <= 0) / 2001 for horizon H. If both horizons have been run: the horizon with the smaller p is tested at one-sided 2.5% (R2 uses the lower bound at alpha = 0.025), the other at 5%; equal p, SX5 first. **If only one horizon has a result when it is read, it is tested at 2.5%** (the stricter one) and that choice is not changed later. R1 is not adjusted; the level applies to R2 only."

**S-6 (replace):** "Fold k (0-based) is eligible if it has at least 10 test days with at least 10 eligible stocks and at least 20 top-5 picks (picks = 5 per such day, counted before any no-repeat rule; no no-repeat rule is applied in this historical test). Folds 0 to 3 are reported and never counted. A fold with status other than `ok` is ineligible."

**S-7 (add):** "The verdict is produced by `sx_verdict.py` at the signed commit, from the `manifest.json` and the `dev_*` and `holdout_*` records of ONE run id named in the signed text. Its output file is created with exclusive-create and records the code hash, the record hashes and the outcome word. A second computation is a protocol breach; a change to the code is a new protocol id."

**S-8 / R4 (replace):** "R4 is met if the mean of D_t over the holdout days (decision days 2026-02-01 to 2026-08-14 with >= 10 eligible stocks) is strictly greater than 0 and the development mean over T is strictly greater than 0. A mean of exactly 0 does not meet R4. The holdout interval is reported, with no pass/fail weight."

**S-9 (replace):** "Before signing, compute the minimum detectable paired edge MDE_H on synthetic series with |T| days (not 838), the measured lag-1 to lag-h day dependence, block 2h, alpha 0.05 one-sided, power 80% (stated numbers; seed 7; script and output hash in the signed package). MDE_H, in return points per day, is written into the signed text. It is used in the outcome rule below. A protocol whose MDE_H is larger than any edge the owner would call worth a forward test is declared 'underpowered' at signing, and the owner decides then whether to sign."

**Burn-in (replace):** "R1 and R2 use folds 4 to 33 (0-based; 30 folds, test windows 2023-10-21 to 2026-01-31). Folds 0 to 3 are reported with the label 'burn-in, not counted'. This is fixed at signing."

**R1 (replace):** "R1 is met if, among eligible counted folds E (S-6), the number of folds with mean(D_t over the fold's days) > 0 is at least ceil(0.6 x |E|). A fold mean of exactly 0 is not a win."

**R2 (replace):** "R2 is met if the one-sided lower bound of the mean of D_t at the level set in S-5 (0.025 or 0.05) is strictly above 0, computed as in S-3 on T."

**R3 (replace):** "R3 is met if |E| >= 12, picks over the folds in E >= 100, and |T| >= 2b. Otherwise the outcome is INCONCLUSIVE."

**R5 (replace):** "R5 is a table only: per-fold mean D_t for folds 4 to 33 with the minimum and maximum. It has no threshold, no weight in the outcome word and is not quoted as a reason to promote or reject."

**After-cost diagnostic (replace A5):** "The after-cost result (SX5: h05 `simulate_trade`; SX10: `ten_day.score_trade`) is reported in an appendix table. It has no weight in PASS, FAIL or INCONCLUSIVE, now or later, unless a new protocol id says otherwise."

**Pass rule inheritance (replace):** "Write the numbers into the signed text: eligible fold >= 10 test days and >= 20 picks; >= 12 eligible folds; 60%; 2,000 draws; seed 7; block 2h. The text does not defer to fd-protocol-v1, td-protocol-v1 or the h05 draft."

**Skipped fold / verdict input (add):** "A fold whose status is not `ok` in any arm is ineligible and listed. The verdict reads exactly one run id, named in the signed text."

**Vocabulary:** replace IMPROVES / NO IMPROVEMENT with **PASS / FAIL / INCONCLUSIVE**, as in td-protocol-v1.

### B4. The outcome rule: PASS, FAIL, INCONCLUSIVE (PROPOSED)

Definitions, evaluated mechanically in this order after R0 holds (if R0 fails, or any arm differs, or the harness refused, there is **no result**: the run is void, recorded as such, and the holdout rules of the registry apply):

1. **INCONCLUSIVE (data)** if R3 is not met, or any of: fewer than 12 eligible counted folds; fewer than 100 picks; |T| < 2h x 1; a mixed fold status that makes the folds counted differ from the signed 30.
2. **PASS** if R3 is met and R1 is met and R2 is met (at the S-5 level) and R4 is met.
3. **FAIL** if R3 is met, R2 is **not** met, and the one-sided 5% **upper** bound of the mean of D_t is **below MDE_H** (the data could have detected an edge of the size the protocol was powered for, and did not).
4. **INCONCLUSIVE (everything else)**: R2 not met and the upper bound is at or above MDE_H (the interval straddles the size of effect of interest: no edge cannot be told from a useful edge); or R2 met but R1 or R4 not met (the signals disagree); or the protocol was declared underpowered in S-9 and R2 is not met.

Because S-9 will almost certainly show an MDE larger than any realistic edge, **INCONCLUSIVE is the expected outcome**, and the signed text must say so.

**What happens after each outcome:**

- **PASS.** It proposes, and only proposes, a separately signed forward shadow test on the same 47-stock cohort (with Limitation U, the 43-46% programme-wide chance of a lucky pass, and the 133-day holdout also being in the register). No model is promoted, no production model, h05 lane, brain, scoring, order or customer screen changes. A PASS is not described as proof or as production performance.
- **FAIL.** The result is recorded with equal prominence in the register. No promotion, no re-run on the same holdout, no re-tuning, no variant of the recipe or the inputs under the same protocol id; a different idea is a new protocol id with this failure on record.
- **INCONCLUSIVE.** Recorded in the experiment register (`EXPOSURE-LEDGER`) with the numbers. **No model promotion. No re-run on the same holdout (the holdout is consumed). No re-tuning (hyper-parameters, seed, block, folds, inputs, rows). No extension of the sample, for example more days or a wider cohort, under the same protocol id; any extension is a new protocol id signed before its data are read.** The result is not read as "no effect" (L5). A forward shadow continuation can be proposed only in a separate protocol, separately signed by the owner, and the INCONCLUSIVE result carries no weight toward it.
- For all three: a null or negative result is stored with the same prominence as a PASS; the outcome word is not changed after it is produced; sensitivity results (block h and 3h, day-iid, secondary arms) are shown and cannot change it.

### B5. Blockers and open items

1. **No verdict code (M1).** `sx_verdict.py` (paired D_t, S-3 bootstrap with a written convention, Holm, R1-R4, outcome word, write-once output) must be written, tested on synthetic data, committed at a named hash, and named in the signed text. Blocks signing.
2. **S-9 not computed**, and the 838-day effective-sample figures do not apply to the counted days (642 before burn-in). MDE_H is an input to the FAIL rule. Blocks signing.
3. **Outcome vocabulary and the unreachable INCONCLUSIVE.** Replace as in B4. Blocks signing.
4. **Burn-in unaccepted, fold numbering inconsistent** (0-based harness against 1-based draft tables). Blocks signing; fix numbering to 0-based in the signed text.
5. **SX10 primary quantity** must be stated (raw 10-session return versus barrier trade result). Blocks signing for SX10.
6. **Holm** needs a p-value definition and a rule when only one horizon has run. Blocks signing.
7. **A5 and A8** (economics status; HINDUNILVR fetch) must be closed before training; A8 changes every hash.
8. **Limitation U** text (A7) replaces L1 and the "unaffected" sentence in L1 in both drafts and both packages.
9. Not blocking: the wording clean-up of "Superseded text" blocks; the two JSWINFRA/ICICIAMC stale series (irrelevant to the 47); a note that the forward test needs a delisting rule.

### B6. Files read and commands used

Files: `docs/superpowers/specs/2026-11-05-sx5-research-protocol-DRAFT.md`, `...sx10...`, `2026-11-06-sx-presigning-findings.md`, `2026-11-06-sx-model-recipe-FINAL-DRAFT.md`, `2026-11-07-sx5-approval-package.md`, `...sx10...` (diffed against SX5), `2026-11-07-sx-blockers-summary.md`, `origin/main:docs/superpowers/specs/2026-10-26-td-protocol-v1-PROPOSAL.md`, `docs/brain/evidence/stock_split/stock_split_ev15.md/.json`, `docs/brain/evidence/wider_universe_data_check_2026-10-12.md`, `docs/superpowers/specs/2026-09-25-factor-selection-and-experiments-design.md`, `docs/brain/SECTOR-FEATURES-SPEC.md`, `docs/superpowers/specs/2026-10-29-nse-feed-licensing-inventory.md` (in the main checkout, not in the worktree), `backend/src/swing_trade_ml/ml/sector_walkforward.py`, `ml/sector_research.py` (label function), `brain/walk_forward.py` (bootstrap), `brain/ten_day.py`, `brain/five_day.py`, `services/ingestion.py`. Database: SELECT only on `instruments`, `candles`, `watchlist_snapshots`, `candle_corrections` (docker `stml-postgres`, `SELECT 1` answered at once). Scratch script and data: `C:\Users\nares\AppData\Local\Temp\claude\8875f858af878994\7760ad1c-0af2-4782-9c69-ebf2dca1d1d5\scratchpad\an.py` and `perf.txt`.
