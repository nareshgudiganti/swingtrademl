# Evidence and pilot plan — prove, measure, then test demand

Status: **FROZEN 2026-10-15.** Adopted by the owner, final review and three final corrections applied the
same day. Changes only if new evidence reveals a material problem, recorded in section 7. **Phase A
approved and started. Phase B approved on condition** that the stock split and `wf-protocol-v2` are locked
first; no Phase B model is built yet. Trial freeze unchanged. Numbers marked
*proposed* need the owner's confirmation **before** Phase B results are looked at; after that they only
change through a new dated entry in section 7.

Tracker: System Atlas → Pending work → section "Evidence plan" (ev).

## 0. Ground rules

- Paper only. `TRADING_MODE` stays `paper`; no real orders anywhere in this plan.
- The trial freeze (2026-10-14) holds: nothing here changes which stocks are picked or how orders are
  placed during the trial. Research runs offline; the Observatory is read-only.
- Rules before results. Every test is locked (written, committed, tagged) before it is run. A failed result
  stays on record; a re-run with new rules is a new protocol version.
- The next investment is **evidence, not more brain modules**. No new modules until a decision review asks
  for one.

## 1. Where we start (facts, 2026-10-15)

| Fact | Source |
|---|---|
| Frozen test `wf-protocol-v1` failed: beat random in 7 of 21 blocks, profit in 9 of 21 | `docs/brain/evidence/wf_v1/` |
| The score barely ranks stocks: same-day rank correlation +0.011 (lower bound −0.015) | `docs/brain/evidence/ranking_diag/` |
| Only lead: score 0.8–1.0 → 885 ideas, +0.62% average, 33% hit, 12 folds — found by looking, so a guess | same |
| Prod paper starting balance is correct (₹9,79,792, measured since 2026-09-28) | prod `/portfolio/summary`, checked 2026-10-15 |
| Prod drawdown halt already measures from the trial's own peak | commit `9ac2e8e` |
| Stored `drawdown_pct` on prod snapshots 2026-09-28..10-09 was measured from the old peak (≈2% too high; errs toward caution) | prod `/portfolio/equity-curve`, checked 2026-10-15 |
| The "+435%" balance bug is **local only** (local `.env` `PAPER_STARTING_CAPITAL=200000` + stale snapshots) | memory note, prod check above |

## 2. Phase A — Repair and measure (start now; target 2026-11-06)

All read-only or reporting. Allowed under the trial freeze.

| # | Task | Done when |
|---|---|---|
| A1 | **Balance reconciliation record.** Write `docs/brain/evidence/paper-balance-reconciliation-2026-10-15.md`: prod numbers, the 09-28..10-09 old-peak rows, the fix commit, the local-only cause. **No snapshot row is overwritten**; screens already recompute from the trial window | file committed; a test pins that trial drawdown ignores pre-trial peaks (exists from `9ac2e8e`, confirm) |
| A2 | **Observatory Phase 1A**, answering only four questions: what was decided, why, what happened, compared with what. Scope = Observatory spec rev 4 section 10 | spec section 10 "done means" met; deploy approved separately |
| A3 | **One source of truth.** Dashboard, Brain Logs, Performance and Observatory read finished-idea results from one function (brain decisions + `services/costs.py`). The function takes the category (backtest / paper / practice) as a required input and never mixes them; stored evidence files are never edited, only added to | no screen computes its own idea P&L; a test proves categories are never summed |
| A4 | **Baselines in every report**, exactly as defined in section 3a (`evidence-defs-v1`): trade-level matched baselines and equal-capital portfolio baselines with the risk report. Built only after 3a is locked | shown side by side in the Observatory and the monthly pack |
| A5 | **Monthly evidence pack**: backtest, paper, practice in separate labelled sections, never summed; ideas, outcomes, fees, drawdown, baselines | first pack for October 2026 |

## 3. Phase B — Limited research experiment (2026-11-09 to 2026-12-04, 4 weeks)

Offline only. Development data = the "seen" sample 2025-02-01..2026-08-15 (49 stocks), plus a robustness
check on never-used stocks. **The robustness check only rejects candidates; it never confirms one.**

**Stock split, fixed before any run:** the 257 never-used stocks are split once, by stock, with a recorded
random seed, into:

- **reject set** (129 stocks): never used to train **any** candidate; used only for the robustness check
- **extra training set** (128 stocks): used only by B2

The seed, both lists and their file hash are committed before the first Phase B run.

Exactly three candidates, each with fixed settings written down before it is run, **one run each, no
retuning**:

| # | Candidate | Fixed setting | Extra thing to report |
|---|---|---|---|
| B1 | Trade only on high score | score ≥ 0.80, otherwise no trade that day | ideas per week (coverage) |
| B2 | Wider training set | train on the 49 + the 128 extra stocks (177), score the same 49 on the same dates; the reject set is never in its training data | data quality, survivorship note, leakage check (no reject-set stock in any training fold) |
| B3 | Buy only after market weakness | model's best 5, **only** on days when the breadth signal (defined below) is under 30%; otherwise no new trades. Same signal as `weakness_experiment_2026-10-12.md` (B5). The 30% line was chosen on this data, so it is not out-of-sample | losses avoided **and** profitable trades missed on the other days; how many days a year it trades |

A candidate survives Phase B only if, on development data, it beats **both** every-stock and momentum on
average result per trade after costs, **and** is not worse than every-stock on the reject set.

**B3 breadth signal (candidate setting; locked with `wf-protocol-v2`).** At the decision day's close: the share of the 49 watchlist stocks whose close is
above their own 50-day simple average of closes, counting only stocks with at least 50 closes. Market-weak
= under 30%. The same signal is used on the reject set (breadth is a market signal, always from the 49).

**Stop rule:** if no candidate survives, Phase C is skipped and the decision review (section 6) happens
in December. No fourth candidate is invented.

The single best survivor is locked as `wf-protocol-v2` (rules, settings, code commit, tag) by 2026-12-04.

## 3a. Fixed definitions — baselines and calculations (locked 2026-10-15, before A4)

This section is locked now, before task A4 is built, and is versioned as `evidence-defs-v1`. It holds only
baseline and calculation definitions. **Candidate-specific settings** (score threshold, training stocks,
breadth line, model parameters) are not here; they are locked later in `wf-protocol-v2` (section 3). A change
to this section is a new dated entry in section 7 and a new `evidence-defs` version; results already
produced keep the version they were made with.

**Decision timing.** Every signal uses only data known at the decision day's close (IST date of the daily
candle). Entry is at the next trading day's open. Nothing from the entry day or later is used.

**Matched baselines.** Every baseline uses the **same decision days, the same next-open entry, the same exit
rule** (+8% / −4% / half out at +5% / 15 trading days), **the same cost and slippage model**
(`services/costs.py`) and the same stock list as the candidate:

| Baseline | Definition |
|---|---|
| Every stock (matched random) | every stock in the list on each day the candidate trades |
| Random 5 | 1,000 seeded draws of 5 random stocks on each day the candidate trades (gives the share of draws the candidate beats) |
| Momentum | the 5 stocks with the highest 20-day return at the decision close (`walk_forward.momentum_scores`), same days |
| NIFTY, matched holding period | for each candidate idea, NIFTY 50 over the same entry open to that idea's exit day, with the same costs as one stock trade. **A trade-level comparison only: its exits depend on the candidate's trades, so it is never presented as an index strategy anyone could run** |
| Cash | 0% |

**Two levels of comparison.** Both are reported; neither replaces the other.

1. **Trade level (matched):** the table above. Per-trade results, unconstrained by capital.
2. **Portfolio level (equal capital, independently executable):** each strategy below starts with the same
   capital on the same first day and runs on its own rules only, with no input from the candidate's trades, through the same point-in-time portfolio replay (`brain/portfolio_sim.py`): the
   ladder limits, the 25% sector cap, the 15% drawdown halt, and the cost and slippage model.

| Portfolio strategy | Rule (decided only from data known at each decision close) |
|---|---|
| Candidate | the candidate's ideas |
| Random 5 | 5 random stocks a day from the same list, every trading day; 200 seeded runs, results given as median and 5th–95th percentile |
| Momentum 5 | the 5 strongest 20-day risers every trading day |
| NIFTY buy and hold | the whole capital in a NIFTY 50 index fund on the first day's open, held to the last day, one round trip of costs (ETF delivery costs) |
| Cash | 0% |

Random 5 and Momentum 5 trade every day, not only on the candidate's days, so they do not depend on the
candidate.

**Portfolio risk report.** For each portfolio strategy:

| Reported | Meaning |
|---|---|
| Maximum drawdown | the largest fall from a running peak of account value, in % |
| Halt triggered | yes / no: did the 15% drawdown halt stop new entries |
| Time halted | trading days with new entries halted |
| Final net return | ending account value vs starting capital, after all costs, in % |

The drawdown pass rule (section 4) uses the candidate's maximum drawdown and is shown next to the same four
numbers for every baseline.

**Daily aggregation.** For each decision day the candidate trades: day result = average net result of that
day's ideas; day edge = day result minus every-stock's average on that day. Days without a candidate idea
are left out (coverage is reported separately).

**Confidence method.** Lower bound = 5th percentile of the mean day edge, by block bootstrap over runs of
15 consecutive trading days, 2,000 draws, seed 7 (`walk_forward.bootstrap_low`, as in wf-protocol-v1).
Fewer than 30 trading days with ideas → **Insufficient evidence**.

**Market types.** Labelled after the fact, for reporting only (never used for decisions): for each 28-day
fold, the average move of the 49 stocks from the fold's first to last close; over +3% = rising, under −3% =
falling, otherwise sideways (`walk_forward.classify_regime`).

## 4. Phase C — Independent validation (from the lock date)

**Confirmation data = trading days after the `wf-protocol-v2` lock.** Nothing before the lock counts as
confirmation.

- The locked candidate is scored every trading day as a **shadow record only** (no effect on picks or
  orders), on every stock whose daily prices prod keeps. More stocks → evidence builds faster.
- **C0** is a read-only check of which stocks prod keeps daily prices for. Writing shadow scores is a
  separate step: an isolated, append-only shadow store that no decision, strategy or order code reads.
  It gets a **technical review** (what it writes, proof that picks and orders are unchanged) and an owner
  decision under the trial change policy before it runs. The trial freeze itself is not changed.
- **Fixed evaluation horizon, no early stop:**
  - **3 months:** working-order check only: counts, errors, missing days. **Returns are not looked at**,
    and the candidate's shadow returns are kept out of the Observatory and the monthly pack until the
    verdict.
  - **Verdict at exactly 6 months** after the lock date.
  - If fewer than 100 finished ideas exist at 6 months, there is **one** pre-set extension to exactly
    9 months. The extension depends on the idea **count** only, never on results.
  - At 9 months the verdict is given whatever the count. Under 100 finished ideas = **Not proven**.

### Pass rules (*proposed* — owner to confirm before Phase B results are seen)

All must hold on the confirmation data:

| Check | Pass when |
|---|---|
| Net return | average per trade after costs and slippage > 0 |
| Baselines | trade level: beats every-stock (matched random) and momentum on average per trade, and NIFTY over the matched holding periods; portfolio level: final net return above the Random 5 median, Momentum 5, NIFTY buy and hold and cash |
| Statistical confidence | lower bound of the mean day edge over every-stock > 0 (method in 3a) |
| Drawdown | candidate's maximum drawdown in the portfolio replay (3a) under 15%, reported with halt triggered, time halted and final net return, next to every portfolio baseline |
| Market conditions | no market type (3a definition, with at least 3 folds) averages worse than −1% per trade after costs |
| Coverage | at least 100 finished ideas, and at least 1 idea per week on average |
| Consistency | still profitable after removing the best 5% of trades; no single stock gives more than 20% of total profit |

The **30-finished-idea forward gate** (layer-2 draft 5a) stays as an **operational smoke test only**: it
checks the brain works end to end on paper. It is never evidence of skill and never by itself allows real
money. Real money additionally needs Phase C to pass and the owner's go-ahead.

## 5. Phase D — Customer and business validation (only after Phase C passes)

**Early regulatory step (D0a, now, not after Phase C):** an initial assessment by a SEBI compliance
professional of where the line is under the Research Analyst regulations and their amendments, **before**
any externally visible research feature is designed. A free pilot is not automatically exempt. It also
covers whether the current tester set-up (Vijay's test) is within that line. No outside-facing feature is
designed until D0a is in hand.

| # | Step |
|---|---|
| D0b | Detailed written opinion from a SEBI compliance professional on the exact pilot design, before any outside user sees it |
| D1 | Pilot: 5–10 invited users, free; research / education view; ideas shown only after they finish; honest track record |
| D2 | Safeguards: consent + disclaimer, payments switch off, no broker link for testers, data deletion, tester accounts kept out of the paper book |
| D3 | Measure: screens opened, explanations tapped, return visits; 5-question weekly check-in (Vijay workbook format) |
| D4 | Ask about willingness to pay; take no money before D0b allows it |

Vijay's 4-week manual test (from 2026-10-15) continues as a usability check; it is not a demand test.

No spending increase during Phases A–C: no new paid services or infrastructure. The ₹50,000/month figure is
a future commercial scenario, not a current budget.

## 6. Decision review — go / pivot / stop

Four questions, answered with evidence:

| Question | Gate | Answered by |
|---|---|---|
| Accuracy: does the analysis beat reasonable alternatives? | **Research validation** | Phase C verdict |
| Reliability: does it run without hidden errors or misleading reports? | (part of every gate) | Phase A, Observatory, monthly packs |
| Usability: can someone new use it with confidence? | **Product validation** | Phase D pilot |
| Commercial viability: will enough people pay to cover acquisition, compliance and running costs? | **Business validation** | a separate test, defined before it starts; 5–10 testers cannot answer it |

The business-validation test needs a larger sample than the pilot (for example a waiting list or a priced
pre-order survey) and is designed only once D0a/D0b allow outside-facing activity. Its pass numbers are set
before it runs.

Readiness checklist (a box is ticked only with a committed evidence file):

- [ ] Beat meaningful baselines on genuinely new data (Phase C)
- [ ] Risk and drawdown inside the predefined limits (Phase C)
- [ ] Forward results reproduce the advantage (Phase C)
- [ ] Reports reconcile, with no hidden errors (Phase A onward)
- [ ] Users understand and repeatedly use the product (Phase D, product gate)
- [ ] Enough people would pay to cover costs (business gate)
- [ ] Commercial use has an approved regulatory path (D0a, D0b)

| Outcome | Decision |
|---|---|
| Strong independent evidence + demand | pursue compliant commercialisation |
| Weak prediction + reliable, usable product with demand for research tools | pivot to analytics / education ("avoid bad trades, when to stay out") |
| Weak prediction + no demand | stop expansion; maintenance only |

Review dates: **December 2026** (if Phase B finds nothing), otherwise at the Phase C final verdict
(≈ June 2027), hard stop ≈ September 2027.

## 7. Change log

| Date | Change |
|---|---|
| 2026-10-15 | Plan adopted with the outside review's five changes: unused stocks reject only; stricter pass rules; strict candidate controls; Observatory = four questions, one source of truth; stop conditions |
| 2026-10-15 | Final review applied: fixed reject set excluded from all training (B2 trains on 177, not 306); fixed evaluation horizon with no early stop, returns hidden until the verdict; point-in-time breadth definition; matched baselines with the same days, entry, exit, costs and capital limits; locked daily aggregation, confidence method and market-type definitions (3a); early regulatory assessment D0a; separate product and business gates; C0 shadow store needs a technical review instead of a blanket ban. Phase A approved; Phase B approved on condition that 3a is locked first; trial freeze unchanged |
| 2026-10-15 | Three final corrections: (1) 3a split into baseline/calculation definitions locked now as `evidence-defs-v1` before A4, with candidate settings left to `wf-protocol-v2`; (2) matched trade-level baselines kept, equal-capital independently executable portfolio comparisons added, and the matched NIFTY exit labelled as a comparison, not an index strategy; (3) portfolio risk report: maximum drawdown, halt triggered, time halted, final net return, for the candidate and every baseline. **Plan frozen.** Phase A started |
| 2026-10-21 | Amendment 1 adopted (`2026-10-21-evidence-plan-amendment-1.md`, tag `evidence-defs-v2`): four result labels (PASS / FAIL / INCONCLUSIVE / NOT TESTABLE); Rules-only, Model-only and risk-matched random comparisons; human picks never count; blind trial results sealed in the backend (counts only, PR #43); sample size and confidence on every number; evidence manifest; horizons never mixed; provisional pause rules (ps7); pass-rule definitions. Changes nothing already run. Seeded stock split locked (ev15: seed 7, reject set 129, extra training set 128, PR #41) |
