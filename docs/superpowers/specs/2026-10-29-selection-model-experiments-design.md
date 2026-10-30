# 15-day stock selection experiments — design for owner approval (rev 2)

Status: **DESIGN rev 2 for owner approval, 2026-10-29. Not approved to build, not approved to run.**
No code, model, table, protocol, ledger row or trading rule has been changed by this document.
Proposed protocol name: **`sl-protocol-v1`** (selection lab). Frozen only when the owner signs section 17 and
the signed commit is tagged.

Inputs to this revision:

- independent review `2026-10-29-selection-design-review.md` (all (a)/(b) items adopted unless noted);
- audits `2026-10-29-audit-market-gate.md`, `2026-10-29-audit-model-scores.md`,
  `2026-10-29-audit-data-integrity.md` (sections 10–12);
- data research `2026-10-29-r0-data-feasibility-report.md` (section 13).

## 0. Owner decisions this design is built on

| Date | Decision |
|---|---|
| 10-29 | Phase B runs unchanged 9 Nov – 4 Dec, three candidates, no fourth. This lab is a **separately signed follow-up phase**, not approved to execute. |
| 10-29 | Training only on the locked 177 (49 + ev15 extra 128). The 129 held-back stocks stay under ev15: never trained on, never used for feature choice or tuning. |
| 10-29 | Research pre-2021 data and forward testing; investigate free and paid sources; **buy nothing** without approval. |
| 10-29 | NSE archives first for results/shareholding; paid alternatives only if needed, with costs. |
| 10-29 | Point-in-time market-cap groups for formal evidence; today's lists only for labelled exploration. |
| 10-29 | Model baseline S0 = the raw 15-day barrier model (D6, corrected wording in review 2), plus random and momentum. |
| 10-29 | Anything that passes enters **shadow only**. No automatic replacement, no real money, no customer BUY. Promotion needs independent confirmation, forward evidence and explicit owner approval. |
| 10-29 | Owner/tester screens only; D0a SEBI check treated as **not done**. |
| 10-29 | Earnings filter studied separately; never activated without evidence and approval; earnings exposure of open positions documented. |
| 10-29 | D1 pre-2021 confirmation is labelled "NO WARNING (untouched history)", never PASS. D2 quotes only; buying needs a plan amendment; licensing review covers **all** NSE feeds. D3 F1 is report-only. D4 every label is measured against the 49. D5 one 15-day forward candidate at a time. D6 S0 = the raw 15-day barrier model, not M06. |
| 10-29 | Include four more workstreams with clear boundaries: market-regime separation, horizon-specific scores, feature reduction, daily shadow top-5. Feature reduction must sit in an allowed slot, **never a fourth Phase B candidate**. |
| 10-29 (review 3) | Q2 YES. Q3 YES for design and definitions only — company inputs not authorised until B3 verifies public times, completeness, point-in-time correctness and licensing. Q4 CONDITIONAL YES pending the 6.1/6.2 clarifications. Q9 YES. Q5 approved as winner-only, no fallback. Lab does not run until B1 and the evidence-plan amendment are approved. |
| 10-29 (review 2) | Held-back 129: **one use by the lab only** — for the single preselected winner. Ranking **and** money both required; positive net expectancy required; "no winner" is a valid outcome. Pre-registration may be signed separately; **the lab may not run until an evidence-plan amendment is signed**. Corporate actions: never auto-remove real losses or every > 20% move — classify verified error / real gap / unresolved anomaly. S0 named as the raw 15D barrier model, never M06. Phase B unchanged. Q10, Q11 approved; Q12, Q13 resolved. |

## 1. Why this exists — what we know, sorted honestly

| Kind | Item | Source |
|---|---|---|
| **Observed failure** | wf-protocol-v1 (15D): beat random in 7 of 21 blocks — FAIL | `docs/brain/evidence/wf_v1/` |
| **Observed failure** | Same-day ranking: rank correlation +0.011 (lower bound −0.015) | `ranking_diag/` |
| **Observed failure** | fd-protocol-v1 (5D): AUC ≈ 0.52, picks no better than every stock — FAIL | `fd_v1/` |
| **Observed failure** | First two prod weeks: brain had 0 counted ideas; tester positions filled the slots | two-week review, Oct 2026 |
| **Confirmed defect** | Prices are not split/bonus adjusted; no corporate-action history | review a8 |
| **Confirmed defect** | Breadth inputs use today's watchlist for every past date (survivorship) | look-ahead audit item 12 |
| **Confirmed defect** | Shareholding `filed_on` stored as a date, not a publication time | `db/models/company.py` |
| **Confirmed defect** | The split check reads only future events; its "0 suspicious" covered almost no history | data-integrity audit |
| **Untested** | 9–10 stocks with suspected unadjusted jumps (none in the 49); mid/small calibrated models trained on them | data-integrity audit |
| **Confirmed defect** | M10's FII check reads one day too few (errs bolder); market-wide inputs sit inside the stock score; replay gates differ from live | market-gate audit, section 10 |
| **Confirmed defect** | The live brain picks 15-day ideas with the **5-day** score; mid/small caps scored by the large-cap model; decisions don't record which model scored them | model-score audit, section 11 |
| **Process risk** | "Score ≥ 0.80" means three different numbers (Phase B B1 vs the trial set vs the owner's rule) | section 11 |
| **Untested explanation** | The target asks the wrong question (market direction, not stock choice) | → experiment S1 |
| **Untested explanation** | Inputs are chart-only | → S3 |
| **Untested explanation** | Too few independent market situations to learn from | → S2, Stage 2 |
| **Untested explanation** | Market mood shifts (monthly hit rate 3.5%–35%) confuse the model | → section 10 |
| **Untested explanation** | Look-alike inputs make the model learn noise | → S2r, section 12 |
| **Untested explanation** | Large liquid stocks leave little edge | → cap-group split |

An untested explanation is never written as a cause until an experiment supports it.

## 2. Goals, non-goals, anti-goals

**Goals**

- G1. Measure separately whether (A) a "beat the others" target, (B) a wider training set, (R) fewer, cleaner
  inputs and (C) results/shareholding inputs make 15-day **stock ranking** better.
- G2. Measure separately whether better ranking turns into **money after realistic costs** under the locked
  trade rule (+8% / −4%, half out at +5%, 15 trading days).
- G3. Audit and document the market gate, the meaning of every model score, and past data problems.
- G4. Design a shadow record of daily top-5 ideas that is independent of free portfolio slots.
- G5. One read-only owner/tester screen with honest labels.

**Non-goals.** No new horizon (10D only later, section 15; 5D closed). No new model families (LightGBM via the
existing trainer). No new services or infrastructure. No change to the live brain, M06, the v1 bot, the sealed
trial, Phase B, trial-frozen files (`backend/tests/trial_freeze.py`), or any order/size/stop/limit.

**Anti-goals — failure even if it "works":** a result shown with a stronger label than its data allows;
tuning after a result; a fifth lab candidate after the others fail; a held-back stock reaching any training,
feature choice or setting; a filing used before it was public; a shadow idea counted as a trade or as profit;
a score presented as a promise or as "BUY".

## 3. Where this sits

```
 Now ─ 9 Nov                 9 Nov ─ 4 Dec        after 4 Dec, only with a separate owner GO
 ┌───────────────────────┐   ┌──────────────┐     ┌──────────────────────────────────────────────┐
 │ Audits (done, read-   │   │ Phase B runs │     │ Lab Stage 1 on development data              │
 │ only) + sign sl-proto-│ → │ UNCHANGED    │ →   │ Stage 2: one survivor, untouched pre-2021    │
 │ col-v1 before Phase B │   │ B1, B2, B3   │     │ Stage 3: forward shadow — only when no other │
 │ results exist         │   │              │     │ 15D candidate is in forward test (D5)        │
 └───────────────────────┘   └──────────────┘     └──────────────────────────────────────────────┘
 Hold-out A (forward trial from 14 Oct) stays sealed; nothing here reads its results.
```

Recommendation (Q1): sign before 9 Nov so Phase B's results cannot shape these rules. Phase B's B2 asks
"does 177 help the *current* model"; the lab asks it of the *new* target — not a duplicate.

**Forward queue (D5).** If Phase B locks a survivor (`wf-protocol-v2`), it has the single 15D forward slot for
its Phase C. A lab survivor waits for that slot. Only one 15D candidate is ever in forward test.

## 4. The lab candidates

Family of four model candidates, fixed in advance, one run each, no retuning. Each differs from the one it is
compared with by **exactly one** thing.

| ID | Role | Trained on | Target | Inputs | Compared with (R4) |
|---|---|---|---|---|---|
| **S0** | control: **raw 15-day barrier model** — LightGBM, label "+8% before −4% within 15 trading days", retrained per fold, uncalibrated (as Phase B). **Not** the M06 meta-combiner, **not** prod `swing_classifier` v2 (5-day) | 49 | +8% before −4% in 15 days | the 53 | — |
| **S1** | experiment A — the target | 49 | beats the 49 (4.1) | the 53 | S0 (better) |
| **S2** | experiment B — wider training | 177 | beats the 49 | the 53 | S1 (better) |
| **S2r** | feature reduction (section 12) | 177 | beats the 49 | reduced set | S2 (not worse) |
| **S3** | experiment C — company inputs | 177 | beats the 49 | the 53 + 8 | S2 (better) |
| F1 | earnings filter — **report-only**, not in the family, never a survivor | — | — | — | — |

All candidates **score the same 49 stocks on the same days** (as Phase B). Picks = each day's top 5 among the
49 with ≥ 220 bars; no liquidity filter on picks, so every candidate and baseline chooses from the same pool.

**Baselines on every candidate:** Phase B's own functions (`phase_b.py`: every stock, random 5 from the same
pool, risk-matched random, momentum 5, NIFTY matched, cash), so the lab compares like for like with Phase B —
plus S0.

### 4.1 Experiment A — "beats the 49" (S1, S2, S2r, S3)

For decision day *d* and stock *s*:

- Day 1 and day 15 are **market-calendar** days (NIFTY bars). r(s,d) = close(day 15) ÷ open(day 1) − 1; open
  joined from `candles`. Missing either bar → no label; the stock is left out of that day and counted.
- **Reference group = the 49** (D4), for every candidate: those with ≥ 220 bars, a valid r, and median
  turnover (close × volume, 20 sessions up to and including *d*) ≥ ₹5 crore. ≥ 10 such stocks a day, else no
  labels that day.
- Excess e(s,d) = r(s,d) − median r of the reference group. The 128 extra stocks are labelled against the same
  median.
- **Label** = 1 if e(s,d) would rank in the top 30% of the reference group (percentile ≥ 0.70, ties averaged).
- `label_end_ts` = bar day+15, so the existing `apply_cutoff` and purge are exact.

Note: the trainer always uses `class_weight="balanced"`. Ranking is unaffected; probabilities are not used.
S0's label runs from today's close, S1's from the next open (small, reported).

The label is **not the trade rule**: picks are still traded and scored with +8% / −4% / half at +5% / 15 days.
Hence two separate verdicts (section 6).

### 4.2 Experiment B — 177 stocks (S2)

Training stocks = the 49 + ev15 extra 128 (`stock_split_ev15.json`, SHA-256 checked before every run). Every
`symbols` list is passed explicitly — never `symbols=None`, which reads today's watchlist.

**Data-quality gate** (raw prices, no corporate-action history — review a8/b5/b6):

| Check | Rule |
|---|---|
| History | a stock enters training from its first complete input row (~272 bars); `min_rows = 300` |
| Gaps | > 10 missing sessions in a calendar year → that stock-year left out, listed |
| Bad bar (high < low, close ≤ 0, zero volume; M01 numbers where they apply) | leave out the bar's row **and every label whose window [d+1, d+15] contains it**; inputs using it for up to 252 sessions are reported, not dropped |
| Large overnight move (\|close-to-open\| > 20%, M01 spike line) | **flagged for review, never removed automatically.** Each flag is classified before the run, from a written record: **VERIFIED ERROR** (exchange record or company filing shows a split/bonus/demerger or bad print not reflected in our prices) → only that stock's labels spanning it and its rows for the next 252 sessions are left out; **REAL GAP** (exchange record shows a genuine move, e.g. results) → kept, losses included; **UNRESOLVED ANOMALY** (no record either way) → kept in the main result, and a sensitivity result without them is reported; a candidate must pass in **both**. Moves ≤ 20% are never touched. Verification is done by hand from public exchange pages (no automated collection) and recorded in the run folder. The report never says "adjusted" |
| Survivorship | all 177 are listed today; stated in the report's first paragraph. Fixed only in Stage 2 |

### 4.3 Experiment C — results and shareholding (S3)

Fixed now; not changed after any result:

Definitions. *Q* = the latest quarterly result public before 15:30 IST on decision day *d* (L1–L2); *Q−4* = the
same quarter a year earlier; every figure is the **first-filed** value (L3). Basis: consolidated if **both**
quarters have consolidated figures, else standalone if both have standalone, else missing — never mixed.
*t0* = the first session whose 15:30 IST close is after the result's `public_at`.

| # | Name | Exact formula | Missing when | First usable |
|---|---|---|---|---|
| 1 | `sales_yoy` | Revenue from operations Q ÷ Q−4 − 1, clipped to [−1, +2] | either quarter absent; Q−4 revenue ≤ 0; banks/NBFCs/insurers (different format) | session *t0* |
| 2 | `profit_yoy` | Net profit after tax Q ÷ Q−4 − 1, clipped to [−2, +2] | either quarter absent; Q−4 profit ≤ 0 | session *t0* |
| 3 | `opm_change_pp` | OPM(Q) − OPM(Q−4), OPM = (revenue from operations − total expenses + depreciation + finance costs) ÷ revenue from operations × 100 | as #1 | session *t0* |
| 4 | `days_since_results` | trading sessions from *t0* to *d* | no result public in the last 200 sessions | session *t0* |
| 5 | `results_reaction` | close(*t0*+2) ÷ close(*t0*−1) − 1, minus NIFTY 50 over the same sessions | before the *t0*+2 close; any of the 3 bars missing | close of *t0*+2 |
| 6 | `promoter_change_pp` | promoter & promoter-group % of shares, quarter *H* − quarter *H*−1 | either filing absent or not summing to 100% ± 0.5 | first session after *H*'s `public_at` |
| 7 | `fpi_change_pp` | foreign portfolio investors % (category total), *H* − *H*−1 | as #6 | as #6 |
| 8 | `dii_change_pp` | domestic institutions % (mutual funds + insurers + banks + other DII, category total), *H* − *H*−1 | as #6 | as #6 |

*H* = the latest shareholding pattern public before 15:30 IST on *d*; both quarters as first filed. Any input
whose latest source filing is older than 200 sessions is missing.

**Missing-value behaviour:** missing stays missing — no fill-forward beyond the rules above, no imputation, no
zero. LightGBM's native missing handling is used. A **new scorer** requires the 53 base inputs (as today) but
allows company inputs to be missing, so S3 is trained and scored on **exactly** the same stock-days as S2. Each
input's missing share per year is reported.

**Point-in-time availability — NOT yet verified (blocks S3 only):** an input may be used only when its source
gives a per-filing dissemination timestamp and first-filed values (L1, L3, L5), under a valid licence or consent
(Q8). Before S3 runs, a verification record must show, for ≥ 20 of the 177 stocks × ≥ 8 quarters, that every
row has `public_at` and first-filed values. Known today: NSE/BSE filings carry dissemination time; NSE results
moved to "Integrated Filing – Financials" on 2025-04-01 (two formats to join); our existing
`company_filing_shareholdings.filed_on` is a date only (fails L1). If verification fails or consent is not
granted, **S3 is NOT TESTABLE**; the multiple-testing correction still counts four (section 6.3), the
conservative choice.

### 4.4 F1 — earnings filter (report-only)

The rule already exists live: the brain's M13 blocks new ideas with results due within 5 trading days
(`m13_news/calendar.py`), v1 blacks out 3 days (`services/avoid.py`). Both are trial-frozen. History of
board-meeting notices does not exist (`upcoming_events` is refreshed, not accumulated). So F1:

- starts only when a dated notice store exists (Release 3), measures forward: trades the rule blocks, their
  hypothetical result vs kept trades, losses avoided, profit given up, days with **unknown** calendar;
- changes nothing live, is never a survivor, and any change to M13 or `avoid.py` is a separate owner decision
  after the trial.

**Earnings exposure of open positions — reporting only:** for each open paper position, whether a results
meeting falls before its 15-day exit and how many days away. Symbols and dates only (allowed under the seal).

## 5. Leakage rules

Unchanged rules: decision at the IST close, entry next open, `.astimezone(IST).date()`; overlapping labels
purged on `label_end_ts`; 15-day block bootstrap.

| Rule | Detail |
|---|---|
| L1 Public time | Every filing row carries `public_at` = exchange dissemination timestamp. Period dates never used for timing. |
| L2 Next usable session | Usable for day *d* only if `public_at` < 15:30 IST on *d*. |
| L3 As first filed | Revisions are new rows with their own `public_at`; history is never overwritten. |
| L4 Calendar known in advance | A results date counts only if its notice was public by the decision close. |
| L5 No timestamp, no formal use | A source without per-filing `public_at` is exploration only. (Today's `company_filing_shareholdings.filed_on` is a date → fails L5 as stored.) |
| L6 Automated test | Before every run, a test samples (stock, day) pairs and proves every company value came from a row public before that day's 15:30 IST. |
| L7 Training-window only | Every data-driven choice (feature reduction, calibration, liquidity) uses only rows before the fold's cutoff. |
| L8 Universe recorded | The breadth inputs' watchlist set and its hash go in `manifest.json`. |

## 6. How candidates are judged

### 6.1 Ranking verdict — "does a higher score mean a better stock?"

Reuse `brain/ranking_diagnostics.py` functions (`daily_rank_correlation`, `topk_middle_bottom`); do **not**
call its `run_diagnostics` (it hard-codes a protected window that the ledger now marks spent — reason stated in
the protocol).

**Scored set U(d):** the 49 stocks with ≥ 220 bars, a model score and a valid r(s,d) on decision day *d*. Days
with |U(d)| < 10 are left out of every ranking measure (and counted). r(s,d) is the **gross** 15-day price return
of 4.1 (open of day 1 → close of day 15), the same quantity the S1–S3 label is built on; costs do not enter the
ranking verdict.

**Primary ranking statistic (R1) — mean daily rank IC:**

```
IC(d)  = Pearson( rank_avg(score(s,d)), rank_avg(r(s,d)) )   over s in U(d)
         rank_avg = ranks with ties given their average rank   (= Spearman correlation; pandas .rank().corr())
IC̄     = (1 / D) · Σ_d IC(d)                                  D = days with |U(d)| ≥ 10, equal weight per day
LB_1.25 = 1.25th percentile of IC̄ over 2,000 resamples of the day-ordered IC(d) series in runs of 15
         consecutive days (moving-block bootstrap, seed 7)
R1 passes  ⇔  IC̄ > 0  and  LB_1.25 > 0
```

Days where every score or every r is equal are left out (IC undefined) and counted. Implemented with
`ranking_diagnostics.daily_rank_correlation` (called with r as its `ret` column) and the new
`selection_lab._block_quantile` (q = 0.0125).

**Top-5 performance — evaluated separately from overall ranking.** IC measures the order of the whole day;
the money is made only by the top 5, so the top 5 has its own rules:

| Measure | Definition | Rule |
|---|---|---|
| Top-5 set T(d) | the 5 highest scores in U(d); exact ties broken by symbol, alphabetically | — |
| Top-5 excess (R2) | mean over days of [ mean of e(s,d) over T(d) ], e = r − median r of U(d) | > 0 and > momentum 5's same statistic |
| Top-5 hit share | mean over days of [ share of T(d) whose r is in the top 30% of U(d) ] (chance ≈ 30%) | reported |
| Spread | mean over days of [ mean r of top 20% − mean r of bottom 20% of U(d) by score ] | reported |
| AUC | reported only, never a rule | — |

A model can pass R1 (good overall order) and fail R2 (no useful top), or the reverse; both are required.

### 6.2 Money verdict — "does it make money after costs?"

**Execution and costs = exactly the locked 15-day protocol** (`evidence-defs-v1` §3a, `replay_scoring.strict_score`,
the function Phase B and wf-v1 use):

- Entry at the **next trading day's open** after the decision close, ₹40,000 per idea (`POSITION_INR`).
- Exit: stop −4% checked first in each bar (a bar touching stop and target counts as the stop), half sold at
  +5%, rest at +8%, otherwise the close of the 15th bar; **gaps fill at the open**, not at the level.
- Costs (`services/costs.py`) at the **code defaults**: slippage 5 bps per fill; brokerage ₹0 per order;
  statutory charges 11.9 bps on buys and 10.4 bps on sells; depository fee ₹15.93 per sell order. **These values
  are pinned in `config.json`, and a run refuses if the loaded settings differ** (the scorer reads settings,
  which a local `.env` can override; checked 2026-10-29: the local `.env` overrides none of them).
- Each day's top 5 are separate trades even when a stock repeats on consecutive days (Phase B convention).

**M0 — positive net expectancy:** the mean `net_return` over every finished top-5 trade in the development
folds, under the costs above, is **> 0** (point estimate; its 1.25% block-bootstrap bound is reported).
M1: that mean is above every stock's and momentum 5's on the same days (`phase_b` matched functions) and above
S0's. M3: the equal-capital portfolio replay (`portfolio_sim`, ₹10 lakh as Phase B, ladder limits, 25% sector
cap, top 5 a day, 15% halt) has max drawdown < 15%.

**Cost stress.** Pass rule **M2:** M0 **and** M1 still hold with charges ×2 (`CostStress(charges_x=2.0)`).
Diagnostics, never pass or fail: the other locked ps3 settings from `cost_stress.STRESSES` — fills 0.3% worse,
and both together (the harshest) — reported in one table: for each setting, top-5 mean net per trade, every
stock, momentum 5, S0, and the difference, each with its trade count. A measured real-fill setting (ps4) is
added as a column if it exists at run time.

### 6.3 Pass rules — fixed before any run

Development folds: expanding walk-forward, 28-day test folds, **2023-07-01 → 2026-08-15** (≈ 41 folds), same
start as wf-v1 and fd-v1. Every candidate trains exactly like `train_model` (20% chronological hold-back at the
code default, LightGBM defaults, `calibrate=False`); model names `sl1_<cand>_<cutoff>`, registered TRAINED,
never activated.

**Statistical family and correction (fixed now):**

- **Family** = the four model candidates {S1, S2, S2r, S3}. S0, the baselines and F1 are not in it (they are
  comparisons or reports, never winners). The family size stays **4** for the correction even if a candidate
  turns out NOT TESTABLE.
- **Primary hypothesis per candidate:** H0 "mean daily rank IC ≤ 0" (R1). One-sided, familywise error 5%,
  **Bonferroni**: each candidate's lower bound is the **1.25th percentile** (5% ÷ 4) of a 15-day block
  bootstrap of the mean daily IC (2,000 draws, seed 7), via a new `selection_lab._block_quantile`;
  `walk_forward.bootstrap_low` is not edited. R4's paired IC difference uses the same 1.25th percentile.
- **All other rules (R2, R3, M0–M3, N) are extra gates joined by AND.** They can only make passing harder, so
  they need no further correction; their bounds, where computed, also use the 1.25th percentile.
- **Across phases:** Phase B's own family of three is untouched and separate. Both use the same development
  data, so neither can confirm anything; the protection is that **at most one** lab candidate ever reaches a
  later test, and that test (Stage 2 at the 5th percentile, Stage 3 under Phase C rules) is a single test.

**Stage 1 — development (best label: "NO WARNING (diagnostic)"):**

| # | Rule | S1 | S2 | S2r | S3 |
|---|---|---|---|---|---|
| R1 | Mean daily IC > 0 and its lower bound > 0 | ✓ | ✓ | ✓ | ✓ |
| R2 | Top-5 excess > 0 and > momentum 5's | ✓ | ✓ | ✓ | ✓ |
| R3 | IC > 0 in ≥ 60% of eligible folds (≥ 10 days, ≥ 20 finished ideas; ≥ 12 eligible) | ✓ | ✓ | ✓ | ✓ |
| R4 | vs its comparison model, on days both scored ≥ 10 stocks: paired daily IC difference lower bound **> 0** (better) — for S2r: lower bound **> −0.005** (not worse) | ✓ | ✓ | ✓ | ✓ |
| M0 | **Positive net expectancy:** top-5 mean result per trade after costs and slippage > 0 | ✓ | ✓ | ✓ | ✓ |
| M1 | Top-5 mean per trade after costs > every stock, > momentum 5, > S0 | ✓ | ✓ | ✓ | ✓ |
| M2 | M1 holds at 2× charges | ✓ | ✓ | ✓ | ✓ |
| M3 | Portfolio replay max drawdown < 15% | ✓ | ✓ | ✓ | ✓ |
| H1 | Held-back check — **not** run per candidate; run **once**, on the preselected winner only (below) | — | — | — | — |
| N | ≥ 30 trading days with picks and ≥ 100 finished trades, else INCONCLUSIVE | ✓ | ✓ | ✓ | ✓ |

**Both verdicts are required.** Ranking (R1–R4) and money (M0–M3) are reported as two separate lines; a
candidate qualifies only if **both** pass. A candidate that ranks well but has zero or negative net expectancy
after costs is reported as **"ranks, does not pay"**, cannot be the winner, and can never be promoted to any
recommendation.

**Choosing the one winner (development data only, before the held-back check):** among qualifying candidates,
the highest R1 lower bound; ties → simpler wins (S1 < S2r < S2 < S3). Exactly one is preselected and recorded
(name, numbers, timestamp) in the run folder and the exposure ledger **before** the 129 are scored.

**Held-back check H1 — one use by the lab, winner only:** the preselected winner is scored once on the 129
(IC and every-stock both measured within the 129; Phase B's ≥ 30-day gate). It survives only if mean IC ≥ 0
**and** its top-5 mean after costs is not below every stock's. INCONCLUSIVE = does not survive. It can only
reject. **No fallback:** if the winner fails, the runner-up is **not** checked. Held-back uses, all logged in
the exposure ledger: Phase B 3 (B1, B2, B3) + lab 1 = **4**.

**"No winner" is a valid, expected outcome.** It is recorded as NO WINNER (with every candidate's numbers)
when: no candidate qualifies; the winner fails H1; or the evidence is INCONCLUSIVE. Then: no fallback, no
retuning, no fifth candidate, no re-run; a ledger row; the result goes to the next decision review. If a winner
survives H1 it is locked as `sl-protocol-v1-locked` and is the only candidate that may go to Stage 2/3.

**Stage 2 — untouched pre-2021 history (one survivor, once):** expanding walk-forward, 28-day folds, test
2016-01-01 → 2021-07-31, point-in-time universe incl. delisted. All Phase C pass rules + R1 at the 5th
percentile. Best label: **"NO WARNING (untouched history)"** (D1) — never PASS. If the data cannot be had:
NOT TESTABLE, and the candidate is reported as "forward only, no historical check".

**Stage 3 — forward shadow:** Phase C's clock exactly (3-month working check without returns, verdict at 6
months, one count-based extension to 9). Starts only when the 15D forward slot is free (D5). The **only**
stage that can give PASS.

### 6.4 Large cap vs mid cap

Split by NIFTY 100 / NIFTY Midcap 150 membership **on the decision day** for formal results; today's lists
only with the badge "EXPLORATORY — today's index lists (survivor bias)". < 30 days with picks in a group → NOT
TESTABLE (small caps expected to be).

### 6.5 Labels shown everywhere

| Label | Means |
|---|---|
| Exploratory | development data, already looked at |
| No warning (untouched history) | Stage 2 passed its rules on pre-2021 data |
| Forward-tested — PASS | Stage 3 passed |
| Shadow (not a trade) | a recorded idea, never counted as a trade or profit |

Labels are computed from the run record, never typed.

## 7. Data periods

| Period / stocks | Use | Status |
|---|---|---|
| 2021-08 → 2026-08-15 (complete inputs from ~2022-09), 49 + 128 | training, Stage 1 | seen — Stage 1 can only warn |
| 129 held-back | H1, **once**, on the preselected winner only | Phase B 3 uses + lab 1 = **4 uses**; each logged |
| Hold-out A (from 2026-10-14) | not used | sealed |
| Pre-2021 (2014 → 2021-07) incl. delisted, plus NIFTY 50, INDIA VIX, 16 sector indices, PIT breadth universe | Stage 2 | not held — section 13 |
| After the lock | Stage 3 | future |

Every use gets a new row in `docs/brain/EXPOSURE-LEDGER.md` before the run; no existing row is edited. Locked
protocols (wf-v1, fd-v1, evidence-defs-v1/v2, phase-b-settings, ev15) and evidence files are not touched.

## 8. Experiment record and reproducibility

Each run writes an immutable folder `docs/brain/evidence/sl_v1/<run_id>/`:

- `config.json` (example below), its SHA-256 in the manifest;
- `manifest.json`: git commit, tag, Python/library versions, `feature_set_version()`, data fingerprint per
  table (rows, first/last date, SHA-256 of sorted (symbol, date, close, volume)), watchlist hash (L8), model
  artefact hashes, start/end time;
- `metrics.json`: every number in 6.1–6.4 with its sample size; `report.md` in plain English.

**Run guard** (copy of `five_day.py`'s guard: tag in history, frozen files unchanged since the tag, no re-run)
**plus a refusal when `git status --porcelain` is not empty.** Runs are imported into `research_lab_runs`
(append-only trigger as `experiment_selections`).

```json
{
  "protocol": "sl-protocol-v1", "run_id": "sl1-S2-20261207T1630", "candidate": "S2", "horizon_days": 15,
  "label": {"kind": "excess_vs_median", "reference": "used_49", "top_share": 0.30,
            "entry": "next_open", "exit": "close_day_15", "min_reference": 10, "liquidity_inr": 5e7},
  "train_universe": {"source": "ev15", "sha256": "bc8878f2…", "sets": ["used_49", "extra_training_set"]},
  "score_universe": "used_49", "heldback_check": {"set": "reject_set", "when": "winner_only_once", "uses_before_this_run": 3},
  "trainer": "five_day_train pattern + feature list", "algorithm": "lightgbm", "calibrate": false,
  "features": {"base": "FEATURE_COLUMNS@<feature_set_version>", "reduction": null, "company": []},
  "folds": {"first_test": "2023-07-01", "last_test": "2026-08-15", "test_days": 28, "purge": "label_end_ts"},
  "top_k": 5, "trade_rule": "evidence-defs-v2", "baselines": "phase_b functions",
  "cost_stress": {"pass": "2x_charges", "diagnostic": ["fills_0.3pct", "both"]},
  "bootstrap": {"block_days": 15, "draws": 2000, "seed": 7, "lower_pct": 1.25}, "seed": 7
}
```

## 9. Architecture — reuse first

```
 importers (Release 3) ─▶ research_eod_prices, research_index_members, research_filing_results,
                          research_holdings, research_board_notices, research_corp_actions   (public schema,
                                                                                               local-only)
                                   │ PIT loaders (L1–L3, L6)
 candles (v1, read-only) ──────────┤
                                   ▼
 brain/selection_lab.py (NEW): label 4.1, data gate 4.2, feature reduction 12, new scorer, ranking + money
 verdicts, guard, report.  Reuses: five_day_train pattern, ml/dataset purge, walk_forward folds/outcomes,
 ranking_diagnostics fns, replay_scoring, portfolio_sim, cost_stress, phase_b baselines, splits,
 stock_split hash, m06 trainer.fit_honesty (import only), seal
                                   ▼
 docs/brain/evidence/sl_v1/<run_id>/ ──import──▶ research_lab_runs (append-only)
                                   ▼
 owner/tester API (GET, seal-aware) ──▶ Observatory tab "Selection lab"
```

**Not reused, and why:** `walk_forward._train` / `train_model` (no label or input hook); `ml/train.py` stays
untouched (v1 path); `ml/asof._score_all` (drops rows with any missing input); `phase_b`'s guard (records a
dirty tree, does not refuse); `ml/calibrated_model.py` (fit-time wrapper, not out-of-fold). Trial-frozen files
(`ml/features.py`, `ml/market_context.py`, `ml/calibrated_model.py`, `brain/modules/**`) are imported, never
edited; new inputs live in new files.

## 10. Workstream: market regime separation

**Boundary:** documentation, audit and a reporting split. No change to the banner, M07/M10, the 15% halt or any
production behaviour. Any defect found becomes a separate change note needing owner approval under the trial
change policy.

| Item | Content |
|---|---|
| Principle | The banner (NORMAL / DEFENSIVE / NO_NEW_TRADES) decides **whether** to open trades; the model decides **which** stock. Lab candidates are judged on ranking within the day, so market direction cancels out by construction (4.1). |
| Status of the gate | A **risk-control hypothesis**, not proven protection. Evidence so far is exploratory (weakness experiment: nothing adopted; portfolio replay: 15% halt kept). |
| Audit | `2026-10-29-audit-market-gate.md`: look-ahead, inconsistent definitions, replay fidelity, gate mixed into scores. Findings: **see audit summary below**. |
| Lab reporting | Every lab result is also split by the banner state on each decision day (computed point in time, reported only, never a pass rule). |

Audit summary (read-only; details and file:line evidence in the audit file). "The gate" is **14 mechanisms**:
7 live, 7 in replay/evidence tools.

| # | Finding | Class | Prod today? |
|---|---|---|---|
| F1 | Breadth measured over **today's** watchlist for past days (replays, training) | CONFIRMED DEFECT (known) | no (live), yes (replays) |
| F2 | Prod breadth may count a 10-stock watchlist; all gate evidence used 49 | LIKELY | yes |
| F3 | A half-formed daily candle can be stored mid-session (refresh/backfill) and read as today's close | CONFIRMED path; occurrence UNTESTED | only if refreshed in market hours |
| F4 | M10's two-good-days check gets 19 FII days, needs 20 → never sees yesterday's FII selling (errs bolder) | CONFIRMED DEFECT | yes |
| F5 | M10 inputs lose their dates; stale VIX not flagged | LIKELY | possible |
| F6 | Replays don't compute the gate as live does (M04, FII, money ceiling, defaults) | CONFIRMED inconsistency (mostly disclosed) | no |
| F7 | Unknown mode = NORMAL in `portfolio_sim`/`bad_market`, DEFENSIVE live | CONFIRMED (disclosed) | no |
| F8 | v1's 20–85% money ceiling is a second gate, absent from replays | CONFIRMED (disclosed) | no |
| F9 | v1 can buy on a −4% crash day while the brain says NO NEW TRADES | CONFIRMED (by design) — owner decision | yes |
| F10 | 6 market-wide inputs (NIFTY trend/volatility, VIX ×2, breadth ×2) sit **inside** the model score and move all scores together against a fixed buy line | CONFIRMED separation breach | yes |
| F15 | A daytime manual run can file yesterday's-close banner under today; reserved-slot sizing uses the latest banner however old | LIKELY | slightly |
| F11–F14 | "+10-point downtrend boost" raises v1's buy line (not scores); brain banner never changes scores; hindsight `classify_regime` name clash; look-back windows clean | NOT A DEFECT | — |
| F16 | Uncommitted local M07/`risk.py` testing-mode edit lifts the money ceiling and v1 limits in shadow stage | noted, not judged, not on main | — |

**Does the gate protect? (all exploratory):** drawdown — the banner roughly halved the worst fall in 5 windows
chosen *because* markets fell (false-alarm cost never measured); returns — no evidence; contrary signs — every
stock did best when breadth < 30% and M04 crash/bear days had better 15-day outcomes; the 15% halt and the
crash-day rule never fired in any replay. **Verdict: a risk-control hypothesis, unproven.** Nothing already
produced (fd-v1, Phase B, bad_market, the sealed trial) needs re-running or relabelling.

**What the lab does with this:** F10 matters less inside the lab because ranking is judged within the day,
where market-wide inputs are equal for every stock; they are flagged in the section-12 inventory and their
importance is reported. F1 is handled by L8 (watchlist hash) and stated in every report. F3, F4, F5, F9, F15
go to separate change notes (Q11); F4 and F5 touch trial-frozen `brain/modules/**`, so they wait for the trial
change policy. Missing tests listed in the audit (F1, F3, F4, F5, F6) are part of those change notes.

**Acceptance criteria:** (1) one written table of every regime/breadth definition in the codebase with inputs,
thresholds, universe and timing; (2) every look-ahead or inconsistency classified CONFIRMED DEFECT / LIKELY /
NOT A DEFECT with file:line; (3) each defect has a proposed fix naming the protocol/trial it touches;
(4) nothing in production changed.
**Test cases (for any later fix):** gate computed at day *d* from a database truncated at *d* equals the gate
computed from the full database; live and replay paths give the same banner for the same day.
**Implementation impact:** documentation only now; ≈ 1 day per approved fix later.

## 11. Workstream: horizon-specific model scores

**Boundary:** trace and document; no model, threshold or display is changed here. Mismatches are recorded as
defects with proposed fixes; any fix touching the trial, Phase B (B1 uses score ≥ 0.80) or a locked protocol
needs owner approval and does not alter results already produced.

| Item | Content |
|---|---|
| Score register | For every score: producer (file:line), model name and selection rule, version, target (threshold, horizon, entry/exit), training label code, calibration, consumers, and what each consumer assumes it means. |
| Audit | `2026-10-29-audit-model-scores.md`. Findings: **see audit summary below**. |
| Rule going forward | Every score carries `{model_id, version, target, horizon_days, calibration}`; a consumer that needs a 15D probability refuses a 5D score; screens show the horizon next to any score. |

Audit summary (read-only; prod not queried, so prod model ids are LIKELY from earlier documents; five read-only
prod checks listed in the audit would settle them):

- **No code turns a 5-day score into a 15-day probability.** The only "honest chance" display
  (`brain/score_evidence.py`) refuses any model not trained on +8% / −4% / 15 days; screens never show a raw
  score with a % sign.
- **But the brain chooses its 15-day ideas with the 5-day score.** Live brain runs read the active
  `swing_classifier` (`brain/reader.py:460-496`, checked) — per fd-protocol-v1 C1 that is prod model 2, "close
  ≥ +2% after 5 trading days", uncalibrated. That score decides "liked" (≥ 0.60 or the accepted buy level) and
  slot priority; the +8% / −4% / 15-day plan is attached afterwards. This is the known tv23/tv24 gap and is
  **what the sealed trial is actually testing**.
- **M06**, the only true 15-day probability, runs in shadow and very probably has nothing to run on (no active
  barrier model).

| # | Defect | Class | Touches |
|---|---|---|---|
| D1 | 15-day brain ideas selected and prioritised by the 5-day score | CONFIRMED in code; prod model = 5D LIKELY | prod picks, sealed trial |
| D2 | Brain scores mid/small caps with the large-cap model; v1 uses tier models for the same stocks | CONFIRMED | prod picks |
| D3 | A brain decision does not record which model scored it; evidence is chosen by today's active model | CONFIRMED, dormant | trial reporting after tv23/tv24 |
| D4 | "Score ≥ 0.80" means three different numbers (Phase B B1 = per-fold 15D model; trial's "Score 80+" set and the owner's "read score > 80" rule = prod 5D score) | LIKELY (process) | **a B1 pass would not validate the owner's rule** |
| D5 | Different score kinds sorted on one scale (`/signals/picks`, `/top-picks` already mix strategies incl. SMA's made-up 0.5–0.85) | CONFIRMED | live display |
| D6 | Stock-page score trail: last strategy to run wins, incl. the 250-day model | CONFIRMED | display |
| D7 | Positions page uses "the active model" for every position → 15-day positions get "5-day call has passed" notes | CONFIRMED | display |
| D8 | Prod settings likely 5 days / +2%; untagged `swingtrade train`, as-of models and documented `*_barrier_cal` commands would build 5D models — **the tv23/tv24 fix itself would build the wrong model** | LIKELY, high | future training |
| D9–D12 | Signal grading mixes questions; 5D graded on calendar days + slack; long-term text from settings; real-question switch moves bands but not the brain's model | CONFIRMED, low / dormant | v1 path |

Proposed fixes (proposals only, in the audit as F1–F14): record the scoring model on every decision and choose
evidence by it (F1–F3); make training refuse to run without explicit label flags (F5, before F4); the real
tv23/tv24 with explicit 15 / 8% / 4% labels, its own model name, and WAIT when no 15D model exists (F4); route
stocks to tier models (F6); never rank different score kinds together and block M06 activation while the trial
is sealed (F7); display fixes (F8–F12); say on 15-day screens that ideas are ranked by the 5-day model (F13); a
**new** note separating B1's 0.80 from the prod "score over 80" (F14, the locked Phase B file is not edited).
**F4, F6, F7 would change the sealed trial's picks and F3 its reporting** → only after the trial evaluation or
as a new trial, with owner approval. F8, F9, F11, F12 touch the v1 path.

**Label for the sealed trial's evidence (confirmed in prod, `2026-10-29-score-provenance-note.md`):**
"**15-day brain trial — 5-day score (`swing_classifier` v2, id 2: close ≥ +2% after 5 days, uncalibrated) +
15-day trade plan (+8% / −4%, half at +5%, 15 trading days)**". The trial runs unchanged; no existing evidence
record is edited. The label is used in new notes now; putting it on screens (audit F13) is a separate,
owner-approved display change.

**What the lab does with this:** S0 is already a true 15-day model per fold, so the lab compares against the
right question. The lab report states plainly that the live brain does **not** use S0 (it uses the 5D score),
so a lab result says nothing about the trial's picks.

**Acceptance criteria:** register complete for every score reaching M06, M08, signals and screens; each mismatch
classified; no 5D score is shown or used as a 15D chance without a recorded defect.
**Test cases (for later fixes):** a 5D-labelled score passed to a 15D consumer raises; every API score field
includes horizon and model id; display tests check the horizon label.
**Implementation impact:** register = documentation; fixes ≈ 2–4 days once approved, after the trial freeze.

## 12. Workstream: feature reduction (candidate S2r)

**Boundary:** a lab candidate (S2r), inside the lab family of four — **not** a Phase B candidate. Uses
development data only, inside each fold's training window (L7). The held-back 129 are never used to choose
inputs. The production feature list is not changed.

**Inventory (before any data is looked at, from code only):** list the 53 inputs by family (trend, momentum,
volatility, volume, price structure, regime, market, sector, VIX, breadth) and flag look-alikes by construction
(e.g. several moving-average ratios; RSI / stochastic / Williams %R; ROC vs return_10d/20d). Also flag inputs
built from long windows or percentile ranks for a look-ahead check (the market-gate audit found those
windows look back only), breadth inputs built from today's watchlist (confirmed defect, section 1), and the
6 market-wide inputs that are identical for every stock on a day (market-gate audit F10).

**Procedure, fixed now, run per fold on that fold's training rows only:**

1. Drop an input for this fold if > 30% of its training rows are missing.
2. Spearman correlation between all inputs (no labels used). Group inputs where |ρ| ≥ 0.90 (connected groups).
3. In each group, keep the input with the highest |IC| against the training label.
4. **Usefulness check — do not drop on correlation alone:** for each other group member, refit on the training
   window's first 80% with and without it and compare IC on the last 20% (still inside training). Keep it if
   removing it lowers that IC by more than 0.005.
5. The kept list is recorded per fold in `metrics.json`.

**Diagnostics (reported, never pass rules):** missing-value share per input per year; importance rank
stability across folds (Kendall τ between consecutive folds); inputs whose importance flips sign.

**Comparison:** S2r vs S2 under identical folds, stocks, days, trainer and costs; R4 non-inferiority bound
−0.005 (6.3). S3 builds on S2's full inputs, fixed now, whatever S2r shows.

**Acceptance criteria:** procedure code has unit tests on synthetic data (two copies of one input → one kept;
a correlated but useful input → kept by step 4; nothing reads rows after the cutoff); per-fold kept lists
stored; S2r and S2 reported side by side.
**Implementation impact:** ≈ 2–3 days inside Release 1; compute ≈ 2× S2's (step 4 refits).

## 13. Workstream: data integrity and data sources

**Data-integrity audit:** `2026-10-29-audit-data-integrity.md` lists every known data problem, which past
results it could affect (AFFECTED / NOT AFFECTED / UNKNOWN), and what remains. Rule: **sealed or locked
verdicts are never re-run to change them**; a re-run is a new, labelled diagnostic. Summary:

- **No bar has ever been recorded as corrected**, so no past result can be tied to a corrected bar. The
  correction log (`candle_corrections`) started 2026-10-05 and the local database has ingested nothing since
  (last bar 2026-09-09): its 0 rows mean "not checked", not "clean". Overwrites before 10-05 were silent and
  cannot be traced. Prod was not checked.
- **Suspected unadjusted jumps** (price/volume pattern only, not checked against exchange records): ALLCARGO
  (incl. a new −24.8% gap on 2023-04-18), TRIVENI, SANOFI, SCI, BAJAJELEC, VEDL, NMDC, SIEMENS, IDEA; ABFRL
  2025-05-22 possibly a demerger. **None is in the 49**; the two big moves inside the 49 (ADANIENT,
  INDUSINDBK) are real events, and BAJAJFINSV's 2022 split is already adjusted.
- **Confirmed defects, fixed:** breadth counted missing stocks as bearish and signals scored on calendar days
  (`2145a20`); portfolio-replay cash bug (`25c6a6c`); four "bolder on bad data" decision bugs (`99147d8`).
- **Confirmed defect, open:** the split check reads only future events, so its 2026-10-05 "0 suspicious"
  covered almost no history; its advice to deprioritise price adjustment is unsupported.
- **Past results:** every 49-stock result (wf-v1, fd-v1, ranking diagnostics, scoreboard, horizon grids,
  replays, ps-checks) — **not affected** by any known problem; wf-v1 was reproduced exactly after the breadth
  fix (1,980 ideas, −0.204% per trade). **Affected, size unknown, never re-run:** the 2026-09-15 barrier models
  and the 10-08/09 calibrated mid/small-cap models (their training lists hold all 13 flagged stocks) — so the
  "mid/small scores are honest and useful" claim is an untested explanation either way. **Unknown:** the prod
  forward trial (October corporate events fall inside it), M04/M12 evidence scripts.
- **The failures (wf-v1, fd-v1, no ranking, ps12, ps3) are observed failures; blaming bad data is an untested
  explanation with no evidence.**

Consequences for this design (applied in 4.2): 4 of the 128 extra stocks carry suspect jumps (SANOFI,
BAJAJELEC, VEDL, ABFRL); the gap line is lowered from 30% to **20%** (M01's spike line) because 30% misses
ALLCARGO's −24.8%; every flagged gap gets the "unadjusted; affected windows removed" treatment; the data
snapshot (row count + hash) is frozen at the start of each run and a run refuses if it changes mid-way.

**Data sources:** R0 report `2026-10-29-r0-data-feasibility-report.md` (desk research only; nothing bought,
no vendor contacted). Summary:

| Need | Best source found | Point-in-time / public time | Status / cost |
|---|---|---|---|
| Pre-2021 prices incl. delisted | NSE daily bhavcopy (every traded stock that day; 2014 files still online) | yes (daily file) | automated download barred by site terms; licensed historical copy was ₹30,000/yr in the Apr-2025 tariff, line missing in Apr-2026 → quote needed |
| Index membership by date | NSE Indices monthly constituent files | yes | verified: all indices Apr 2013 – Mar 2022, F&O indices only after. **Midcap 150 first appears between Feb 2017 and Jan 2018** → formal cap split for 2014–2017 is NOT TESTABLE without paid history |
| Results as first filed, with time | NSE / BSE filings only | yes (dissemination time, first-filed kept) | no vendor (EODHD, CMIE, ACE, Capitaline, Trendlyne) states either; EODHD has a date, no time → fails L5 unless confirmed in writing |
| "KEI results stop at Dec 2024" | not a lag: NSE retired the old results utility on 1 Apr 2025 (circular NSE/CML/2025/20) → "Integrated Filing – Financials" | — | the comment in `services/company_filings.py` is out of date (documentation defect) |
| Licence for using NSE data in analysis | NSE non-display policy (Mar 2026) | — | separate agreement, price not published |

Cost routes (per year): ≈ **₹35,000 incl. GST** if NSE gives written consent for one-off research use plus the
historical price licence; ≈ ₹6.3–8.4 lakh if NSE's EOD corporate-data product is needed; ≈ ₹11 lakh via BSE
feeds (₹3 lakh each for results, shareholding, calendar); ≈ ₹15–30 lakh for later use in a product shown to
users. Recommended order: (1) NSE historical price licence + written consent from NSE and NSE Indices for
research use; (2) BSE as fallback for company data; (3) EODHD prices only, as a cross-check. The report's
section 10 lists the exact questions to send to each vendor — sending them is the owner's call.

**Terms risk already in production (finding, nothing changed):** `services/company_filings.py` (KEI, weekdays
19:40) and `services/market_feeds.py` (bhavcopy, FII/DII, event calendar, corporate actions, ASM/GSM) collect
from NSE by program every day; NSE's terms bar this with no size threshold. This is the subject of Q8.
Full feed-by-feed inventory with verbatim terms: `2026-10-29-nse-feed-licensing-inventory.md` (all 7 NSE feeds
need consent for any use; Kite Connect terms also restrict virtual/mock trading, permanent databases and display
to third parties; v1 `avoid.py` is fail-open, so stopping a feed would make v1 *less* cautious).

Known constraints: NSE website terms bar automated collection without consent, and its non-display policy
covers data used in automated trading decisions; v1 prod already pulls 7 NSE feeds daily
(`services/market_feeds.py`), so the licensing review (Q8) covers all of them, not only the KEI filings job.
The evidence plan forbids new paid services during Phases A–C (plan section 5); any purchase needs a plan
amendment (Q7).

## 14. Workstream: daily shadow top-5 record

**Boundary: design only. Not built until the C0 technical review is approved.** Changes no pick, order, slot,
size, stop, limit, trial metric or seal.

**What already exists:** the brain stores every nightly ranked idea in its decisions, and `services/shadow_test.py`
follows each ranked stock for 15 days, sealed from 2026-10-14. So the **brain's** daily top 5 is already
recorded independently of slots; nothing new is needed for it, and its results stay sealed.

**What is new:** a shadow record for a candidate that is **not** live (a lab survivor in Stage 3, or Phase B's
survivor if the owner wants it here), in one append-only table `research_shadow_ideas`:

| Field | Meaning |
|---|---|
| lane, protocol tag, model id/version | which candidate |
| decision_day, rank (1–5), score, rank percentile | the idea |
| banner state, breadth, VIX percentile | market at the decision close |
| event flags | results notice within 5 / 15 days (as known at the close), ASM/GSM |
| eligible, slot_free | would the portfolio have had room (recorded, not acted on) |
| hypothetical entry (next open), exit, status, net result | filled by the scorer after 15 days |
| `kind` = `shadow` | never `trade` |

Rules: one record per stock at a time (no repeats until finished); recorded whether or not a slot is free;
results hidden until the Stage 3 verdict (counts only), like Phase C; **never summed with portfolio trades,
never called profit**; nothing reads this table except the lab report and the owner screen.

**Acceptance criteria:** a test proves no decision/order/risk module imports the table or its writer; a test
proves the record is identical with slots full or empty; counts match the candidate's daily top 5; seal test.
**Implementation impact:** ≈ 3–5 days after C0; ~1 minute a night on prod.

## 15. Owner/tester screen, API, 10D

Observatory tab **"Selection lab"** — read-only, owner and tester only, seal-aware (Stage 3 and shadow rows show
counts only until the verdict), plain English. No customer screen until D0a is verified.

| Part | Shows |
|---|---|
| Experiment list | S0–S3, S2r, F1: stage, label (6.5), verdict, date, run id |
| Result card | two boxes: **"Does it pick better stocks?"** and **"Does it make money after costs?"**, each vs random, momentum, S0, every stock, NIFTY, with sample size and "could be as low as …" |
| Score bands | top 5% / next 15% / rest: picks, different days, "out of 100 picks in this band, about N hit +8% first" — from out-of-fold predictions via `fit_honesty` (≥ 20 different days, else "too few days to say") |
| By market state | results split by banner state (reporting only) |
| Large vs mid cap | 6.4 split with its badge |
| What went wrong | worst 3 folds with market type, biggest losing trades, stocks > 20% of profit |
| Earnings exposure | open paper positions with results before their 15-day exit (symbols and dates) |

Scores are shown as **rank that day (0–100)**, never as a probability. Every page: *"Past results do not promise
future profit. A high score has never been proven to make money."*

API (GET only, owner/tester auth): `/api/v1/research/selection-lab/runs`, `/runs/{run_id}`,
`/runs/{run_id}/bands`, `/api/v1/research/earnings-exposure`.

**10D:** not in this protocol. The runner takes the horizon as a setting; a 10D run later is a new signed
protocol (`td-protocol-v1` stays unsigned), considered only if a 15D candidate passes Stage 1.

## 16. Effort, compute, cost, risks

| Release | Content | Effort (dev-days) | Money |
|---|---|---|---|
| 0 | Audits (done, read-only) + sign protocol before 9 Nov | 1 | ₹0 |
| **1** | After 4 Dec: `selection_lab.py`, label, data gate, new scorer, S0/S1/S2/S2r Stage 1, feature inventory | 7–10 | ₹0 |
| 2 | R0 → owner decision; licensing review of all NSE feeds | 1–2 | ₹0 (quotes) |
| 3 | Research tables + importers + L6 test; S3; F1 forward; earnings exposure | 9–14 | per Q7 |
| 4 | Owner screen + API | 4–5 | ₹0 |
| 5 | Stage 2 (if data) and Stage 3 shadow (after C0, when the 15D slot is free) | 5–8 | ₹0 |
| — | Fixes for confirmed defects from sections 10–11 | separate change notes | ₹0 |
| | **Total** | **≈ 27–40** | |

**Compute:** ~180k training rows; inputs rebuilt per stock per fold make a candidate's Stage 1 about 1–3 hours
on the laptop (S2r ≈ 2×). All of Stage 1 ≈ one working day of machine time. No cloud, no new servers.

| Risk | Likelihood | Response |
|---|---|---|
| New target also ranks no better than chance | high | stop rule; points at inputs/data |
| Picks beat others but lose money in falling markets | medium | separate verdicts; banner handles market direction |
| NSE licensing blocks the cheap route | medium | Q8; licensed or vendor route |
| Plan forbids paid data until Phase C ends | certain | Q7 amendment or wait |
| Fundamentals restated, not as-filed | medium | L5 |
| Development data over-used | certain | Stage 1 warns only; PASS only forward |
| Held-back set worn down | low | 4 uses in total (Phase B 3 + lab 1, winner only); logged; reject-only |
| Forward slot contention with Phase B | medium | D5 queue |
| Scope creep | medium | family of four, frozen |

## 17. For your approval

| # | Question | My recommendation |
|---|---|---|
| Q1 | Sign `sl-protocol-v1` before 9 Nov; execution waits for a separate GO after 4 Dec? **Note:** the evidence plan has no phase for this lab (after Phase B it allows Phase C or the December go/pivot/stop review only), so signing the rules is a pre-registration; permission to *run* needs a separately signed evidence-plan amendment, decided at or after the December review | Owner: CONDITIONAL (2026-10-29) |
| Q2 | Approve the target in 4.1 (top 30% of 15-day excess vs the 49's median)? | **Approved 10-29** |
| Q3 | Approve the 8 company inputs in 4.3? | **Approved 10-29 for design/definitions only**; use needs B3 |
| Q4 | Approve pass rules 6.3 (1.25% bound for 4 candidates; S2r non-inferiority −0.005)? | **Conditional yes 10-29**; clarifications written in 6.1/6.2 — awaiting final yes |
| Q5 | One lab use of the 129, on the preselected winner only (4 uses in total incl. Phase B), each logged? | **Approved 10-29** (winner only, no fallback) |
| Q6 | Execute Release 1 after 4 Dec? | **Not before the evidence-plan amendment is signed** (owner 10-29); pre-registration (Q1) is separate |
| Q7 | Paid data: amend the evidence plan to allow a purchase after R0, or wait until Phase C ends? | Decide after R0 quotes |
| Q8 | Licensing review of all 7 NSE feeds + KEI job now? | Yes |
| Q9 | Approve the feature-reduction procedure in section 12 as candidate S2r? | **Approved 10-29** |
| Q10 | Approve the shadow-record design in section 14 for C0 technical review (not build)? | **Approved 10-29** |
| Q11 | Defects from the audits (sections 10, 11, 13): written as separate change notes for your approval? | **Approved 10-29** |
| Q12 | Run the five read-only prod checks? | **Approved and done 2026-10-29** — D1, D2, D4, D8 confirmed in prod; see `2026-10-29-score-provenance-note.md` |
| Q13 | Record that B1's "0.80" is not the prod "score over 80"? | **Approved and done 2026-10-29** — `2026-10-29-score-provenance-note.md` |

## 18. Calls made by me (check these)

- S0 is the **raw 15-day barrier model** per fold (Phase B decision 3) — never called M06, never the prod
  5-day model.
- Turnover = close × volume from candles; ₹5 crore applied only to the label's reference group.
- Top 30%, the 8 inputs, the 0.90 correlation line, 30% missing line, 0.005 usefulness and non-inferiority
  margins, the 5-day filter window: set from first principles, not results; changing any is a new protocol.
- Stage 2 test window 2016-01 → 2021-07 (needs 2014 data for warm-up).
- Tables live in the public schema as `research_*` (Alembic has no schema support), local-only until Stage 3.
- Not committed yet: the current branch holds unrelated work; on approval this goes on its own docs branch.

Signature (owner): ____________________  Date: __________
