# Data-integrity audit: which past results could be touched by bad or corrected stock bars (2026-10-29)

Read-only audit. No code, config, test, protocol or evidence file was changed. Nothing was re-run. Prod was
not touched. The local Docker database (port 5433) answered a test query within the 20-second limit, so
some read-only queries were run in read-only transactions (section 6). Nothing was written to it.

Three labels are used throughout and are never mixed:

- **OBSERVED FAILURE**: a result that came out badly (for example "wf-v1 failed"). It says what happened,
  not why.
- **CONFIRMED DEFECT**: a fault proven by code, a test, or a query (for example "breadth counted missing
  stocks as bearish").
- **UNTESTED EXPLANATION**: a possible reason for a failure that nobody has checked (for example "bad bars
  caused wf-v1 to fail"). It stays untested until a new, separately labelled diagnostic checks it.

## Summary

**The main finding is that no stock bar has ever been recorded as corrected.** The correction log
(`candle_corrections`) has existed since 2026-10-05 (`fcaef35`). The local database has not taken in a
single new bar since then: the arrivals table is empty and the last bar is 2026-09-09. So the log's 0 rows
mean "nothing was checked", not "nothing was wrong". Before 2026-10-05 any overwrite of a bar was silent and
cannot be traced now. No past result can be tied to a "previously corrected bar", because no record shows
one.

What the record does show is a different set of problems: bars that look **never corrected** (suspected
splits or demergers left unadjusted), and fixes to **calculations** (breadth input, signal horizon,
portfolio cash, decision safety). Most of them sit outside the 49 watchlist stocks.

| Question | Answer |
|---|---|
| Corrected bars on record | **0** (local). Logging started 2026-10-05; local data was never re-ingested after that. Prod: not checked (off limits). |
| Suspected unadjusted price jumps (corporate-action signature) | 17 one-day moves larger than 25% or overnight gaps larger than 20% in 14 stocks. None of the suspect ones are among the 49. |
| Problems among the 49 watchlist stocks | Only ADANIENT (2023-02-01/02) and INDUSINDBK (2025-03-11). Both were checked against press reports and are real events. BAJAJFINSV's 2022 split and bonus are already adjusted in our data. |
| Results built on the 49 stocks only (wf-v1, fd-v1, ranking diag, S1, horizon grids, replays, ps checks) | **NOT AFFECTED by any known bar problem.** Some UNKNOWN remains, because there is no list of company events to prove it. |
| wf-v1 and the breadth fix (made after wf-v1) | **Shown NOT AFFECTED.** ps3 retrained every fold model after the fix (2026-10-20) and got the frozen result exactly: 1,980 ideas, −0.204% per trade. |
| Results that included the wider stocks | **AFFECTED (exposure confirmed, size of effect unknown):** the 2026-09-15 barrier models and the 2026-10-08/09 calibrated models (mid 150, small 104). Their training lists contain all 13 flagged stocks. None was re-run. |
| Could wf-v1 FAIL, fd-v1 FAIL or "the score does not rank" flip on a re-run? | No known bar problem touches their data. Saying bad bars caused them is an **UNTESTED EXPLANATION**, and there is no evidence for it. Sealed or locked runs are not re-run to change a verdict. |
| Biggest open gap for the 177-stock experiment | 4 of the 128 extra training stocks carry suspect jumps: SANOFI, BAJAJELEC, VEDL, ABFRL. There is no company-event history, so "adjusted" can never be claimed. Follow review item b6: remove the affected windows and label the result "unadjusted; affected windows removed". |

## 1. Every known data problem

Dates are IST trading days. "Found" is the first written record; "Fixed" is the commit that fixed it.

### 1a. Price bars

| # | Problem | Stocks and dates | Found | Fixed | Label |
|---|---|---|---|---|---|
| D1 | One-day moves whose low volume and lack of rebound suggest the price basis changed (a split, demerger or ex-date not adjusted). The audit's own words: "a signature, not proof". | ALLCARGO 2025-11-12 (−60%, gap −64%, volume 1.0×); TRIVENI 2026-07-22 (−42%, 0.25×); SANOFI 2024-06-13 (−28%, gap −30%, 0.7×); SCI 2023-03-31 (+30%, 0.39×); BAJAJELEC 2023-09-14 (+39%, 0.12×) | 2026-10-12 (wider-universe check), classified 2026-10-13 (AUDIT F-07) | **Not fixed.** Adjusted-price layer (gap #3) deferred. | Suspected; not a CONFIRMED DEFECT, because nothing was checked against exchange records |
| D2 | Large moves the audit marked "unclear — check" | VEDL 2026-04-30 (−33%, 1.9×), NMDC 2022-10-27 (+86%, 2.0×), SIEMENS 2025-04-07 (−25%, gap −35%, 3.5×), IDEA 2021-09-16 (+26%, no baseline) | 2026-10-13 (F-07) | Not fixed | Suspected. The 2026-10-26 data-audit draft calls VEDL "not adjusted for demergers", citing F-07, but F-07 itself never verified it. |
| D3 | A move the audit marked "probably real" (heavy volume) that may still be a demerger | ABFRL 2025-05-22 (−56%, gap −52%, 6.1×) | 2026-10-12 | Not fixed | UNTESTED. High volume on an ex-date does not rule out a demerger. This audit adds the flag; it is not verified. |
| D4 | **New in this audit:** a low-volume overnight gap below F-07's 25% close-to-close threshold | ALLCARGO 2023-04-18 (gap −24.8%, close −21.0%, 0.28×) | 2026-10-29 (this audit, read-only SQL) | Not fixed | Suspected (same signature as D1) |
| D5 | Heavy-volume moves judged real | ADANIENT 2023-02-01/02, INDUSINDBK 2025-03-11 (checked against press reports, 2026-10-26); IEX 2025-07-24, OFSS 2024-01-18, RECLTD 2024-06-04 (volume signature only) | 2026-10-13 / 10-26 | n/a | Not a problem. ADANIENT and INDUSINDBK are confirmed real. The other three are likely real. |
| D6 | Splits and bonuses inside the 49 | BAJAJFINSV 1:5 split + 1:1 bonus, ex-date 2022-09-13: our series is continuous, so its history is back-adjusted | 2026-10-26 | n/a | Checked: not a problem |
| D7 | Impossible bars (high below low, close outside the range, price ≤ 0) | None among all 399,321 daily bars (query, 2026-10-29); none in the 49 (2026-10-26); none in the 306 (2026-10-12) | n/a | n/a | Checked: not a problem |
| D8 | 21,287 daily rows with zero volume, probably indices | `candles` | 2026-10-13 (F-15) | Not verified | Open. The 306 stocks themselves showed no zero volume (2026-10-12). |
| D9 | Stale or short histories | ICICIAMC (159 sessions) and JSWINFRA stop on 2026-08-11; TMCV, IREDA, NUVAMA and KFINTECH are short | 2026-10-12 | n/a | A known limit. ICICIAMC and JSWINFRA are in the reject set; TMCV, IREDA and KFINTECH are in the extra training set. |
| D10 | Local bar end date read wrongly (UTC instead of IST) in documents | Watchlist candles end 2026-09-07, not 09-08. fd-v1 RUN-NOTES says "ending 2026-09-06". | 2026-10-13 | Corrected in AUDIT text | A document error, not a data error |

### 1b. The checks and tools that guard bars

| # | Problem | Found | Fixed | Label |
|---|---|---|---|---|
| T1 | The split check (`services/split_check.py`) reads only `upcoming_events`, which holds future events only. The 2026-10-05 "0 suspicious, 1 event checked" result therefore covered almost nothing historical. Today the table holds 13 company events, 2026-09-22 to 2026-10-23, all after the last local bar. | 2026-10-13 (F-07) | Not fixed | **CONFIRMED DEFECT** (a gap in coverage). The "do not prioritize gap #3" advice in `split_contamination_latest.md` rests on that empty check. |
| T2 | Bar overwrites were silent before the correction log | 2026-10-05 | `fcaef35` (log) and `0bdaa76` (stale M02 feature snapshots cleared when a bar changes), 2026-10-05 | Fixed going forward. Anything earlier cannot be traced. |
| T3 | No record of when each bar first arrived | 2026-10-13 (F-07) | `eb09242` (`candle_arrivals`), 2026-10-13 | Fixed going forward. Bars loaded earlier have no arrival time, and locally that means every bar. |
| T4 | Possible mixed price bases over time (**this audit**). The broker's history appears to be adjusted as of the day it is downloaded (BAJAJFINSV). Daily top-ups only re-request the latest bar. A split after the first download could leave old bars on the old basis and new bars on the new one, and the correction log would record only the one overlapping bar. | 2026-10-29 | n/a | **UNTESTED EXPLANATION / structural risk.** Matters mostly for prod, which takes in bars every day. Not checked. |

### 1c. Calculation fixes (not bar problems, listed because they changed inputs or results)

| # | Problem | Found | Fixed | Effect on history | Label |
|---|---|---|---|---|---|
| C1 | The breadth input counted a stock with no bar yet as "bearish". It changes about the first 50 days of breadth, plus days with late listings. | 2026-10-13 (F-08) | `2145a20`, 2026-10-13 15:41 | ps3 (2026-10-20) retrained every wf-v1 fold model **after** the fix and reproduced wf-v1 exactly. Other earlier reports were not reproduced. | CONFIRMED DEFECT, fixed |
| C2 | Signals were scored over 15 calendar days (about 10 sessions) instead of 15 trading days. | 2026-10-13 (F-03) | `2145a20` | Old stored v1 signal results were not rescored. The evidence reports here use `strict_score` and trading-day bars, so they were not affected. | CONFIRMED DEFECT, fixed |
| C3 | Portfolio replay: a cash bug in the half-out step | 2026-10-12 | `25c6a6c`, 2026-10-12 | The published `portfolio_replay_*` report already carries the corrected numbers (worst fall 11–14%, not 25–35%) | CONFIRMED DEFECT, fixed and re-reported |
| C4 | 4 "bolder on bad data" decision bugs (market judge backup, NaN stop or target, probability > 1, NaN score) | 2026-10-20 (`bad-data-bugs-severity`) | `99147d8`, 2026-10-20 | None. These are decision-path bugs, not bar bugs. On clean data they change nothing, and no dropped module was seen after 2026-10-14. | CONFIRMED DEFECT, fixed |
| C5 | Stale index, VIX and breadth caches in the API process | 2026-10-13 (F-09) | `6209568` | Live display only. No evidence report used it. | CONFIRMED DEFECT, fixed |

## 2. Each evidence report against the known problems

Rule used: AFFECTED means the report ran **before** a fix (or with an unfixed problem) **and** its stocks
and dates overlap an affected stock and date. Universe and window come from each report's own text. Run date
is the commit date. Problems D1–D4 involve only non-watchlist stocks (checked against the ev15 list: none of
the 13 is in `used_49`). The breadth input is built from watchlisted stocks only
(`ml/market_context.py` line 158), so wider-universe bars never feed a 49-stock result.

| Report | Run | Data window | Universe | Bar problems D1–D4 | Breadth fix C1 | Re-run? |
|---|---|---|---|---|---|---|
| Barrier model retrain (`research/2026-09-15-barrier-model-retrain.md`) | 2026-09-15 | 2021-08 to 2026-09 | 51 + 150 + 104 | **AFFECTED.** The training lists (`ml_models.training_symbols`) include all 13 flagged stocks: mid = ABFRL, IDEA, IEX, NMDC, OFSS, RECLTD, SANOFI, SIEMENS, VEDL; small = ALLCARGO, BAJAJELEC, SCI, TRIVENI. The large-cap model has only ADANIENT and INDUSINDBK (real). | Before the fix (UNKNOWN effect) | No |
| `retrain_real_question_20261008.md` | 2026-10-08 | 2021-08 to 2026-09 | 49 (main) | NOT AFFECTED (49) | Before (UNKNOWN, expected small) | No |
| `real_question_calibrated_models_20261009.md` (`*_barrier_cal`, `*_cal_ev`) | 2026-10-08/09 | to 2026-09-08; held-out Nov 2025 to Aug 2026 | 49 / 150 / 104 | **AFFECTED** for mid and small (same lists as above). The held-out window contains ALLCARGO 2025-11-12, VEDL 2026-04-30 and TRIVENI 2026-07-22. The claim that "mid and small calibrated scores were honest" is drawn partly from those stocks. | Before (UNKNOWN) | No |
| `asof_replay_2026-07-13_2026-08-14` | 2026-10-11/12 | 2026-07-13 to 08-14 | 49 | NOT AFFECTED | Before (UNKNOWN; the window is far from the first 50 days) | Its 561 ideas were re-scored exactly in ps3 (prices only) |
| `walk_forward_2025-10-01_2026-08-15` and `score_reliability*` | 2026-10-11/12 | 2025-10-01 to 2026-08-15 | 49 | NOT AFFECTED | Before. Not reproduced by a retrain (pause-check reused the stored models and matched). UNKNOWN, expected small. | Matched by pause-check using the stored models |
| `wf_v1/` (wf-protocol-v1, frozen) | 2026-10-12 | 2023-07-01 to 2025-01-31 | 49 | NOT AFFECTED | **Shown NOT AFFECTED.** ps3 retrained after `2145a20` and reproduced it exactly. | Reproduced 2026-10-20 (ps3) and 2026-10-22 (pause-check) as diagnostics. The verdict is unchanged and was never re-run to change it. |
| `horizon_grid_*` (3 periods) | 2026-10-12 | 2025-02 to 06, 2025-08 to 12, 2026-05 to 08 | 49 | NOT AFFECTED | Before. UNKNOWN, expected small. | No |
| `ranking_diag/` | 2026-10-12 | 2025-02-01 to 2026-08-15 | 49 | NOT AFFECTED | Before. Its fold models use the same trainer as wf-v1 (not separately reproduced). UNKNOWN, expected small. | S1 (2026-10-26, after the fix) got the same headline: best 5 −0.14%, all −0.27% |
| `portfolio_replay_2025-10-01_2026-09-17` | 2026-10-12 | 2025-10-01 to 2026-09-17 | 49 | NOT AFFECTED | Before (UNKNOWN) | Already re-reported after the cash fix C3 |
| `input_and_regime_spike_2026-10-12`, `weakness_experiment_2026-10-12` | 2026-10-12 | 2024-08 to 2026-08 | 49 | NOT AFFECTED | Before. The weak-market line uses breadth from the 49, but the affected days are in 2021. UNKNOWN, expected nil. | No |
| `wider_universe_data_check`, AUDIT F-07 | 2026-10-12/13 | 2021-08 to 2026-09 | 306 | These are where D1–D3 were found | n/a | n/a |
| ps3 `cost_stress/` | 2026-10-20 | wf-v1 period plus as-of replay | 49 | NOT AFFECTED | After the fix | n/a |
| ps2 `bad_market/` | 2026-10-20 | 5 windows, 2024-08 to 2026-05 | 49 | NOT AFFECTED | After | n/a |
| ps1 `module_ablation/`, ps11 `wait_check/`, ps12 `pit_replay/` | 2026-10-20/21 | 2026-07-13 to 08-14 (ps12 to 09-04) | watchlist | NOT AFFECTED | After | n/a |
| ev15 `stock_split/` | 2026-10-21 | n/a (a seeded split of 257 names into two sets) | 257 | Does not use prices. It decides which flagged stocks land in the 177 (section 4). | n/a | Locked |
| A8 `pause_check/` | 2026-10-22 | decisions 2022-01-03 to 2026-08-14 | 49 | NOT AFFECTED | After (stored wf models reused) | n/a |
| fd-v1 `fd_v1/` (fd-protocol-v1, locked) | 2026-10-26 | 2023-07-01 to 2025-01-31 | 49 | NOT AFFECTED | After | Run once. Locked. |
| `scoreboard/` S1 and S2 | 2026-10-26 | S1 2025-02-01 to 2026-08-15; S2 2026-07-13 to 10-31 | 49 | NOT AFFECTED | After | n/a |
| M04 / M05 / M12 evidence scripts | 2026-10-02 | 2021-08 to 2026-09 | Watchlist (`m05_*.py` filters `is_watchlisted`) | NOT AFFECTED (M05). M04 and M12: universe not checked, so **UNKNOWN**. | Before | No |
| Prod forward trial (from 2026-10-14) and prod models | live | prod data | prod | **UNKNOWN.** Prod's `candle_corrections` was not read (prod is off limits here). Prod takes in bars daily, and company events (splits on 10-06, 10-08, 10-16, 10-22, 10-23; demergers 10-01, 10-06, 10-08) fall inside the trial. Whether any of those stocks is in the brain's universe was not checked. | n/a | Sealed; not touched |

**"NOT AFFECTED" means not affected by any known problem.** It does not mean clean. There is no
authoritative company-event history for the 49 either, so an unknown unadjusted event cannot be ruled out.
The search for one (every move beyond ±12% in the 49, done on 2026-10-26) found none.

## 3. Verdicts that could change if re-run

Nothing here is a reason to re-run a sealed or locked confirmation. wf-protocol-v1 (spent period) and
fd-protocol-v1 (closed by the owner on 2026-10-26, "no tuning or rerun") keep their verdicts. Any check
below would be a **new, separately labelled diagnostic** with its own ledger row. It could not overturn or
replace those verdicts.

| Verdict | Type | Could bar problems explain it? | Label |
|---|---|---|---|
| wf-v1 FAIL (skill 7/21 folds, profit 9/21, model −0.20% per trade) | OBSERVED FAILURE | No known bar problem touches its 49 stocks and dates. The calculation fix C1 was shown to change nothing (exact reproduction after the fix). | "Bad data caused the fail" is an **UNTESTED EXPLANATION**, and **no evidence supports it**. |
| fd-v1 FAIL (5-day, both parts) | OBSERVED FAILURE | Same 49 stocks and same period as wf-v1. Run after every fix. | **UNTESTED EXPLANATION**, no evidence for it |
| Ranking diagnostics / S1: "the score does not rank stocks" (rank correlation +0.011, lower bound −0.015) | OBSERVED FAILURE | 49 stocks. S1 after the fixes agrees with the pre-fix diagnostic. | **UNTESTED EXPLANATION**, no evidence for it |
| ps12: brain no better than chance; ps3: edge does not survive costs; as-of replay: picks equal random | OBSERVED FAILURES | 49 stocks, after or unaffected by the fixes | **UNTESTED EXPLANATION**, no evidence for it |
| Calibrated mid and small models "honest and useful" (2026-10-09) | Positive result | **Yes, possibly.** The held-out window and the training include the flagged stocks. An unadjusted −60% "fall" makes a stop-loss label look easy to predict, so it could make the scores look more honest than they are, or less. | **UNTESTED EXPLANATION** in both directions. This is the only result where exposure is confirmed. |
| 2026-09-15 barrier models (mid AUC 0.564, small 0.556) | Positive, modest | Same as above | **UNTESTED EXPLANATION** |
| Split check "0 suspicious" and the advice to deprioritise the adjusted-price layer | Check result | The check covered almost no history (T1) | The conclusion is **not supported**. This is a CONFIRMED DEFECT in the check's coverage, not in the data. |

## 4. Remaining gaps and what they mean for the 177-stock experiment

The experiment trains on 49 + 128 (ev15 seed 7, `stock_split_ev15.json`). The 129 reject stocks are used only
to reject.

**Flagged stocks by set (from the ev15 file):**

| Set | Flagged stocks with suspect jumps | Real-looking big moves |
|---|---|---|
| 49 (used) | none | ADANIENT, INDUSINDBK (confirmed real) |
| 128 extra training | **SANOFI** 2024-06-13, **BAJAJELEC** 2023-09-14, **VEDL** 2026-04-30, **ABFRL** 2025-05-22 (D3) | OFSS 2024-01-18, RECLTD 2024-06-04 |
| 129 reject | ALLCARGO 2023-04-18 and 2025-11-12, TRIVENI 2026-07-22, SCI 2023-03-31, NMDC 2022-10-27, SIEMENS 2025-04-07, IDEA 2021-09-16 | IEX 2025-07-24 |
| Short or stale | Training: TMCV, IREDA, KFINTECH. Reject: ICICIAMC, JSWINFRA, NUVAMA | |

**Gaps that stay open:**

1. **No company-event history.** `upcoming_events` holds only future rows, and the look-ahead audit marks
   this NOT TESTABLE (row 14). The design's gate, "every gap above 30% must match a company event", cannot
   be met with local data (design review a8).
   - *For the 177:* never write "adjusted". Apply review item b6: list every gap above 30%, and for each one
     remove the stock's labels whose 15-day window spans it, plus its input rows for the next 252
     sessions. Report "unadjusted; affected windows removed".
2. **The threshold misses smaller events.** A split or bonus need not move the price by 30%. D4 (ALLCARGO
   2023-04-18, −24.8%) would pass a 30% gate.
   - *For the 177:* a 30% gate alone is not enough evidence of cleanliness. Report the low-volume gaps
     between 12% and 30% too. This audit's query found them clustered on market-wide days (2025-04-07,
     tariff day) plus a few single-stock regulatory events (PAYTM 2024-02-01, IIFL 2024-03-05). They look
     real but are not verified.
3. **Mixed price bases over time (T4).** Untested. Local history was downloaded in one go, so this is mainly
   a prod and forward-data risk. *For the 177:* low risk on local data; state it as a limit.
4. **The correction log has never been exercised on real data** (0 rows; local data not re-ingested since
   it was added). *For the 177:* there is no correction history to rely on. Re-ingesting bars in the middle
   of the experiment would change its inputs. Fix the data snapshot (bar count plus a hash) at the start.
5. **Survivorship and today's sector map.** NOT TESTABLE; already on every report.
6. **Breadth comes from the 49 only.** This is by design, and it keeps wider-universe bar problems out of
   49-stock inputs. For the 177, market inputs still describe the 49. That is a stated limit, not a defect.
7. **Prod data integrity is unknown** (corrections, arrivals, and the October company events inside the
   forward trial). A read-only prod check would need the owner's go-ahead. It was not done here.

**What this means in plain words:** the 177-stock experiment is the first result whose training data
includes stocks with suspect price jumps. Four of the 128 extra stocks need their affected windows removed
before any result is read. Otherwise a fake −50% "fall" teaches the model a stop-loss pattern that never
happened. Without a company-event list, the result can only be labelled "unadjusted, affected windows
removed".

## 5. What was not done

- Nothing was re-run, retrained or rescored. No evidence file, protocol or code was changed.
- Prod was not queried.
- No move was checked against exchange records in this audit. D1–D4 remain signatures, not proof.
- The M04 and M12 evidence scripts' universes were not checked.

## 6. Read-only database queries (local Docker, 2026-10-29)

All queries ran inside `begin transaction read only … rollback`, through `docker exec` using the
container's own login. `.env` was not read.

- `candle_corrections`: 0 rows. `candle_arrivals`: 0 rows.
- `candles` (daily): 399,321 bars, 324 instruments, last bar 2026-09-09 (stocks 2026-09-07; 304 stocks on 09-04).
- Impossible bars (high < low, close ≤ 0, close outside the range): 0.
- `upcoming_events`: 539 results rows and 13 corporate_action rows (2026-09-22 to 2026-10-23: splits TAALTECH,
  BLSE, BUILDPRO, BANSALWIRE, JSWDULUX, AZADIND; bonuses MOLDTECH, MOLDTKPAC; demergers KMSUGAR, VERANDA,
  BHAGYANGR; rights NATCOPHARM, OLAELEC).
- Equity moves with close change above 25% or overnight gap above 20%: the 17 rows listed in D1–D5.
- `ml_models.training_symbols`: flagged stocks are in every mid and small barrier and calibrated model
  (2026-09-15 and 2026-10-08). The large-cap and 49-stock models hold only ADANIENT and INDUSINDBK.

Sources read: `docs/brain/evidence/` (all files named in section 2), `docs/brain/EXPOSURE-LEDGER.md`,
`docs/brain/AUDIT-2026-10-13.md`, `docs/superpowers/specs/2026-10-26-data-audit-and-scoreboard-DRAFT.md`,
`docs/superpowers/specs/2026-10-29-selection-design-review.md`, `services/ingestion.py` (`_upsert_candles`),
`db/models/market.py`, `ml/market_context.py`, `brain/cost_stress.py`, `brain/walk_forward.py`, and git
history (`fcaef35`, `0bdaa76`, `eb09242`, `2145a20`, `25c6a6c`, `99147d8`, `c660433`).
