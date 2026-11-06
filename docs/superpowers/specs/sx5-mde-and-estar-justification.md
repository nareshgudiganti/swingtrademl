# SX5: MDE_H power calculation and justification, and the economic floor E* (DRAFT, unsigned)

Date: 2026-11-04 (owner request). Status: **analysis only. Nothing signed, nothing committed, no value is approved.** MDE_H = 0.16 pp is examined, not adopted.
Code: `backend/scripts/sx_mde_estar_analysis.py` (tests `backend/tests/test_sx_mde_estar_analysis.py`, pure). Results: `docs/brain/evidence/sector_prep/sx_mde_estar_v1.json` (seeds in `meta`, per-cell `seed_key`).
No model was fitted, no arm evaluated, no holdout-period (2026-02-01 to 2026-08-15) outcome computed, no prod / Kite / `.env`. Real data used: development-period candles (dates up to 2026-01-31) of the signed eligible rows, SELECT only, and the repo's existing evidence files.
Labels: **MEASURED** (from data), **ASSUMED** (modelling choice), **PROPOSED** (for the owner).

> **UNITS (fixed wording; full table in `sx5-units-gross-net-and-idea-rule.md`).** The quantity is the daily paired difference D_t = (C_56 daily top-5 excess return) minus (A_53 daily top-5 excess return). A daily top-5 excess is the mean forward 5-session return of that day's 5 picks minus the mean forward 5-session return of all eligible stocks that day, written as a FRACTION of the money in a trade: 0.0017 = 0.17 percentage points (pp) = 17 basis points (bps) of one 5-session holding return. Because the daily value is already an average over that day's ideas, "per day" and "per trade" are the same number. Nothing is annualised. MDE_H = 0.0018 means 0.18 pp (18 bps) of one holding return, per trade; typing 0.18 would mean 18 percentage points per trade (100 times too large), and the verdict code refuses any MDE_H >= 0.02 ("looks like percentage points: pass a fraction") and any unit tag other than `fraction_of_return`; `mde_h_from_pp(0.18)` gives 0.0018. SX10 would use the 10-session return. The primary quantity is GROSS (no costs; entry at the decision-day close); costs and the net reading are in the same note, section 2.

**Recommended signed values (PROPOSED).** SX5 MDE_H = 0.18 pp = 0.0018 (80% power for the PASS rule 0.183 pp on the 565 counted days; R1 + R2 alone 0.170 pp; range 0.12 to 0.34 pp; central assumptions pick persistence 0.5 and arm correlation 0.8 are ASSUMED). E\* = 0.37 pp = 0.0037 is a REPORTED SENTENCE, not an outcome rule, unless signed. Gross-versus-net and the ideas-per-fold justification: `sx5-units-gross-net-and-idea-rule.md`.

## 1. Plain-English summary

1. **How 0.16 arises.** The question: how big must the true gain of the 56-input model over the 53-input model be (in percentage points per trade) for the pass rule to say PASS four times in five? For the counted series (folds 4-33: 30 folds, **565 days**, not the 642 of all 34 folds) at the central assumptions the answer is **0.170 pp** for the rule R1 + R2 (Monte Carlo range 0.166 to 0.175; an independent replicate gave 0.174) and **0.183 pp** for the full PASS rule including the holdout check R4. The figure **0.16 is what you get from all 642 days** (0.163): it counted days the verdict does not count. With the looser 5% bound that the second horizon would get under Holm the figure is 0.156. So 0.16 is within rounding of a defensible number but it is the *uncorrected* one. The corrected one is **0.17** (R1 + R2) or **0.18** (full PASS rule). (SX10, same correction: 0.25 and 0.27.)
2. **The arithmetic behind it.** The noise in the average daily difference of the two models over 565 days is 0.061 pp (daily spread 1.275 pp, only 440 of the 565 days are effectively independent because the picks repeat). To be 97.5% sure the bound is above zero and 80% likely to get there: (1.960 + 0.842) x 0.061 = **0.170 pp**. The simulation agrees to the third decimal. Nothing about it is exotic.
3. **What the words mean (central assumptions, MDE_H = 0.16, full rule R1 + R2 + R4, 2.5% bound).**

   | True gain | PASS | FAIL | INCONCLUSIVE |
   |---|---|---|---|
   | 0 pp (inputs do nothing) | 1.6% | **84.9%** | 13.5% |
   | 0.05 pp | 9.3% | **59.6%** | 31.0% |
   | 0.10 pp | 29.0% | 27.6% | 43.3% |
   | 0.16 pp | 68.5% | 5.4% | 26.0% |
   | 0.30 pp | 99.2% | 0.0% | 0.9% |

   **FAIL means only "a gain of 0.16 pp or more is unlikely". It does not mean the inputs do nothing.** At a true gain of 0.05 pp, the realistic top, FAIL is still the most likely word (60%). FAIL cannot be read as "every smaller positive gain is absent": the test cannot see those. R1 and R4 do not change a FAIL (see 4.2), they only split PASS from INCONCLUSIVE.
4. **E* (the smallest gain worth acting on).** Costs decide this. One round trip costs **0.36% to 0.44%** of the money in a trade. Under the traded 5-day rule (+2% / -4%) buying every stock lost **0.36% to 0.38% a trade** (MEASURED in the repo's own runs), and the production-score top-5 lost 0.37%: the picks did no better than every stock. To make the top-5 break even the paired gain would have to be about **0.37 pp**. That is **2.2 times** the MDE80 of 0.17 and 3.7 times the top of the realistic range (0.10). So a gain *equal to MDE_H*, even if detected for certain, would **not** make the 5-day top-5 profitable under the traded rule (net would stay about -0.19% a trade). It would matter only as evidence that the extra inputs improve the *ranking*. Candidate E* values: **0.10** (what this experiment can tell from zero), **0.17-0.18** (the power value), **0.37** (break-even). I recommend 0.37 as the economic E* (section 6) and keeping MDE_H power-based. E* would change no outcome word unless the owner writes it into the rule.
5. **Good news hidden in the numbers.** The experiment is well powered for the size of gain that would actually matter for money: 80% power needs only about 120 trading days of confirmation at 0.37 pp, against about 1,640 days for 0.10 pp. The weakness is the realistic small edge, which is economically small anyway.

## 2. What was recomputed, and why the number moves

- The simulation of the S-9 note (`sx_power_analysis.py`) reported "34 / 30 folds". Its 34-fold column used all 642 development days (folds 0-33 in the 0-based numbering). The verdict code counts folds 4-33 only: `VerdictParams.burn_in_folds = 4`, 30 folds, **565 days** (CSV `sx5_fold_coverage_v3.csv` rows 5-34; checked: 565 = 775 - 133 - 77). The S-9 headline "about 0.16" was the 642-day column.
- This script re-runs the decision procedure on the counted series with the verdict code's exact conventions: bootstrap bounds taken at sorted-index 50 / 100 (lower 2.5% / 5%) and 1899 (upper 5%) out of 2,000 draws, moving blocks of 10 days (SX5) and 20 (SX10), R1 = at least ceil(0.6 x 30) = **18** of 30 folds with a positive mean paired difference, R4 = development mean > 0 and holdout mean > 0 (133 simulated holdout days, same true edge ASSUMED), FAIL = R2 not met and the 5% upper bound below MDE_H.
- Synthetic model (ASSUMED, unchanged from S-9; measured inputs read from `sx_s9_power_v1.json`): market factor + stock noise, Student-t tails (4.9 df), measured stock volatilities, market share of variance 0.252; AR(1) pick persistence phi; arm correlation rho_AC; only the part of C's score A does not see carries information; A has no edge. Central = (phi 0.5, rho_AC 0.8). 2,000 simulations per cell, master seed 20261104 (replicate: +1000), per-cell `SeedSequence` keys in the JSON.

## 3. Corrected MDE80 (true paired gain, pp per trade, giving 80% probability)

"R1+R2" = dev rule without R4; "PASS" = R1 + R2 + R4 (the word PASS). Bound = 2.5% (single-horizon, the code default) unless stated. Brackets = Monte Carlo 95% range of the interpolated MDE (about +/-3%).

**SX5**

| Assumption (phi, rho_AC) | Days | R2 alone | R1+R2, 2.5% | R1+R2, 5% bound | PASS (with R4) | SE of mean D |
|---|---|---|---|---|---|---|
| **Central (0.5, 0.8), counted 565 days** | 565 | 0.166 | **0.170** [0.166, 0.175] | 0.156 | **0.183** [0.179, 0.187] | 0.061 |
| Central, replicate seed | 565 | 0.170 | 0.174 | 0.160 | 0.189 | 0.062 |
| Central, all 34 folds (the old headline) | 642 | 0.154 | **0.163** [0.159, 0.168] | 0.154 | 0.182 | 0.057 |
| Optimistic (0, 0.95) | 565 / 642 | 0.108 / 0.102 | 0.110 / 0.108 | 0.101 / 0.103 | 0.120 / 0.118 | 0.039 / 0.036 |
| Pessimistic (0.9, 0.5) | 565 / 642 | 0.299 / 0.274 | 0.306 / 0.291 | 0.282 / 0.278 | 0.336 / 0.322 | 0.112 / 0.103 |
| Sticky picks (0.9, 0.8) | 565 | 0.219 | 0.227 | 0.209 | 0.250 | 0.083 |
| Independent picks (0, 0.8) | 565 | 0.151 | 0.155 | 0.142 | 0.168 | 0.054 |

**SX10 (same correction)**

| Assumption | Days | R2 alone | R1+R2, 2.5% | R1+R2, 5% | PASS (with R4) |
|---|---|---|---|---|---|
| **Central** | 565 | 0.241 | **0.247** [0.242, 0.253] | 0.227 | **0.268** |
| Central, all 34 folds | 642 | 0.228 | 0.242 | 0.228 | 0.265 |
| Optimistic | 565 | 0.154 | 0.158 | 0.146 | 0.171 |
| Pessimistic | 565 | 0.510 | 0.520 | 0.481 | 0.567 |

Reading: moving from 642 to 565 days raises the R1+R2 MDE80 by 4% (SX5 central 0.163 to 0.170). The old table's "30 folds" column already used 565 days (0.165), so the S-9 note's *table* was nearly right; its headline number and the "34 folds" label were the uncorrected ones. MDE80 for the full word PASS (with R4) is about 0.01 higher than for R1+R2.

**Sensitivity in one line.** Over the assumed ranges the SX5 MDE80 (PASS rule) runs from 0.12 (optimistic) to 0.34 (pessimistic), a factor of about 2.8. The two ASSUMED dependences drive it: pick persistence (phi) and the correlation between the arms (rho_AC); neither can be measured without fitting models (not done). They can be measured after the run from the stored per-fold scores (descriptive).

**Monte Carlo error.** Binomial SE of a probability p over 2,000 runs: 0.5 points at p = 3%, 1.1 points at 20%, 1.1 points at 50%. MDE80 range +/-0.004 to 0.005 (about 3%). Two independent seeds of the central SX5 cell gave R1+R2 0.170 and 0.174 and PASS probabilities at a 0.16 true gain of 68.5% and 65.8%. Quote MDE80 as "0.17 +/- 0.005". The model uncertainty (phi, rho_AC) is ten times larger than the simulation noise.

## 4. Outcome-word probabilities (SX5, 565 days, 2.5% bound, full rule)

### 4.1 Central assumptions, several MDE_H (each cell: PASS / FAIL / INCONCLUSIVE, %)

| True gain | MDE_H 0.10 | **MDE_H 0.16** | MDE_H 0.18 | MDE_H 0.25 | MDE_H 0.30 |
|---|---|---|---|---|---|
| 0 | 1.6 / 52.1 / 46.3 | 1.6 / **84.9** / 13.5 | 1.6 / 90.7 / 7.6 | 1.6 / 96.6 / 1.8 | 1.6 / 96.6 / 1.8 |
| 0.05 | 9.3 / 22.1 / 68.5 | 9.3 / **59.6** / 31.0 | 9.3 / 70.8 / 19.9 | 9.3 / 84.5 / 6.1 | 9.3 / 84.6 / 6.0 |
| 0.10 | 29.0 / 5.4 / 65.5 | 29.0 / 27.6 / 43.3 | 29.0 / 38.5 / 32.5 | 29.0 / 61.0 / 10.0 | 29.0 / 61.3 / 9.7 |
| 0.16 | 68.5 / 0.4 / 31.0 | 68.5 / 5.4 / 26.0 | 68.5 / 10.5 / 20.9 | 68.5 / 23.0 / 8.5 | 68.5 / 23.1 / 8.4 |
| 0.30 | 99.2 / 0.0 / 0.9 | 99.2 / 0.0 / 0.9 | 99.2 / 0.1 / 0.8 | 99.2 / 0.1 / 0.7 | 99.2 / 0.1 / 0.7 |

PASS does not depend on MDE_H; only the split of the rest does. The earlier scratch check (FAIL 91% / 63% at 0 / 0.05 pp) matches the MDE_H 0.18 and 0.16 columns (91% / 71% and 85% / 60%): it was right in kind because **in the verdict code FAIL depends only on R2 and the upper bound** (4.2).

### 4.2 Why R1 and R4 do not change FAIL

`compute_verdict` order: data checks, then "R2 and R1 -> PASS if R4 else INCONCLUSIVE", else "R2 not met and 5% upper bound < MDE_H -> FAIL", else INCONCLUSIVE. A run whose R2 fails can therefore be FAIL even if R1 holds (R1 alone holds 18% of the time at zero gain, 88% at 0.16). R1 and R4 only decide whether a run with R2 met is PASS or INCONCLUSIVE. The tables above are joint over R1, R2, R4 (a single simulated sequence per run). Under zero gain (simulated): R1 alone 18.0%, R2 alone 3.5%, R1 and R2 together 3.3%, R4 alone 23.8% (development mean > 0 and holdout mean > 0), all three 1.6%. The false-PASS rate of the full rule under no effect is about 2% (SX5) and 1% (SX10), below the 2.5% nominal level: conservative.

### 4.3 Other assumptions (SX5, MDE_H 0.16; PASS / FAIL / INCONCLUSIVE, %)

| True gain | Optimistic (0, 0.95) | Central (0.5, 0.8) | Pessimistic (0.9, 0.5) |
|---|---|---|---|
| 0 | 1.5 / 96.8 / 1.7 | 1.6 / 84.9 / 13.5 | 1.8 / 47.7 / 50.4 |
| 0.05 | 18.5 / 73.6 / 7.9 | 9.3 / 59.6 / 31.0 | 5.3 / 31.6 / 63.1 |
| 0.10 | 64.6 / 26.1 / 9.3 | 29.0 / 27.6 / 43.3 | 11.7 / 17.9 / 70.4 |
| 0.16 | 95.8 / 1.5 / 2.7 | 68.5 / 5.4 / 26.0 | 25.7 / 7.4 / 66.9 |
| 0.30 | 100 / 0 / 0 | 99.2 / 0.0 / 0.9 | 71.1 / 0.4 / 28.6 |

In the pessimistic world a zero-effect run is INCONCLUSIVE half the time, because the noise (SE 0.112) is as large as MDE_H.

## 5. Trade-off: what changes if MDE_H is set differently (SX5)

Columns: P(FAIL) when the true gain is 0; P(PASS) / P(FAIL) / P(INCONCLUSIVE) when the true gain equals MDE_H.

| MDE_H | Central: P(FAIL), gain 0 | P(INCONC), gain 0 | P(PASS) at MDE_H | P(FAIL) at MDE_H | P(INCONC) at MDE_H | Pessimistic: P(FAIL) at 0 | P(PASS) at MDE_H |
|---|---|---|---|---|---|---|---|
| 0.10 | 52.1% | 46.3% | 29.0% | 5.4% | 65.5% | 28.3% | 11.7% |
| 0.16 | 84.9% | 13.5% | 68.5% | 5.4% | 26.0% | 47.7% | 25.7% |
| 0.25 | 96.6% | 1.8% | 95.8% | 1.5% | 2.8% | 77.1% | 55.0% |
| 0.30 | 96.6% | 1.8% | 99.2% | 0.1% | 0.7% | 88.4% | 71.1% |

Reading. (i) P(FAIL) at a true gain equal to MDE_H is about 5% for MDE_H up to the point where the bound saturates: this is the meaning of a one-sided 5% upper bound ("a gain of MDE_H or more is unlikely" is wrong 5% of the time). (ii) A **small MDE_H (0.10)** gives a FAIL that is a strong claim (rules out 0.10) but arrives only 52% of the time at zero gain, and P(PASS) at 0.10 is only 29%: the experiment cannot back the claim it states. (iii) A **large MDE_H (0.25, 0.30)** produces FAIL almost always when nothing works (97%) but it also stamps FAIL on a true gain of 0.16 in 23% of runs and on a true gain of 0.10 in 61%: FAIL then says only "no large gain", which is true and cheap, and the word would be read as more negative than it is. (iv) MDE_H near the MDE80 (0.17-0.18) is the point where P(PASS) at MDE_H is about 70-80% and the three words are balanced. A power-based MDE_H makes the three words consistent: gain at MDE_H -> mostly PASS, no gain -> mostly FAIL, in between -> INCONCLUSIVE.

## 6. E*: the smallest paired gain worth acting on

E* is the smallest improvement of C_56 over A_53, in percentage points of daily top-5 excess return (= per trade, equal weight, five picks), that would justify acting, given the experiment's objective (a forward shadow test of a 5-day ranking: no money, only time), costs and uncertainty.

### 6.1 Cost per trade (MEASURED from the repo's cost model; slippage ASSUMED in the repo)

| Item | Value | Source |
|---|---|---|
| Buy / sell charges | 11.9 + 10.4 = 22.3 bps | `docs/brain/COSTS-CHECK-2026-10.md`, `h05_protocol.COSTS` |
| Depository fee | Rs 15.93 per sell: 1.6 bps of Rs 1,00,000; 4.0 bps of Rs 40,000 | same |
| Slippage per side, large cap | 10 bps (h05 lane); 5 bps (fd_v1, 15D notes) | `h05_protocol.SLIPPAGE_BPS` |
| **Round trip, large cap, h05 assumption** | **43.9 bps = 0.439%** | computed (tested) |
| **Round trip, 5 bps slippage, Rs 40,000** | **36.3 bps = 0.363%** (the "about 0.36%" of the notes) | computed (tested) |
| Mid cap (20 bps per side) | 63.9 bps | not needed: all 47 SX stocks fall in the lane's "large" group (MEASURED: 47 large, 0 mid) |

Observation (read-only, not edited): `h05_protocol.COST_UNITS["round_trip_cost_bps_approx"]` says large 58 bps. That figure treats the Rs 15.93 depository fee as 15.9 bps; on Rs 1,00,000 it is 1.6 bps. The sum with 10 bps slippage is 43.9, not 58. Worth a look when the h05 protocol is next reviewed (the text is part of its hash).

### 6.2 Baselines on development-period data

| Quantity | 5-day | Source / status |
|---|---|---|
| Every eligible stock, raw close-to-close 5-session return, gross mean, counted window 2023-10-21 to 2026-01-31 (560 days, 26,262 stock-days; windows with a one-day move over 25% dropped) | **+0.370%** | MEASURED now from candles (survivor-biased 47-stock cohort in a rising period: **flattered, not a forecast**) |
| same, net of 0.439% | **-0.069%** | computed |
| Random-5: expectation equals every stock; sampling noise of its 560-day mean | SD 0.054 pp | MEASURED (400 seeded draws, seed 20261110 for 5-day, 20261115 for 10-day) |
| fd_v1 (traded rule +2% / -4%, next open, 2023-07 to 2025-01, 396 days, 49 stocks, costs 0.36%): every stock | **-0.359% per trade** | `docs/brain/evidence/fd_v1/five_day_2023-07-01_2025-01-31.json`: model best-5 -0.370%, random-5 -0.359%, momentum -0.362%, buy rule -0.423% |
| fd_v1 best-5 minus every stock, daily edge | -0.011 pp (lower bound -0.155) | same |
| h05 power evidence: every eligible stock under the lane rule, large caps, 1,042 sessions | **-0.382%** | `h05/power/power_support.md` (cohort differs) |
| Hit rate needed to break even under +2/-4 | 72.7% after costs (hit rate seen: 40% every stock, 51% best-5) | fd_v1 |

Why raw-hold and traded rule differ so much: the +2% / -4% rule caps winners and lets a cost of 0.36-0.44 pp sit on top of a 40% hit rate. The shadow lane trades the +2/-4 rule; the SX test judges the raw 5-day return.

### 6.3 Candidates

| Candidate | Definition | Calculation | Value |
|---|---|---|---|
| **E*_sd** (statistical resolution) | smallest gain separable from zero at one-sided 5% in a typical 565-day run: 1.645 x SE of the mean D | 1.645 x 0.061 (central; 0.064 optimistic, 0.184 pessimistic). Cross-check with real data: 1.645 x 0.054 = 0.089 (random-5 noise, iid picks) | **0.10 pp** |
| **E*_power** (power value) | MDE80 of the experiment | section 3 | **0.17 pp** (R1+R2), 0.18 (PASS rule) |
| **E*_breakeven** (economic floor) | gain C must add over A_53 for the top-5 to earn zero net per trade: cost - baseline gross - edge of A_53 (A_53 edge about 0: fd_v1 -0.011 pp) | traded rule: every stock nets -0.36% (fd_v1) / -0.38% (h05, large) so the top-5 needs +0.36 to +0.38 pp. Raw hold in the counted window: 0.439 - 0.370 = 0.07 pp, but this rests on +0.37% drift in 5 days (about 19% a year, survivor cohort) and is not used | **0.37 pp** |
| E*_costs (friction only) | one round trip | 0.363% (5 bps) to 0.439% (h05) | 0.36 to 0.44 pp |

Net result per trade if C_56 gains +delta over A_53 (traded rule, A_53 about equal to every stock, baseline -0.36%): delta 0.05 -> -0.31%; 0.10 -> -0.26%; **0.17 (MDE_H) -> -0.19%**; 0.37 -> about 0%.

### 6.4 Independent days needed to confirm each candidate (80% power, 2.5% bound, central; days = (1.960 + 0.842)^2 x sd^2 / E*^2; sd of daily D = 1.275 pp, effective share of days 0.78)

| E* | Independent days | Trading days | Months (21 per month) |
|---|---|---|---|
| 0.10 (E*_sd) | 1,276 | 1,639 | 78 |
| 0.18 (E*_power) | 381 | 490 | 23 |
| 0.25 | 204 | 262 | 12 |
| 0.36 (cost, 5 bps) | 97 | 124 | 6 |
| 0.37 (break-even) | 93 | 120 | 6 |
| 0.44 (cost, h05) | 66 | 85 | 4 |

### 6.5 Relation of E*, MDE_H and the realistic range

Realistic edge (ASSUMED, S-9): 0.02 to 0.10 pp. MDE80 = 0.17-0.18. E*_breakeven = 0.37. So realistic < E*_sd (0.10) = top of the realistic range < MDE80 < E*_breakeven; the realistic range covers at most 27% of one round trip.

**Is a detectable gain equal to MDE_H economically meaningful? No, not as money.** At 0.17 pp the top-5 would still lose about 0.19% a trade under the traded rule (about 47% of the cost is covered). Under the flattered raw-hold view in the development window it would turn -0.07% into about +0.10%; I do not rely on that view because it rests on period drift. It is meaningful as *information*: a ranking improvement of that size, if it were real, is the sort of increment that the shadow lane (the h05 power tables start at 0.5 pp) could eventually test. This is a finding about the programme: even a successful SX5 does not make the 5-day strategy profitable by itself.

### 6.6 Recommendation (the owner chooses)

1. **Recommended E* = 0.37 pp** (rounded; the measured net loss of buying every stock is 0.36 to 0.38 pp and one round trip is 0.36 to 0.44 pp). Reason: it answers the question "what gain would change what we do with money", it is a number the experiment can resolve (120 trading days to confirm), and it is not arbitrary (two independent repo measurements agree to 0.02 pp).
2. **Keep MDE_H power-based: 0.17 or 0.18**, not E*. Setting MDE_H = E* = 0.37 would stamp FAIL on a true gain of 0.16 pp in about 23% of runs and give a 97% FAIL at zero; the word FAIL would then mean only "no gain big enough to trade", a weaker and differently-worded claim. With MDE_H at the power value FAIL keeps its link to what the experiment can see.
3. **Report both, as sentences, not words.** Beside R2 print the 5% upper bound of mean(D) and say: "a gain of MDE_H or more is unlikely" when the bound is below MDE_H (that is the word FAIL), and separately "a gain large enough to cover trading costs (E*) is unlikely / not ruled out" when the bound is below / above E*. The second sentence carries **no outcome word and changes none**: E* enters the pass/fail logic only if the owner signs it into the rule (it would then be a new PROPOSED parameter in `VerdictParams`, with a code and protocol change).
4. If the owner prefers a single number: E* = 0.37 as the "worth trading" floor and the power value as MDE_H; the S-9 proposal of E* = 0.10 (the top of the realistic range) is E*_sd and describes resolution, not value.

## 7. Limitations

1. Everything above the measured inputs is ASSUMED: iid daily returns, one-factor structure, AR(1) pick persistence (central 0.5 matched to one nine-pair measurement), arm correlation 0.8 (unmeasurable without fitting), constant true gain over all folds and the holdout. A regime-limited gain would pass R1 less often than shown.
2. R4 power assumes the holdout edge equals the development edge.
3. Block bootstrap with about 57 blocks of 10 days: false-PASS and false-FAIL rates are approximately, not exactly, nominal. The simulated zero-gain false-PASS of the full rule is about 1.6%.
4. The cost baseline is survivor-biased (today's watchlist) and period-specific (rising 2025); true break-even is likely higher, not lower. h05 slippage is an assumption from daily high-low ranges.
5. Raw-return versus traded-rule: the SX test judges the raw 5-session return (entry at the decision-day close); the economic numbers use the +2/-4 rule with next-open entry. Convert with care.
6. The dependence on the correct number of counted days is measured only for the simulated structure; the real D_t may have a different autocorrelation (the S-9 note lists the negative lag-5 autocorrelation of the daily mean that is not modelled).
7. One cohort of 47 large caps; nothing generalises to mid or small caps (Limitation U).

## 8. Owner decisions this needs

1. Replace the MDE_H candidate 0.16 by the corrected 0.17 (R1+R2) or 0.18 (full PASS rule), or keep 0.16 knowingly (it is the 642-day figure; PASS probability at a true 0.16 gain is 68.5%, not 80%).
2. Choose E* (recommended 0.37) and whether it is reported as a sentence only (recommended) or signed into the rule.
3. Accept that FAIL is worded "a gain of MDE_H or more is unlikely" and never "the inputs do nothing".
4. Units for the signed parameter: the harness stores `forward_return` as a fraction, so `excess_vs_all` and `VerdictParams.mde_h` are fractions per day. 0.17 pp is `mde_h = 0.0017`; 0.16 pp is 0.0016. A value typed as 0.17 would be 17 percentage points and would make FAIL almost automatic. Worth a unit check (or a sanity bound) when the parameter set is signed.
