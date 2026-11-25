# 5D Paper Trial Protocol, v1 (large cap)

| Field | Value |
|---|---|
| Status | **DRAFT FOR OWNER SIGN-OFF.** Frozen by sha256 once signed. Any later change is a new file (`-v2.md`), never an edit of this one |
| Source | GitHub #279, section H recommendations approved by Naresh on 2026-11-14 for drafting this spec |
| Revision | Draft revision 4 (2026-11-15, before sign-off). Rev 4: stale cut-off counting clarified (5.3). Rev 2: owner rulings on the market check (3.1), open paper positions, missing marks, sealed-trial access and retries (5.3, 9). Rev 3: card words, missing factor detail vs unverifiable prediction (3.1, 5.3), three cohorts, stale-position publication, provisional totals and later verified marks, and read-only h05 access enforced by database permissions (5.3, 9). Reference-outcome rules are unchanged (section 11) |
| Journey | #340 (Option B). Shared by #318 (full-scan reference outcomes), #321 (100-portfolio ledger), #330 (report periods and snapshots) |
| Not covered | The running h05 trial (own protocol, unchanged), 10D (deferred), 15D (behind its lab approval gate). Implementation is out of scope until separately approved |
| Code references | Checked read-only on 2026-11-14, branch `review/local-work-nov12` |

## 1. Purpose and the three separate numbers

The trial shows a beginner a daily 5-day idea for a large-cap stock, the model score and the Brain safety checks, and later the idea's outcome. It also measures whether the model's ranking adds value. Three numbers answer three different questions and are never mixed:

| Number | Question | Anchor |
|---|---|---|
| **Model target outcome** | Did the model's own target happen? | Signal-day close: met when the session-5 close is at least signal close x 1.02 |
| **Reference strategy return** | What would one fixed-rule 5-session trade have returned after costs? Same rule for every eligible stock | Entry fill (section 4) |
| **Paper portfolio P&L** | What did each synthetic paper portfolio make in rupees under its own rules? | That portfolio's own fills (#321) |

## 2. Universe, calendar and eligibility

- **Model**: prod model 2 (`swing_classifier`, 37 inputs, uncalibrated, label "+2% at the session-5 close"). The score is shown as "Model score NN/100 · 5D ranking signal", never as a chance.
- **Universe**: the frozen large-cap evaluation list used by h05 (52 stocks), point-in-time.
- **Sessions**: exchange trading sessions, defined by NIFTY 50 daily bars. Weekends and holidays are skipped. Daily candles are read with `.astimezone(IST).date()`.
- **Eligible**: in the frozen universe, with a candle on the signal session, at least 220 bars, and finite inputs.
- **Scored**: eligible, and the model produced a score from that session's candle. Otherwise NOT SCORED, with the reason saved. A stock is never scored from older data.
- **No liquidity or volatility filter** is added, and none may be added after outcomes are seen.

## 3. Signal, safety checks, selection and repeats

### 3.1 Signal and display (Option B)
- The signal is taken at the close of session D, from completed candles only.
- The card shows the model score and the Brain checks that apply (data quality, market, risk) as **separate** items.
- A failed or unavailable required check blocks a new paper entry.
- **Market check**: a `NO_NEW_TRADES` banner fails the check and blocks every new paper entry. A `DEFENSIVE` banner passes it: the card shows **"Careful"** and the reason recorded by that Brain run, and every other existing Brain safety block still applies. There is no extra limit on 5D entries in a `DEFENSIVE` market. A cap such as "at most 2 new buys a day" is a portfolio policy that needs separate explicit approval.
- **Card, report and filter words** (all taken from the saved snapshot):
  - **"Eligible for paper review"** is the safety result. It is shown when every required check passes, including the score check below.
  - **"In the day's top 5"** is a separate ranking fact. A top-5 stock that fails a check shows "Held back: <check>" in place of the safety result.
  - A paper entry needs both.
  - "Paper buy" means a recorded simulated purchase.
  - The 5D trial never uses "TradeMind said Buy". There is no 5D TRADE label until a separately approved 5D decision profile exists.
- **Score check: missing factor detail is not the same as an unverifiable prediction.**
  - **Missing factor detail**: the score reconciles to its saved prediction, model version and model file hash, but a per-input explanation is not available for that version. The score is shown, the missing detail is stated, and eligibility is unaffected.
  - **Unverifiable prediction**: the score cannot be reconciled to a saved prediction and model version. The score is hidden and the stock is **not eligible for paper review**, with the reason shown. It keeps its reference row, and reports count it as "score not verified", never inside a score band.
- Model score, Brain decision and paper action are stored separately. The original score and decision are kept even when a portfolio acts differently.

### 3.2 Selection
- **Counted picks**: the top 5 scored stocks by model score per signal session. A shortfall is recorded.
- A Brain-blocked stock still keeps its reference row (section 6).

### 3.3 Repeat rule
**Rule**: a stock picked and counted on session D is not counted again on sessions D+1 to D+4. It can count again from session **D+5**. The reason: a pick made on D is held through session D+5 at the latest, so a pick made on D+5 enters at the D+6 open and never overlaps.

- A repeat pick inside the window **stays recorded**. It appears in "all selections" figures and keeps its reference row, but it is **not counted** in the verdicts.
- The window restarts only from a **counted** pick. A blocked repeat does not extend it.
- The rule applies to model picks and to the momentum-five comparison. It does not filter the benchmark pool.
- Code basis: `h05_rules.repeat_blocked` (blocked when `i - last < 5`, `backend/src/swing_trade_ml/brain/lanes/h05_rules.py:210-226`).
- Repeat memory **restarts at each run boundary**: only selections of the same run are compared (`h05_service.py:315-325`).

**Worked example (sessions numbered within one run):**

| Session | Stock X in the top 5? | Counted? | Why |
|---|---|---|---|
| D = 10 | yes | **yes** | no earlier counted pick |
| 11 | yes | no | 11 - 10 = 1, under 5 |
| 13 | yes | no | 13 - 10 = 3, under 5 |
| 14 | yes | no | 14 - 10 = 4, under 5 |
| **15** | yes | **yes, the first session it can count again** | 15 - 10 = 5; the window restarts at 15 |
| 17 | yes | no | 17 - 15 = 2, under 5 |
| 20 | yes | yes | 20 - 15 = 5 |

The pick on 10 enters at the session-11 open and exits by the session-15 close. The pick on 15 enters at the session-16 open, so the two trades never overlap.

## 4. Entry, exit, costs and net return

### 4.1 Entry
- Entry is at the open of session 1 (the session after D), plus buy slippage.
- The pick must be recorded before that exchange session's approved fill window opens. A row recorded at or after that point is never simulated: it is UNRESOLVED and flagged `recorded_late`. A retry can therefore miss a session, but can never backdate a fill.

### 4.2 Exit (reference strategy)
This is the h05 trade rule (`h05_rules.py:107-174`).
- **Target** = entry fill x 1.02. **Stop** = entry fill x 0.96. Both are anchored to the **entry fill**, not the signal close.
- Each daily candle of sessions 1-5 is checked in order, and the **stop is checked first**.
- **Opening gap through the stop or the target**: exit at that session's open.
- **One candle touching both levels** (the order within the day is unknown): treated as the stop and flagged `same_candle_both_levels`.
- **Neither level hit**: exit at the session-5 close.
- Every exit price gets sell slippage. **Session 6 is never read.**

### 4.3 Costs (large cap)
| Item | Value |
|---|---|
| Slippage | 10 bps of price per side, against us. An assumption from daily ranges, not measured fills |
| Taxes | 11.9 bps of buy turnover; 10.4 bps of sell turnover |
| Depository | Rs 15.93 flat per sell (about 1.6 bps of Rs 1,00,000) |
| Brokerage | Rs 0 |
| Round trip, approx. | **about 44 bps, slippage included** (20 + 22.3 + about 1.6) |
| Higher-cost sensitivity | +30 bps per side and charges x2. Reported, never decides |

### 4.4 Order size and net return
- **Rs 1,00,000 is a reference order size, not a hard cash cap.**
  - shares = floor(1,00,000 / entry_fill)
  - Buy charges are added on top, so the cost can slightly exceed Rs 1,00,000.
  - A price above Rs 1,00,000 buys no share and is UNRESOLVED (`too_expensive`).
  - Paper portfolios apply their own cash limits (#321).
- **Net return formula**:
  - entry_fill = session-1 open x 1.0010
  - exit_fill = exit price x 0.9990
  - cost = shares x entry_fill x 1.00119
  - proceeds = shares x exit_fill x 0.99896 - 15.93
  - **net return = (proceeds - cost) / cost**
- The same function is used for picks, benchmark stocks, the comparison figures and reference rows.

### 4.5 Worked example
Illustrative prices: signal close Rs 1,000; session-1 open Rs 1,010; no candle reaches either level; session-5 close Rs 1,030.

| Step | Calculation | Result |
|---|---|---|
| Entry fill | 1,010 x 1.0010 | Rs 1,011.01 |
| Target / stop | x 1.02 / x 0.96 | Rs 1,031.23 / Rs 970.57 |
| Shares | floor(1,00,000 / 1,011.01) | 98 |
| Cost | 99,078.98 + 117.90 buy taxes | Rs 99,196.88 |
| Exit fill | 1,030 x 0.9990 | Rs 1,028.97 |
| Proceeds | 1,00,839.06 - 104.87 - 15.93 | Rs 1,00,718.26 |
| **Reference strategy return** | 1,521.37 / 99,196.88 | **+1.53%** (gross +1.78%) |
| **Model target outcome** | 1,030 / 1,000 - 1 = +3.0% | **met** |

## 5. Required tests

### 5.1 Exit tests (trade of section 4.5: entry fill Rs 1,011.01, 98 shares, cost Rs 99,196.88)
| # | Case | Candles | Exit price, then fill | Flag | Net return |
|---|---|---|---|---|---|
| T1 | Opening gap through the stop | session 2 opens Rs 960 | Rs 960, fill Rs 959.04 | `gap_fill` | **-5.37%** (a gap is not protected) |
| T2 | One candle touches both levels | session 3 low Rs 970, high Rs 1,032 | stop Rs 970.57, fill Rs 969.60 | `same_candle_both_levels` | **-4.33%** |
| T3 | Exit at the session-5 close | no level reached; session-5 close Rs 1,030 | Rs 1,030, fill Rs 1,028.97 | none | **+1.53%** |
| T4 | Target hit during the day | session 2 high Rs 1,035, low above the stop | target Rs 1,031.23, fill Rs 1,030.20 | none | **+1.66%** |
| T5 | Opening gap through the target | session 2 opens Rs 1,040 | Rs 1,040, fill Rs 1,038.96 | `gap_fill` | **+2.52%** |
| T6 | Missing candle in the window | no candle on session 4 | none | UNRESOLVED (`missing_candle`) | none: excluded and counted |
| T7 | Poisoned session 6 | a session-6 candle at Rs 1 | unchanged | none | same as T3 |

The model target outcome is always judged separately against the signal close. For example, T2 with a session-5 close of Rs 1,030 has the model target **met** while the reference trade lost 4.33%.

### 5.2 Repeat tests
- R1. Using the section 3.3 table, sessions 11, 13 and 14 are blocked; 15 counts; 17 is blocked; 20 counts.
- R2. A blocked repeat does not restart the window: picks on 10, 14 and 15 give counted, blocked, counted.
- R3. The first pick of run 2 counts even if the same stock was picked on run 1's last session.

### 5.3 Other acceptance tests
- **Coverage**: eligible = scored + not scored on every signal day. Every eligible stock has exactly one reference row, and every row is pending, matured or unmeasurable.
- **Linking**: each paper entry links to exactly one reference row; many entries may share one row.
- **Filters**: reference and portfolio reports use the same filter definitions (#330). Their counts may differ.
- **Score**: the displayed score reconciles to the saved prediction and model version. Inputs are listed only for the verified model version, and input values are kept apart from measured contributions. Test both cases from 3.1: a stock with missing factor detail stays eligible, and a stock with an unverifiable prediction is hidden and not eligible.
- **Missing risk evidence** means no new paper entry, with a visible reason.
- **Idempotency**: re-running a day gives identical rows and no duplicates.
- **Restart**: a restart after a committed fill neither refills nor loses the fill. Committed fills are never deleted or redone; only unfinished steps run again. Fills are de-duplicated on a stable execution identifier that includes the buy/sell side. Test: stop the process after a fill is committed, restart, and check that the fill count and identifiers are unchanged.
- **Publishing**: the daily summary is published only after reconciliation passes. It ends in one of three states:
  - **Fully reconciled**: every check passes and no position is stale.
  - **Reconciled with exceptions**: published with a warning banner that lists each exception. Allowed only when all of these hold:
    1. every other reconciliation check passes;
    2. every stale position is caused by a missing or unverified candle, not by a calculation or ledger error;
    3. at most 20% of open positions across all portfolios are stale, and the day's candle set is not missing as a whole.
    A stale position past its 5-session cut-off becomes final unresolved and is still listed. The cut-off counts exchange sessions after the session whose candle is missing (that session is 0): a position still unverified at the close of session 5 becomes final unresolved. While it is still held it stays in the exposure and stale-position counts.
  - **Not reconciled**: any other failed check, or more than 20% of open positions stale (a data outage). The daily summary is blocked and no new paper entries are made.
  - Test each state, including the 20% boundary.
- **Reproducibility**: random-five and momentum figures are identical on shuffled input order.
- **Trial protection**: h05 is accessed read-only; trial data lives in separate writable storage; checksums on an isolated fixture are an extra check.

## 6. Coverage ledger, matured day and missing outcomes

- **Coverage ledger** (#318): one reference row per eligible stock per signal day. That includes NOT SCORED, Brain-blocked, repeat-blocked and never-bought stocks. A row has a measurable outcome when reliable prices exist.
- **Matured day**: a signal day counts toward the verdict when **at least 10 stocks were scored** that day and at least one counted pick and the comparable pool both have a finished reference outcome.
  - The threshold counts **scored** stocks, because only scored stocks can be picked or compared. This matches the h05 code (`h05_report.py:99-102`). The h05 draft text says "eligible"; see section 10.
- **Missing outcomes**: UNRESOLVED (missing candle, too expensive, recorded late) and NOT EVALUATED rows are final. They never become zero or an estimate.
  - They are removed from both sides by the same rule. The picks' daily average uses counted picks with a finished outcome. The benchmark uses scored stocks with a finished outcome, from the same day, fills and costs.
  - Example: 50 scored stocks and 5 counted picks, with 1 pick and 3 other stocks UNRESOLVED, gives a picks' average over 4 and a benchmark over 46. The missing rows are shown in the day's counts.
- **Unmeasurable picks per run**:
  - More than 10% of counted picks UNRESOLVED: evidence-quality warning only, and the verdict stands.
  - More than 20%: **both** verdicts for that run are INCONCLUSIVE, with the reason stated.

## 7. Verdicts

### 7.1 Two verdicts, never merged
- **SELECTION**: does the ranking beat the average scored stock?
  - Daily edge = the counted picks' average net return minus the average net return of every scored stock with a finished outcome, on the same day.
  - PASS when the 90% range is wholly above 0; FAIL when it is wholly below 0; otherwise INCONCLUSIVE.
  - The model-target-outcome edge is a veto: a range for it that is wholly below 0 turns a PASS into INCONCLUSIVE.
- **ECONOMIC**: do the picks make money after the assumed costs?
  - Daily series = the counted picks' own average net return, with no benchmark. The same PASS / FAIL / INCONCLUSIVE rule applies.
- The report prints both words and a one-sentence reading, using the h05 reading table (`h05_verdict.py:113-128`). For example, an ECONOMIC PASS without a SELECTION PASS reads: "Profitable under the stated assumptions; model advantage over the baseline was not established."

### 7.2 Uncertainty
- The evidence is one value per matured signal day, never one per pick.
- The 90% range is a block bootstrap over consecutive signal days: blocks of 5 days (the holding length, so overlapping trades stay together), 2,000 draws, seed 7, 5th and 95th percentiles (`h05_rules.py:232-250`).
- With fewer than 10 matured days there is no range, so the verdict is INCONCLUSIVE.

### 7.3 Per run
- A run is **60 consecutive signal sessions**. Runs follow each other with no gap and no overlap.
- A run is **final** when it is closed and every outcome (picks and pool) has matured. Before that it shows "waiting: N outcomes not matured" and no verdict.
- A final run is INCONCLUSIVE for both verdicts, with the reason stated, when any of these holds:
  - fewer than 40 matured days;
  - the top 5 was short on more than 20% of days;
  - more than 20% of counted picks are UNRESOLVED.
- Runs are never extended and missed sessions are never made up.

### 7.4 Three runs, each verdict separately
- **PASS**: at least 2 of 3 runs PASS, no run FAILS, and the pooled 90% range (the three runs' daily values joined in day order) is wholly above 0.
- **FAIL**: the pooled range is wholly below 0, or at least 2 runs FAIL.
- **INCONCLUSIVE**: anything else, including while fewer than 3 runs are final.
- An INCONCLUSIVE run is final but **neither PASS nor FAIL**. Its daily values still join the pooled series, and it cannot be re-run or replaced (`h05_verdict.py:90-110`, `h05_report.py:262-291`).

| Run | SELECTION | ECONOMIC |
|---|---|---|
| 1 | PASS | PASS |
| 2 | INCONCLUSIVE (36 matured days) | FAIL |
| 3 | PASS | PASS |
| Pooled range | +0.10% to +0.55% | -0.05% to +0.40% |
| **Combined** | **PASS** (2 PASS, 0 FAIL, pooled above 0) | **INCONCLUSIVE** (one FAIL blocks PASS; only one FAIL and the pooled range is not below 0, so not FAIL) |

If SELECTION were PASS, INCONCLUSIVE, INCONCLUSIVE, the combined result would be INCONCLUSIVE (only one PASS).

## 8. Comparison figures (shown, never decide)

- **Random five**:
  - For each day, the pool is the scored stocks with a finished reference outcome, **sorted by symbol**.
  - One draw = 5 stocks sampled without replacement per day (all of them if fewer than 5), averaged across days.
  - 200 draws, `random.Random(7)`, matching `h05_rules.random_k_distribution`.
  - Seed, draw count, order rule and pool hash are stored.
- **Momentum five**:
  - **Score**: the 20-session close-to-close return ending at the signal close.
  - **Adjustment**: closes before a split or bonus ex-date inside the lookback are adjusted using `corporate_actions` ratios (split x new FV / old FV; bonus x den / (num + den)). A stock with an unexplained overnight gap above 20% inside the lookback is not ranked that day, with the reason recorded.
  - **Universe**: the same day's scored stocks; a stock needs 21 closes to be ranked.
  - **Selection**: top 5, ties broken by symbol A to Z. Same entry, exit, costs and repeat rule as the model's picks.
- **NIFTY 50**: context only.

## 9. Portfolio ledger and reports (#321, #330)

- **Paper portfolios**: about 100 synthetic portfolios in an isolated test environment, in **three cohorts**: momentum, model-only and Brain-filtered. Each cohort uses the same matched starting setups, fill rules and costs, and only simulated fills. The exact count, balances, drawdown and cash rules are approved in the #321 rules table. Random five is a comparison figure only (section 8), never a portfolio cohort.
  - Recorded per session: fills, exits, blocks, cash, positions and marks.
  - Daily checks: opening cash - buys - charges + sells = closing cash; positions x mark + cash = equity.
  - **What they prove**: application behaviour (isolation, permissions, bookkeeping, risk blocks, report totals). **They do not prove model edge.** Model evidence comes only from section 7.
  - **One position per stock**: a portfolio never adds to a position it already holds. A fresh eligible signal may open a new position in that stock only after the earlier position has closed. This portfolio rule is separate from the section 3.3 repeat rule, which counts picks for research.
  - **Missing candle for an open position**: the position is flagged and its valuation is marked **stale**. The last confirmed mark and its timestamp are shown. No exit is invented, and the day is reconciled only with exceptions (section 5.3). #321 defines when verified data can resolve the gap (the fix is added as a new record, never by overwriting) and how stale positions are shown in portfolio totals. Reference rows keep the T6 rule unchanged (UNRESOLVED, `missing_candle`). Even if a portfolio position is later resolved from verified data, the reference row is never resolved late. Stale or unresolved portfolio positions never enter the section 7 verdicts.
    - **Provisional totals**: while any position is stale, these figures are labelled "provisional": equity, unrealized P&L, cohort totals and comparisons, and the drawdown of every affected account. Cash, realized P&L, fills and counts stay final.
    - **A later verified mark**: it is appended as a correction record, and the stale record is never overwritten. The stale day and later days get their marks restated in a **new revision** of each affected daily summary. The original summary is kept and shown as "revised on <IST date and time>". A pending exit is recorded on the session it actually happened, flagged `resolved_after_stale`. Decisions already taken are never changed afterwards, including entries allowed or blocked, drawdown halts and cash available. Only valuations are restated.
    - **Exit parity**: portfolio exits follow the section 4 exit rule, with one exception. When the candle needed to decide an exit is missing, the exit is paused, never skipped or invented. It resumes from verified data, or the position becomes final unresolved after the cut-off.
    - **Run end for the ledger**: a run is final for the portfolio ledger when it closes. Final unresolved positions are carried at their last confirmed mark, labelled as unresolved, with no realized P&L. This never affects the section 7 verdicts.
  - **Sealed-trial access**: #321 and #330 read approved h05 and Brain outputs through **one read-only interface**, never by writing to those tables. Portfolio and report writes go only to separate trial storage. Each session records which outputs were available, and a missing output appears with a stated reason. For example, the Brain-filtered cohort makes no new entries that day, with the reason recorded.
    - **Enforced by database permissions**, not only by code.
      - The trial job and the report readers connect with dedicated database roles.
      - The read role may only `SELECT` the approved h05 and Brain outputs.
      - The trial write role may only `INSERT` and `SELECT` on trial tables. No role used by the trial has `UPDATE` or `DELETE` on h05 tables or on committed trial ledger rows.
      - The existing application role is unchanged.
      - Tests run as the trial roles: a write to an h05 table is refused, and an update or delete of a committed fill is refused.
      - The roles and grants are part of the trial's migration approval. Credentials are never printed or committed.
- **Reports** (#330):
  - Periods: day, month, quarter, year and financial year (April start).
  - The 1-day report interval is shown separately from the 5D horizon.
  - Score bands (90+, 80 to below 90) and decisions are taken from the immutable snapshot saved at addition or execution. A later signal is kept separately.

## 10. Differences from h05 (h05 itself is unchanged)

| Topic | h05 | This trial |
|---|---|---|
| Scope | 3 groups, models 2/16/17 | Large cap, model 2 only |
| Brain safety checks | none | Shown beside the score; a failed or unavailable check blocks a paper entry |
| Late-recording cutoff | Fixed 09:15 IST | The approved fill window of the actual exchange session |
| Matured-day threshold | Text says "eligible"; code counts scored | Scored (matches the h05 code) |
| UNRESOLVED picks | Counted and reported only | More than 10% gives a warning; more than 20% makes the run INCONCLUSIVE |
| Random-five pool order | Not fixed (rows loaded without ORDER BY, `h05_report.py:303`) | Sorted by symbol; seed and pool hash stored |
| Momentum comparison | none | Section 8 |
| Cost wording | Text: about 58 bps, depository "15.9 bps" (the code charges Rs 15.93 correctly) | About 44 bps; depository about 1.6 bps |
| Portfolios, saved ideas, reconciled daily summary | none | Sections 3.1, 5.3 and 9 |
| Storage | h05 tables (append-only) | Separate writable trial storage; h05 read-only |

Unchanged and shared: calendar, eligibility, entry at session-1 open, the +2% / -4% / 5-session exit rule, charges function, order size, repeat rule, verdict rule, block bootstrap, minimum evidence and the three-run rule.

## 11. Points flagged for owner review (clarifications, not new rules)

1. **Repeat-rule wording.** #279 H-13 said "counted once per 4 sessions". The precise rule (section 3.3) is: blocked on D+1 to D+4, counts again from D+5. This is the same behaviour as the h05 code; only the wording is corrected.
2. **Repeat memory restarts at each run boundary** (R3). This comes from the h05 code and was not stated in #279.
3. **Repeat-blocked picks keep their reference rows** and appear in "all selections" figures, but not in verdicts. This was implied in #279; it is now explicit.

4. **Revision 2 rulings (2026-11-14)** add the market-check meaning (3.1), report words (3.1), one position per stock, stale marks, sealed-trial access (9), and restart de-duplication (5.3). **None of them changes a reference-outcome rule**: entry, exit, costs, T1-T7, the repeat rule, the verdict and the three-run rule are as in revision 1.
5. **Revision 3 rulings (2026-11-14)**:
   - "Eligible for paper review" is the safety result, and "In the day's top 5" a separate ranking fact.
   - Missing factor detail is separated from an unverifiable prediction; the latter blocks paper entry, which moves toward caution.
   - Three cohorts, with random five as a comparison only.
   - Publication states, provisional totals and later verified marks.
   - Database-permission enforcement of read-only h05 access.

   No reference-outcome rule changes. One clarification: an unverifiable prediction is shown as "score not verified" and is never placed in a score band. Its reference row is unchanged.
6. **Revision 4 (2026-11-15)**: the stale cut-off is counted from session 0, the session whose candle is missing. A position still unverified at the close of session 5 becomes final unresolved, and while held it stays in the exposure and stale-position counts (5.3). No reference-outcome rule changes.

No other rule differs from the approved section H.

## 12. Approved decisions (from #279 section H, 2026-11-14)

| # | Decision | Value |
|---|---|---|
| 1 | Authoritative protocol | This file; approved separately from h05 |
| 2 | Reference exit rule and anchors | +2% / -4% from the entry fill, at most 5 sessions, stop first, a candle touching both counts as the stop, gaps fill at the open |
| 2b | Model-target anchor | Signal-day close; the session-5 close must be at least +2% above it |
| 3 | Fill window | Session-1 open; the pick must be recorded before that session's window opens |
| 4 | Large-cap slippage | 10 bps per side |
| 5 | Cost wording | About 44 bps round trip; h05 text fixed after its trial |
| 6 | Rs 1,00,000 | Reference order size, charges on top |
| 7 | Pass gates | SELECTION and ECONOMIC only, never merged |
| 8 | Momentum | 20-session adjusted return, ties A to Z, comparison only |
| 9 | Random five | Comparison only, 200 draws, seed 7, pools sorted by symbol |
| 10 | Matured day | At least 10 scored stocks and at least one finished counted pick; the ledger keeps every eligible stock |
| 11 | Minimum evidence | 60-session runs, 40 matured days, at most 20% short days |
| 11b | Three-run rule | Per verdict: at least 2 PASS, none FAIL, pooled range above 0; an INCONCLUSIVE run is neither pass nor fail |
| 12 | Unmeasurable picks | More than 10% gives a warning; more than 20% makes the run INCONCLUSIVE |
| 13 | Repeat rule | Counts again from D+5 (section 3.3) |
| 14 | Separate cap-group or pattern model sample size | Deferred until the 5D large-cap verdict exists |
| 15 | Financial-year start | April |

## Sign-off

Owner: ____________ Date: ____________ sha256 of this file at sign-off: ____________
