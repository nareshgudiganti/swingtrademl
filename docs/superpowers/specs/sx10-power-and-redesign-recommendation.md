# SX10: power, duration, and a redesign / expand / defer recommendation (DRAFT, unsigned)

Date: 2026-11-04 (owner request). Status: **analysis only. Nothing signed, nothing committed. The locked holdout and the dataset eligibility are untouched and were not used to improve power.**
Code and results: `backend/scripts/sx_mde_estar_analysis.py`, `docs/brain/evidence/sector_prep/sx_mde_estar_v1.json` (companion note for SX5: `sx5-mde-and-estar-justification.md`, same method and seeds).
No model fitted, no arm evaluated, no holdout-period outcome computed. Labels: **MEASURED**, **ASSUMED**, **PROPOSED**.

> **STATUS 2026-11-04 (owner): SX10 is DEFERRED.** Its power is insufficient. It is **not authorised** for confirmatory training or holdout testing: no training, no holdout use, no registry authorisation. It can be revisited only through a **new protocol id**. The locked holdout is **not changed to improve power**. The raw 10-session return calculation text (section 4) is kept as written.

> **UNITS (fixed wording; full table in `sx5-units-gross-net-and-idea-rule.md`).** The quantity is the daily paired difference D_t = (C_56 daily top-5 excess return) minus (A_53 daily top-5 excess return). A daily top-5 excess is the mean forward 5-session return of that day's 5 picks minus the mean forward 5-session return of all eligible stocks that day, written as a FRACTION of the money in a trade: 0.0017 = 0.17 percentage points (pp) = 17 basis points (bps) of one 5-session holding return. Because the daily value is already an average over that day's ideas, "per day" and "per trade" are the same number. Nothing is annualised. MDE_H = 0.0018 means 0.18 pp (18 bps) of one holding return, per trade; typing 0.18 would mean 18 percentage points per trade (100 times too large), and the verdict code refuses any MDE_H >= 0.02 ("looks like percentage points: pass a fraction") and any unit tag other than `fraction_of_return`; `mde_h_from_pp(0.18)` gives 0.0018. SX10 would use the 10-session return. The primary quantity is GROSS (no costs; entry at the decision-day close); costs and the net reading are in the same note, section 2.

## 1. Plain-English summary and recommendation

1. **SX10 as drafted cannot answer the question it asks.** On the counted series (30 folds, 565 days) the gain it can reliably see is **0.25 pp per trade** (rule R1 + R2; **0.27** for the full word PASS including the holdout check), against an assumed realistic gain of 0.03 to 0.13 pp. At a true gain of 0.05 / 0.10 / 0.13 pp the chance of PASS is **5.5% / 16.8% / 25.3%** (central assumptions). In the pessimistic corner it is 3.6% / 5.8% / 8.8%; in the optimistic corner 10% / 36% / 56%.
2. **Waiting longer does not rescue it in any practical time.** To reach 80% power at 0.13 pp the series would need about **2,000 to 2,140 trading days (8 to 8.5 years)**; at 0.10 pp **3,500 to 3,700 days (14 to 15 years)**; at 0.05 pp about **13,900 days (55 years)** (central). Even in the optimistic corner: 850 to 1,000 days (3.4 to 4 years) at 0.13, 5.5 to 6 years at 0.10, about 23 years at 0.05. The pessimistic corner is out of reach at every size.
3. **A hidden trap in the rule.** R1 ("at least 60% of folds positive") with fold length fixed at about 19 days **does not get easier with more data**: with 19-day folds a true gain of 0.05 pp makes a fold positive only about 56% of the time (SX5; 54% for SX10), so the 60% bar is missed more often as folds multiply (SX5 central: 6,500 days give power 80% by R2 alone but only 6% by R1 + R2 at 0.05 pp). A longer test must keep 30 folds and make each fold longer. This applies to any extension of either protocol.
4. **Recommendation: DEFER SX10.** Do not run SX10 in this round; do not change its dataset, folds or holdout; do not "fix" power by adjusting the rule. Keep the draft on file as deferred, not rejected. Run SX5 (the stronger test, minimum detectable gain 0.17-0.18) as the single sector screening test. EXPANDING (a wider stock list) is a new protocol with a new id, not a change to this one, and would be justified only on its own merits. A REDESIGN to a forward-only design is legitimate but, because of items 1 and 2, would take years to resolve a realistic gain, so it is not a near-term route either (section 6). Un-defer conditions are in section 8.
5. **Cost of running now versus waiting (register arithmetic, section 7).** Running SX10 adds a second use of the same 133-day holdout window and a 12th (instead of 11th) programme comparison: the chance of at least one lucky pass across the programme rises from 43.1% to 46.0% (about 3 points), for an experiment whose most likely printed word at a realistic gain is FAIL (a weak statement: "a gain of 0.27 or more is unlikely") or INCONCLUSIVE.
6. **If the owner still wants a 10-day number**, the zero-cost option is a descriptive companion inside the SX5 work: record the raw 10-session return of the SX5 picks as a labelled diagnostic with no weight. That answers a different question (does the 5-day ranking carry over to 10 days), consumes no extra holdout use and no extra comparison.

## 2. Corrected power for SX10 (counted series: folds 4-33, 565 days)

Central = persistence phi 0.5, arm correlation rho_AC 0.8 (ASSUMED). 2,000 simulations per cell, 2.5% single-horizon bound, R1 at 18 of 30 folds, R4 simulated with 133 holdout days. Brackets: Monte Carlo 95% range.

| Assumption | R2 alone | R1+R2 | **PASS rule (R1+R2+R4)** | Standard error of mean D |
|---|---|---|---|---|
| Central | 0.241 | 0.247 [0.242, 0.253] | **0.268** | 0.087 pp |
| Central, replicate seed | 0.240 | 0.247 | 0.271 | 0.087 |
| Central on all 34 folds (642 days, not the counted series) | 0.228 | 0.242 | 0.265 | 0.084 |
| Optimistic (0, 0.95) | 0.154 | 0.158 | 0.171 | 0.055 |
| Pessimistic (0.9, 0.5) | 0.510 | 0.520 | 0.567 | 0.189 |
| Sticky picks (0.9, 0.8) | 0.366 | 0.374 | 0.419 | 0.139 |
| Independent picks (0, 0.8) | 0.209 | 0.214 | 0.230 | 0.075 |

Probability of the word PASS at a true paired gain (central; optimistic; pessimistic), %:

| True gain (pp) | 0.02 | 0.05 | 0.10 | 0.13 | 0.16 | 0.20 | 0.30 |
|---|---|---|---|---|---|---|---|
| Central | 1.8 | 5.5 | 16.8 | 25.3 | 37.5 | 53.5 | 87.6 |
| Optimistic | 3.5 | 10.4 | 35.6 | 55.8 | 74.6 | 90.0 | 99.7 |
| Pessimistic | 1.9 | 3.6 | 5.8 | 8.8 | 11.8 | 16.5 | 32.6 |

False-PASS under no effect: 0.9% to 1.4% (R1 + R2 + R4); R1 + R2 alone 2.5% (nominal 2.5%).

Outcome words (central, full rule, MDE_H as shown; PASS / FAIL / INCONCLUSIVE, %):

| True gain | MDE_H 0.16 | MDE_H 0.25 | MDE_H 0.30 |
|---|---|---|---|
| 0 | 0.9 / 60.2 / 38.9 | 0.9 / 88.6 / 10.4 | 0.9 / 95.6 / 3.5 |
| 0.05 | 5.5 / 39.5 / 55.0 | 5.5 / 75.4 / 19.1 | 5.5 / 86.2 / 8.3 |
| 0.10 | 16.8 / 20.3 / 62.9 | 16.8 / 55.7 / 27.5 | 16.8 / 70.6 / 12.7 |
| 0.16 | 37.5 / 6.8 / 55.7 | 37.5 / 30.9 / 31.6 | 37.5 / 45.6 / 16.9 |
| 0.30 | 87.6 / 0.0 / 12.4 | 87.6 / 2.0 / 10.4 | 87.6 / 4.4 / 8.0 |

Reading: with SX10 the word FAIL, at any MDE_H that is power-consistent (about 0.27), would be printed in about 75% of runs at a realistic 0.05 pp and its meaning is only "a gain of 0.27 or more is unlikely". FAIL does not mean the inputs do nothing. SX10 has a fixed disadvantage over SX5 of a factor about 1.5 (noisier 10-day returns, 20-day blocks, more overlap).

## 3. How long would a forward test have to run?

Setup: the same decision procedure on a longer counted series, **no burn-in and no holdout** (forward design, R4 replaced by the forward nature of the data), true gain constant, central assumptions unless stated. "R2 only" = lower 2.5% bound above zero; "R1+R2, 30 folds" = same plus 60% of 30 folds positive with folds lengthened to T/30 days. Interpolated between simulated lengths 565, 1,000, 1,500, 2,250, 3,000, 4,500, 6,500 days (600 simulations each, so each figure is +/- about 10%). Analytic = normal theory with the measured standard error falling as 1/sqrt(T). Months = trading days / 21; years = days / 252.

**Trading days for 80% power**

| Edge | SX10 R2 only (sim / analytic) | SX10 R1+R2 (30 folds) | SX10 years (R2 only) | SX5 R2 only (sim / analytic) | SX5 R1+R2 (30 folds) |
|---|---|---|---|---|---|
| 0.13 pp | 2,010 / 2,056 | 2,140 | 8.0 (96 months) | 949 / 934 | 1,000 |
| 0.10 pp | 3,675 / 3,475 | 3,656 | 14.6 (175 months) | 1,513 / 1,578 | 1,615 |
| 0.05 pp | not reached by 6,500 / 13,900 | not reached | 55 | 6,481 / 6,313 | not reached by 6,500 |

Optimistic corner (phi 0, rho_AC 0.95): SX10 R2 only 849 / 1,376 / 5,750 days at 0.13 / 0.10 / 0.05 (3.4 / 5.5 / 23 years); SX5 565 or fewer / 727 / 2,743. Pessimistic corner: SX10 analytic 8,905 / 15,049 / 60,196 days (35 / 60 / 239 years); SX5 3,309 / 5,592 / 22,368 days.

**With R1 on fixed 19-day folds the picture is worse:** SX5 central power at 0.10 pp by R1 + R2 is 38% at 565 days, 62% at 1,500, 72% at 3,000, 76% at 6,500 days: it plateaus (R2 alone reaches 100%). The reason: fold-mean noise is about 0.33 pp, so P(fold positive) = Phi(0.10 / 0.33) = 62% at 0.10 pp and 56% at 0.05 pp; the 60% bar is a coin flip at 0.10 pp and unreachable below 0.085 pp, no matter how many folds are added.

**(a) Answer.** For the realistic range, a forward test would have to run roughly: at 0.13 pp 8 years (SX10) or 4 years (SX5); at 0.10 pp 15 years or 6 years; below 0.05 pp longer than any programme lifetime. One year (250 days) gives SX10 power 5.7% / 11% / 16% at 0.05 / 0.10 / 0.13 pp (analytic, R2 only) and SX5 8% / 20% / 30%.

**(b) Is a longer forward shadow lane the only route?** Within the fixed 47-stock cohort and the fixed development window, yes: more days can only come from the future, because the development series is fixed at 565 counted days (642 with burn-in) and the holdout adds 133 once. The other levers are (i) a wider cohort of stocks and (ii) a different hypothesis, both new protocols (section 5). Breadth would help in principle: for the same rank skill (IC) the expected top-5 excess grows with the mean of the top five of n standard normals: 1.68 (n = 47), 2.02 (100), 2.19 (150), 2.46 (306), i.e. +20% to +47% edge per unit skill at unchanged day count (ASSUMED; day-to-day noise would also change). That is a new experiment on a different universe, not an amendment, and the cohort question (survivorship, Limitation U) would have to be solved first.

## 4. The primary quantity: raw 10-session return, exact calculation text

**Harness check (VERIFIED in code).** `ml/features.build_label` computes `future_close = close.shift(-horizon_days)` and `forward_return = future_close / close - 1` on each stock's own daily frame; `ml/sector_research` carries `forward_return` unchanged; `ml/sector_walkforward._day_metrics` takes `top_ret = mean(forward_return of the 5 highest scores)`, `all_ret = mean(forward_return of all eligible stocks)` and writes `excess_vs_all = top_ret - all_ret`; `ml/sx_verdict._paired_days` forms `D = excess_vs_all(C_56) - excess_vs_all(A_53)` on identical dates. **The harness field is `daily[].excess_vs_all`.**

**Differences between the owner's brief and the harness.** (1) The brief says "entry at next open"; the harness enters at the **decision-day close**, not the next open (`close`, not `open`). (2) "Session" in the harness is the 10th row of that stock's own bar series after the decision day (same as the 10th market session unless the stock skipped a session; the h05 lane uses market sessions, the harness does not). (3) No costs, no stop, no target. (4) Training label is the barrier label; the primary quantity is not. (5) Prices are as stored (adjustment status not re-verified here). The text below therefore describes **entry at the close of the decision day**; if next-open entry is wanted, the harness field would have to change (new code, hashes, power run: option (b) of D-Q10).

> **S-1 (SX10), exact calculation (PROPOSED text).** Let t be a decision day with at least 10 eligible stocks, E_t the set of those stocks, and C(i, t) the close of stock i on day t. For stock i let C(i, t+10) be its close on the 10th trading session after t (the 10th row after t in the stock's own daily-bar series). The **raw 10-session return** is r(i, t) = C(i, t+10) / C(i, t) - 1: bought at the close of day t, sold at the close of session 10, with no stop, no target, no costs, no slippage. For arm m with score s(m, i, t), let P(m, t) be the five stocks of E_t with the highest score (ties: ascending symbol). The daily value is x(m, t) = mean over i in P(m, t) of r(i, t) minus mean over i in E_t of r(i, t) (top-5 mean minus every-eligible-stock mean). The paired daily value is D(t) = x(C_56, t) - x(A_53, t). The **rows are decision days**; the unit of every interval is the day; the primary quantity is the mean of D(t) over the counted days (folds 4-33). It is **not** the +6% / -3.5% barrier trade result (used only to train the models and in the descriptive top-5 hit rate). In the harness this is `daily[].excess_vs_all` (`sector_walkforward._day_metrics`) and `forward_return` (`ml/features.build_label`).

This is the text in the existing draft (S-1 and D-Q10) restated with symbols; it matches the code except for the "next open" point above.

## 5. What a redesign could legitimately change, and what would be a post-hoc power game

| Change | Legitimate? | Effect (central, quantified here) |
|---|---|---|
| Forward-only evidence design, length fixed before any data, new protocol id | **Yes** | Time is the only lever: 8 years at 0.13 pp (section 3). No holdout use, no exposure. |
| R1 on a fixed number of folds (30) whose length grows with the test | **Yes** (and necessary for any longer test) | Removes the R1 plateau; costs nothing in R2 power. |
| Larger pre-specified MDE_H (power-based, 0.27) | **Yes**, if fixed before the run | Changes only the word FAIL; no power gain. |
| One-sided 5% bound instead of 2.5% (pre-specified, single primary, multiplicity re-counted) | **Yes** if declared up front | Lowers MDE80 by about 8% (SX10 R1+R2: 0.247 to 0.227); doubles the nominal false-pass rate; the programme count (11 to 12) then matters more. Not legitimate as a switch after seeing a p-value between 2.5% and 5%. |
| Combine horizons into one pre-specified primary (average of the standardised 5-day and 10-day D) | Legitimate in principle, **little gain** | Per unit of 5-day gain the z-values are about equal (1.4x larger 10-day cross-section over 1.4x larger noise: ASSUMED); with correlation r between the two D series the pooled z grows by sqrt(2 / (1 + r)): 1.41 at r 0, 1.15 at r 0.5, 1.09 at r 0.7, 1.03 at r 0.9. Same stocks and overlapping windows make r high, so expect 3% to 13% lower MDE, and the 10-day question is no longer asked separately. |
| Wider cohort (more stocks) | Only as a **new protocol** with its own eligibility, survivorship treatment and signing | Raises the edge per unit skill by 20% to 47% (section 3b) and is the strongest lever. Forbidden as a change of this dataset made "to improve power". |
| Dropping the 4 burn-in folds, or the opposite | Not for power | Changes the counted series by 12%: about 0.005 pp in MDE; do not toggle. |
| Fewer folds counted, dropping weak folds, trimming days, choosing the best of R1 shares, changing top-5 to top-3 or top-10, pooling picks or folds as the unit, switching to the barrier result, swapping blocks or seeds, choosing MDE_H or E* after seeing the upper bound, extending the sample after an INCONCLUSIVE under the same id | **No: post-hoc power games** | Each uses outcome information or inflates the false-pass rate; the protocol text already forbids the last one. |

## 6. Forward-only design for SX10: what it changes

- **Gains:** no holdout use, no dependence on the exposed holdout prices (they were used in earlier diagnostics), no survivor-selected window, cleaner than any retrospective test. R4 is replaced by "the data did not exist when the rule was signed".
- **Costs:** time (section 3) and a lane to run (data readiness, daily job, model freeze). A 60-session lane resolves only gains of order 0.5 pp (the h05 power tables begin at 0.5 pp).
- **Net:** with a realistic gain of 0.03-0.13 pp a forward-only SX10 is not an answer within the programme's horizon. It remains the right form for any future 10-day claim, because only forward data are clean.

## 7. Cost of running SX10 now versus deferring (register arithmetic)

| Item | Run SX10 now | Defer SX10 |
|---|---|---|
| Comparisons in the programme count (Phase B 3, selection lab 6, td-v2 B1, SX5, SX10 = 11 to 12) | 12 (upper figure) | 11 |
| P(at least one lucky pass), all nulls, 5% each: 1 - 0.95^n | n = 12: **46.0%**; n = 11: 43.1%; n = 10: 40.1% | 43.1% (n = 11): **3 points lower** |
| SX pair, uncorrected, 5% each: 1 - 0.95^2 vs 0.05 | 9.75% | 5% |
| Full-rule false-PASS in my simulation (2.5% bound, R1 + R4), per horizon | SX5 1.6%, SX10 0.9%; pair about 2.5% | 1.6% |
| Holdout window 2026-02-01 to 2026-08-15 (133 days, prices already used in earlier diagnostics) | scored a second time (once per candidate, registry is currently empty, 0 bytes) | SX5 only; SX10 keeps an unscored holdout for a better-powered later design |
| Chance of a PASS at a realistic gain (0.05 to 0.13) | 5.5% to 25% | n/a |
| Most likely printed word at a realistic gain | FAIL (about 75% at 0.05 for MDE_H 0.27) or INCONCLUSIVE; neither says the inputs do nothing | none |

A started holdout run counts as consumed even if it crashes. The protocol forbids re-running the same holdout after INCONCLUSIVE or FAIL. So running SX10 now would likely spend the 10-day holdout on a result that cannot discriminate between "no effect" and "0.13 pp", and a later well-powered 10-day design could not use that window cleanly.

## 8. Recommendation and what would change it

**DEFER SX10.**
Reasons: (1) power 5% to 25% at the assumed realistic gain, in no corner above 56%; (2) no practical forward length resolves a realistic gain (8 years at 0.13 pp); (3) running now spends a holdout use and a multiplicity slot; (4) redesigning for power inside this dataset would be a post-hoc power game or an unusable lever; (5) the zero-cost companion (item 6 of the summary) records the 10-day behaviour of the SX5 picks as a descriptive diagnostic.

Not recommended: EXPAND under the same protocol id (changes eligibility to buy power), and REDESIGN as a short forward lane (cannot resolve the effect).

Un-defer SX10 as a **new protocol id** only if one of these becomes true before any of its data are seen: (a) SX5 gives a PASS and a 5-day forward lane exists, so a 10-day extension of the same lane is nearly free; (b) a wider, survivorship-clean cohort is signed; (c) the owner decides a 0.25-0.27 pp screening test is acceptable as "large effect or nothing" and accepts the programme count of 12.

## 9. Limitations

1. All simulated structure is ASSUMED (iid daily returns, one market factor, AR(1) pick persistence, constant gain); phi and rho_AC are not measured on the two arms. They move the answer by a factor of about 2.2 (0.158 optimistic to 0.520 pessimistic, R1+R2).
2. Duration cells use 600 simulations: each interpolated length is +/- 10%; the analytic column is the cleaner reference. Lengths beyond 6,500 days are analytic extrapolations, and the iid assumption is weakest over decades (regimes).
3. The duration of a forward test assumes the same daily top-5 procedure and the same 47-stock cohort for years; in reality the cohort, models and costs change.
4. Pooled-horizon numbers use an ASSUMED correlation r between the two D series; not measured.
5. Real data used: development-period candles only; no holdout-period outcome was computed here.
6. This note does not decide whether SX10 should exist; it supplies the numbers and one recommendation.

## 10. Owner decisions this needs

1. Accept DEFER for SX10 (or choose to run it knowing the numbers in sections 2 and 7).
2. Sign the exact S-1 text of section 4 (entry at the decision-day close, raw 10-session return) or ask for the next-open version (needs code and a new power run).
3. If any longer test is ever planned: sign R1 as "60% of 30 folds with fold length scaled to the test length".
