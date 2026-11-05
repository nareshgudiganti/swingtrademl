# S-9: minimum detectable edge and power limits for SX5 and SX10 (DRAFT, unsigned)

Date: 2026-11-08. Closes S-9 / B18 / L5 of `2026-11-06-sx-presigning-findings.md` and `2026-11-07-sx-blockers-summary.md`.
Code: `backend/scripts/sx_power_analysis.py` (tests: `backend/tests/test_sx_power_analysis.py`, 19 pure tests). Results: `docs/brain/evidence/sector_prep/sx_s9_power_v1.json`.
Nothing here fits a model, evaluates an arm, signs anything, or touches the holdout period (2026-02-01 to 2026-08-15): the only real data used are development-period prices (candle dates up to 2026-01-31) for the signed eligible rows, plus the stored production score on post-holdout days (2026-08-16 onward; first stored day 2026-08-21) for score persistence only.

Labels used in this note: **MEASURED** (from real development data, code recorded), **ASSUMED** (a modelling choice, not data), **PROPOSED** (for the owner to accept).

## 1. Plain-English summary

1. **Both experiments are underpowered for the edge a sector input can realistically add.** The question each one asks is: does the model with 3 extra sector inputs (C_56) pick better top-5 stocks than the model without them (A_53)? The size of the gain (per trade, in percentage points) that the full pass rule would catch 4 times out of 5:

   | | Central assumption (ASSUMED) | Optimistic corner | Pessimistic corner |
   |---|---|---|---|
   | **SX5** (5-day close at least +2%) | **about 0.16 pp per trade** (50% chance at about 0.11) | 0.11 | 0.30 |
   | **SX10** (10-day +6% / -3.5% barrier) | **about 0.24 pp per trade** (50% chance at about 0.17) | 0.15 | 0.50 |

   Central = score persistence 0.5, the two arms' scores correlated 0.8, 34 folds, 2.5% one-sided bound, R1 + R2. Optimistic = persistence 0, correlation 0.95. Pessimistic = persistence 0.9, correlation 0.5. Per trade and per daily top-5 excess are the same number (equal weight, five picks). Simulation noise on each figure is about 3% of the value.

2. **A realistic gain is smaller than that.** My assumed range for what three sector inputs add to a 53-input model is 0.02 to 0.10 pp per trade for SX5 and 0.03 to 0.13 pp for SX10 (section 7, ASSUMED, anchored on the repo's own evidence, which shows no edge at all for A-like models). At those sizes the chance that the rule says PASS is **about 15% to 45% for SX5 and 7% to 20% for SX10** at the central cell. **Verdict: NOT ADEQUATE POWER for a realistic edge.** Adequate power exists only for a gain of 0.2 pp (SX5) or 0.3 pp (SX10) or more, which would be as large as the entire skill a good model has, not an increment from three inputs.

3. **What the experiment can still do.** (a) It can show a large benefit (a PASS is hard to get by luck: the false-pass rate under no effect is 2% to 4% per horizon, 4% to 7.5% for either horizon across the pair, 2% to 4.5% with the holdout check R4). (b) A failure to pass is **not evidence that the inputs do nothing**; it only rules out gains above roughly the numbers in the table.

4. **"INCONCLUSIVE" in the protocols does not mean this.** In R0 to R5, INCONCLUSIVE only fires when R3 fails (fewer than 12 folds or 100 ideas). With 34 folds and about 3,200 ideas R3 will never fail, so a weak result will be printed as **NO IMPROVEMENT**, which a reader will take to mean "tested and found nothing". The findings and blockers notes say INCONCLUSIVE is the expected outcome, but the written rule does not produce that word. I propose a wording fix (section 9, PROPOSED).

5. **Dependence changes power by a factor of about 2.** The clearest driver is how much the two arms' picks agree (the closer they are, the smaller the noise in the difference) and how much the same stocks stay in the top 5 day after day (more repeats, fewer independent days). The correlation between the arms is an assumption I cannot measure without fitting models, which is forbidden here. Measure it after the run and report it; do not use it to move any threshold.

## 2. What is being asked (rules quoted)

Pass rule (approval packages, section 8, PROPOSED, SX5 and SX10 identical):

- **R0 Same rows**: the A_53, R_37 and C_56 eligible row lists are identical (equal sha256).
- **R1 Paired skill**: "C_56 beats A_53 on the daily top-5 excess over every eligible stock in at least 60% of eligible folds (with S-6; and, if you accept the burn-in rule, over folds 4-33 only)".
- **R2 Paired lower bound**: "5th percentile of the mean daily difference (C_56 minus A_53) is above zero" revised by S-3 and S-5 to the block-2h bootstrap and the Holm bound.
- **R3 Enough data**: "at least 12 eligible folds and at least 100 finished best-5 ideas, else INCONCLUSIVE".
- **R4 Holdout agrees**: "the paired difference on the final holdout has the same sign (reported; not a second chance to pass)".
- **R5 No harm**: descriptive.
- Outcome words: "IMPROVES (R0 to R4 all met), NO IMPROVEMENT (enough data and R1 or R2 not met), INCONCLUSIVE (R3 not met)".

Procedure (S-1 to S-8): daily unit; D_t = C_56 daily top-5 excess minus A_53 daily top-5 excess; moving-block bootstrap, blocks of 2 x horizon days (10 for SX5, 20 for SX10), non-circular, ceil(n/block) blocks per draw, 2,000 draws, seed 7, one-sided lower bounds; Holm over the two primaries (smaller p must clear 2.5%, the other 5%); R1 uses per-fold means of D_t; holdout 133 days; B2 burn-in (folds 4-33 only, 30 folds) PROPOSED.

## 3. Method

**Real data (MEASURED).** `measure_dependence` and `measure_score_persistence` in the script read candles through `docker exec stml-postgres psql` (SELECT only), candle dates up to 2026-01-31, restricted to the signed row lists `sx5_47_rows_v3.txt.gz` and `sx10_47_rows_v3.txt.gz`, decision days from 2023-07-01. Windows containing a one-day move above 25% (probable unadjusted corporate action) are dropped (5 windows at 5D, 10 at 10D). Because forward windows may not use holdout-period bars, the last few development decision days are lost (637 and 632 of 642).

**Synthetic procedure (ASSUMED structure, MEASURED inputs).** For each cell the script simulates 47 stocks and 642 development days (34 folds with the real day counts from `sx5_fold_coverage_v3.csv`, `sx10_fold_coverage_v3.csv`) plus 133 holdout days:

- Daily returns: one market factor plus stock noise, Student-t tails, iid in time; each stock's daily standard deviation is its measured one; market share of variance 0.252 (measured average pairwise correlation of daily returns); tail df 4.9 (from measured excess kurtosis 6.7). The h-day forward return of day t is the sum of the next h daily returns, which builds the overlap of consecutive outcomes in by construction.
- Scores: AR(1) in time with persistence phi (marginally normal). Arm A score zA; arm C score zC = rho_AC x zA + sqrt(1 - rho_AC^2) x zN. The true expected return is proportional to zN only, so the whole gain of C over A is the information A does not see, and A itself has no edge (consistent with the repo's evidence for A-like models). Gain in expected D_t = delta (the grid variable).
- D_t = mean return of C's top 5 minus mean return of A's top 5 on the same day (the every-stock mean cancels).
- The decision procedure is applied exactly as written: R1 (fold means of D_t positive in at least 60% of folds: 21 of 34 or 18 of 30), R2 (moving-block bootstrap, block 10 or 20, 2,000 draws, lower bound at 2.5% and at 5% above zero), R4 (holdout-period mean of D_t above zero, assuming the same true edge), for both 34 folds and 30 folds (B2).
- D_t is linear in delta, so one set of draws gives the full power curve with common random numbers; the power curve is monotone up to Monte Carlo noise (tested).
- 1,000 simulations per cell (each with its own 2,000 bootstrap draws), master seed 20261108, per-cell `SeedSequence` keys are in the script and the JSON. Monte Carlo SE of a rate p is sqrt(p(1-p)/1000): up to 1.6 points for a 50% rate, 0.5 points for a 3% rate. The JSON stores the 95% Monte Carlo range of each minimum detectable edge (about +/-3%).
- Runtime about 30 minutes for 32 cells. Re-run: `python backend/scripts/sx_power_analysis.py --out <file.json>` (re-measures; needs the local Docker database), or `--measured <earlier json>`.

## 4. Measured dependence (development period, MEASURED)

| Quantity | SX5 (5D endpoint) | SX10 (10D barrier) | Findings-file value |
|---|---|---|---|
| Decision days used / stock-day rows | 637 / 29,881 | 632 / 29,641 | 642 test days |
| Eligible stocks a day (min / median / max) | 45 / 47 / 47 | 45 / 47 / 47 | 45-47 |
| Per-stock label autocorrelation, lag 1 / 2 / 3 / 4 | 0.57 / 0.38 / 0.23 / 0.09 | 0.68 / 0.53 / 0.42 / 0.33 | 0.57 / 0.68 at lag 1 |
| Per-stock forward-return autocorrelation, lag 1 / 2 / 4 / h | 0.78 / 0.58 / 0.16 / -0.06 (lag 5) | 0.89 / 0.78 / 0.56 / -0.05 (lag 10) | triangular (h-k)/h expected |
| Same-day cross-stock correlation, label / forward return | 0.160 / 0.268 | 0.123 / 0.243 | 0.157 / 0.113 (label) |
| Daily-mean forward return autocorrelation, lag 1 / 2 / 3 / 4 | 0.77 / 0.56 / 0.34 / 0.09, then -0.15 to -0.17 at lags 5-8 | 0.88 / 0.77 / 0.64 / 0.50 ... 0.02 at lag 8, -0.12 at lag 10 | 0.79 / 0.57 / 0.34 / 0.10 and 0.88 / 0.77 / 0.65 / 0.52 |
| Effective independent days of the daily mean return (formula below) | 199 of 637 | 78 of 632 | about 246 and 95 of 838 |
| Forward-return standard deviation (percent) | 3.33 | 4.59 | |
| Daily return: average pairwise correlation / excess kurtosis | 0.252 / 6.7 | 0.252 / 6.7 | |
| Label base rate | 27.2% | 20.1% | |

Effective days of a series x with n values: **n_eff = n / (1 + 2 x sum_{k=1..K} (1 - k/(K+1)) x rho_k)**, K = 3h (Bartlett taper, rho_k the lag-k autocorrelation), clipped to [1, n]. My figures (199, 78) are lower than the findings file's 246 and 95 because they use development days only and a tapered, truncated formula; the order of magnitude agrees.

**Important distinction.** The 199 and 78 are the effective days of the *market-wide daily mean return*, which is dominated by the common market move and the overlap. The series that matters here, D_t, has the market move cancelled (both arms hold five stocks on the same day) and its noise comes from rotating stock picks. Its effective days, estimated in the simulation as `(mean daily variance of D_t) / (variance of the 642-day mean of D_t)`, are in the tables below (about 150 to 680 depending on persistence). Values slightly above 642 are noise. The 246 and 95 in the findings file should not be used as the sample size of the primary comparison.

**Persistence of picks (phi), real analogues.** The h05 power evidence uses an assumed "stickiness" of 0.8 per pick (`docs/brain/evidence/h05/power`), not a measurement; `h05_signals` in the local database holds no rows, so h05 pick repetition cannot be measured. The only measurable analogue is the stored production score (model 2, post-holdout days, 11 stored days, 9 consecutive pairs, 49 stocks): **MEASURED day-to-day rank correlation 0.59 (range 0.49 to 0.68), and 40% of today's best 5 are in tomorrow's best 5.** In the simulation, phi 0.5 gives a 32% repeat share and phi 0.9 gives 67%, phi 0 gives 10.5% (chance). So the production score sits between phi 0.5 and 0.9, nearer 0.5 to 0.7. Caveats: nine pairs, one model, 3 weeks, a different period. Central phi = 0.5 (ASSUMED, matched to the measurement); phi = 0.9 is the conservative case; phi = 0 is the chance case.

**Arm correlation rho_AC (ASSUMED, not measurable here).** C_56 = A_53 plus three sector inputs. Their overlap with the 53 is high (R-squared 0.83, 0.74, 0.50 from `feature_overlap_v3.json`), so the two models' scores are probably highly correlated; the same recipe, folds and training rows are used. Central 0.8; range 0.5 to 0.95. This is the single biggest unmeasurable driver: it changes the answer by about 2x. It can be measured from the immutable per-fold scores after the run (correlation of the daily scores of the two arms), and I propose it be reported then (descriptive only).

## 5. Results: SX5 (paired, C_56 minus A_53)

Edge units: percentage points of the daily top-5 excess = percentage points per trade. "34 / 30 folds" = all folds / burn-in B2 (folds 4-33). MDE80 = smallest true paired edge for which the PASS rule fires in at least 80% of simulations. R4 columns include the holdout sign check. Null columns: rate at which R1 and R2 both pass when the true edge is zero (nominal 2.5% / 5%). All cells: 1,000 simulations.

| phi | rho_AC | n_eff of D (of 642) | top-5 repeat | MDE80, 2.5% bound, R1+R2 (34 / 30 folds) | MDE80, 5% bound (34 / 30) | MDE50, 2.5% (34) | MDE80, 2.5% with R4 (34) | false pass R1+R2, 2.5% / 5% (34) | false pass R1+R2+R4, 5% (34) |
|---|---|---|---|---|---|---|---|---|---|
| 0.0 | 0.5 | 667 | 10.5% | 0.18 / 0.18 | 0.17 / 0.17 | 0.13 | 0.20 | 2.1% / 3.2% | 1.7% |
| 0.0 | 0.8 | 679 | 10.6% | 0.15 / 0.16 | 0.14 / 0.14 | 0.11 | 0.16 | 1.9% / 3.3% | 1.4% |
| 0.0 | 0.95 | 587 | 10.7% | 0.11 / 0.11 | 0.10 / 0.10 | 0.08 | 0.12 | 2.7% / 4.4% | 2.0% |
| 0.5 | 0.5 | 450 | 32.5% | 0.21 / 0.22 | 0.20 / 0.20 | 0.15 | 0.23 | 2.7% / 4.2% | 2.2% |
| **0.5** | **0.8** | 484 | 32.4% | **0.16 / 0.16** | 0.15 / 0.15 | 0.11 | 0.18 | 3.8% / 5.5% | 3.1% |
| 0.5 | 0.95 | 554 | 32.4% | 0.12 / 0.12 | 0.11 / 0.11 | 0.08 | 0.13 | 2.8% / 4.2% | 2.6% |
| 0.9 | 0.5 | 224 | 67.4% | 0.30 / 0.31 | 0.28 / 0.28 | 0.20 | 0.33 | 2.8% / 4.9% | 3.0% |
| 0.9 | 0.8 | 275 | 66.9% | 0.22 / 0.23 | 0.21 / 0.21 | 0.15 | 0.24 | 2.5% / 3.9% | 2.2% |
| 0.9 | 0.95 | 345 | 67.3% | 0.14 / 0.15 | 0.13 / 0.13 | 0.10 | 0.16 | 3.5% / 5.0% | 2.4% |

Power at assumed true edges (34 folds, 2.5% bound, R1 + R2):

| phi | rho_AC | 0.05 pp | 0.10 pp | 0.15 pp | 0.20 pp | 0.30 pp |
|---|---|---|---|---|---|---|
| 0.0 | 0.5 | 10.9% | 33.0% | 65.3% | 86.9% | 99.7% |
| 0.0 | 0.8 | 14.9% | 44.5% | 79.5% | 96.4% | 99.7% |
| 0.0 | 0.95 | 25.7% | 73.0% | 96.2% | 99.2% | 99.2% |
| 0.5 | 0.5 | 10.6% | 28.6% | 51.6% | 74.6% | 97.3% |
| **0.5** | **0.8** | 14.7% | 42.8% | 73.3% | 94.3% | 99.8% |
| 0.5 | 0.95 | 21.4% | 67.6% | 94.7% | 98.3% | 98.3% |
| 0.9 | 0.5 | 8.2% | 17.8% | 34.2% | 50.8% | 80.4% |
| 0.9 | 0.8 | 10.1% | 27.0% | 49.6% | 73.5% | 96.2% |
| 0.9 | 0.95 | 18.3% | 50.5% | 82.6% | 97.0% | 99.5% |

## 6. Results: SX10 (paired, C_56 minus A_53)

| phi | rho_AC | n_eff of D (of 642) | top-5 repeat | MDE80, 2.5% bound, R1+R2 (34 / 30 folds) | MDE80, 5% bound (34 / 30) | MDE50, 2.5% (34) | MDE80, 2.5% with R4 (34) | false pass R1+R2, 2.5% / 5% (34) | false pass R1+R2+R4, 5% (34) |
|---|---|---|---|---|---|---|---|---|---|
| 0.0 | 0.5 | 674 | 10.3% | 0.26 / 0.26 | 0.24 / 0.24 | 0.18 | 0.28 | 1.9% / 2.8% | 1.6% |
| 0.0 | 0.8 | 686 | 10.7% | 0.20 / 0.21 | 0.19 / 0.19 | 0.14 | 0.22 | 2.8% / 5.0% | 2.6% |
| 0.0 | 0.95 | 612 | 10.7% | 0.15 / 0.16 | 0.14 / 0.15 | 0.11 | 0.16 | 2.5% / 4.9% | 2.3% |
| 0.5 | 0.5 | 430 | 32.6% | 0.31 / 0.32 | 0.29 / 0.29 | 0.21 | 0.33 | 3.6% / 5.6% | 3.3% |
| **0.5** | **0.8** | 522 | 32.3% | **0.24 / 0.25** | 0.23 / 0.23 | 0.17 | 0.27 | 2.4% / 3.2% | 1.2% |
| 0.5 | 0.95 | 563 | 32.2% | 0.16 / 0.17 | 0.15 / 0.15 | 0.11 | 0.18 | 2.6% / 4.1% | 2.0% |
| 0.9 | 0.5 | 153 | 67.8% | 0.50 / 0.51 | 0.47 / 0.47 | 0.33 | 0.56 | 4.5% / 5.3% | 2.5% |
| 0.9 | 0.8 | 189 | 67.3% | 0.36 / 0.37 | 0.35 / 0.34 | 0.26 | 0.41 | 3.1% / 5.1% | 1.6% |
| 0.9 | 0.95 | 283 | 67.4% | 0.22 / 0.23 | 0.21 / 0.21 | 0.16 | 0.25 | 3.7% / 5.5% | 2.7% |

Power at assumed true edges (34 folds, 2.5% bound, R1 + R2):

| phi | rho_AC | 0.05 pp | 0.10 pp | 0.15 pp | 0.20 pp | 0.30 pp |
|---|---|---|---|---|---|---|
| 0.0 | 0.5 | 7.5% | 17.6% | 35.9% | 58.2% | 90.7% |
| 0.0 | 0.8 | 9.6% | 28.9% | 55.3% | 79.0% | 97.7% |
| 0.0 | 0.95 | 17.2% | 46.4% | 78.4% | 95.2% | 98.6% |
| 0.5 | 0.5 | 8.7% | 15.3% | 29.2% | 46.3% | 77.5% |
| **0.5** | **0.8** | 7.0% | 20.0% | 40.3% | 64.2% | 92.9% |
| 0.5 | 0.95 | 14.1% | 40.8% | 73.5% | 91.8% | 99.1% |
| 0.9 | 0.5 | 6.2% | 9.9% | 16.3% | 23.2% | 41.4% |
| 0.9 | 0.8 | 7.5% | 13.3% | 23.2% | 34.5% | 63.9% |
| 0.9 | 0.95 | 10.0% | 24.9% | 46.2% | 70.2% | 95.5% |

## 7. How the pieces of the rule change the answer

- **Holm (2.5% / 5%).** The 2.5% column is what the rule guarantees on its own; the 5% column applies only if the other horizon clears 2.5%. The two differ by only 0.01 to 0.03 pp, so Holm barely matters for power; what matters is the lower bound itself. Holm's joint power (both horizons true) lies between the two columns; I did not simulate the two horizons jointly (they share stocks and days, so they are positively dependent).
- **Programme-wide count (11-12 comparisons), context only, not part of the rule.** If a Bonferroni correction over 12 comparisons were applied (0.05/12 = 0.42% one-sided), the detectable edge would rise by about 24% (normal approximation: (z for 0.42% + z for 80%) / (z for 2.5% + z for 80%) = 3.48 / 2.80), i.e. SX5 central about 0.20 pp and SX10 central about 0.30 pp. The chance that at least one of 11 or 12 true-zero comparisons passes at 5% is 43% to 46% (1 - 0.95^11 and 1 - 0.95^12); that is why a PASS only proposes a forward shadow test.
- **R1 (60% of folds).** R1 alone at a zero true edge passes 9.5% to 14% of the time (consistent with the 11.5% binomial arithmetic in the findings file); at the R2 minimum detectable edge R1 passes 87% to 89% of the time, so it adds only 0.01 to 0.02 pp to the minimum detectable edge (R2 alone: SX5 central 0.152, SX10 central 0.228 pp, against 0.162 and 0.245 with R1). R2 carries the inference, as S-6 says.
- **Burn-in B2 (30 folds).** Costs at most 0.01 pp (about 12% fewer days). Cheap for what it buys.
- **R4 (133 holdout days).** At a true edge equal to the R1+R2 minimum detectable edge, the holdout sign is positive about 90% of the time; the joint power at that edge falls from 80% to about 72% to 74%, so the 80%-power edge rises by 0.01 to 0.06 pp (columns "with R4"). Under a true zero edge R4 is a coin flip (47% to 52%), which is its job: it removes about half of the false passes.
- **False-pass rate under no effect (checked by simulation).** Per horizon, R1 + R2: 1.9% to 4.5% at the 2.5% bound (nominal 2.5%) and 2.8% to 5.6% at the 5% bound (nominal 5%); the block-2h bootstrap holds the nominal level within simulation noise (SE about 0.5 points) except for a mild excess at the persistent corners. **For the pair under Holm (a pass of either horizon, independent nulls): 4.0% to 7.5% for R1 + R2 and 2.1% to 4.5% for R1 + R2 + R4**; the highest values are at phi 0.5 to 0.9. So the family-wise error is about 4% to 7.5% before R4 and 2% to 4.5% with R4. (This was measured with 1,000 independent pairs; SE about 0.8 points.)

### Single-arm benchmark comparison (secondary reference): A_53 against every stock

| phi | SX5 MDE80 2.5% (34 / 30 folds) | SX5 MDE80 5% | SX5 false pass 2.5% / 5% | SX10 MDE80 2.5% (34 / 30) | SX10 MDE80 5% | SX10 false pass 2.5% / 5% |
|---|---|---|---|---|---|---|
| 0.0 | 0.15 / 0.15 | 0.14 | 2.6% / 4.3% | 0.21 / 0.22 | 0.20 | 3.4% / 4.1% |
| 0.5 | 0.19 / 0.19 | 0.18 | 3.2% / 5.5% | 0.27 / 0.28 | 0.26 | 2.5% / 3.8% |
| 0.9 | 0.25 / 0.26 | 0.24 | 3.2% / 5.5% | 0.44 / 0.44 | 0.41 | 3.2% / 5.6% |

(A_53 against every stock: no sector comparison, one arm, so the paired variance saving does not apply; this is the same kind of statistic as td-v1 and fd_v1. The td-protocol-v2 draft's power statement, "about +0.12% per trade at 396 days", is lower than every single-arm SX10 figure above even before scaling 396 days up to 642 (roughly x1.27 less data); I have not seen its derivation and do not rely on it.)

### Robustness of the central conclusion (phi 0.9, rho_AC 0.8, 34 folds, 1,000 simulations)

| Horizon | Variant | MDE80 2.5% | MDE80 5% | false pass 2.5% / 5% | n_eff of D |
|---|---|---|---|---|---|
| SX5 | base (measured tails, t with 4.9 df) | 0.22 | 0.21 | 2.5% / 3.9% | 275 |
| SX5 | normal tails | 0.22 | 0.21 | 2.8% / 4.2% | 279 |
| SX5 | heavy tails (t, 4 df) | 0.22 | 0.21 | 3.1% / 4.7% | 267 |
| SX5 | volatility regimes (common volatility multiplier, AR 0.98) | 0.23 | 0.21 | 2.5% / 3.7% | 277 |
| SX5 | 10 sector-style groups (return factor 10% of variance, 30% of score variance shared in the group) | 0.22 | 0.21 | 2.5% / 4.1% | 253 |
| SX10 | base | 0.36 | 0.35 | 3.1% / 5.1% | 189 |
| SX10 | normal tails | 0.36 | 0.34 | 3.1% / 4.5% | 208 |
| SX10 | heavy tails (t, 4 df) | 0.38 | 0.35 | 2.1% / 4.2% | 205 |
| SX10 | volatility regimes | 0.38 | 0.34 | 2.8% / 4.9% | 202 |
| SX10 | 10 sector-style groups | 0.37 | 0.35 | 3.1% / 4.8% | 196 |

None of these structural changes moves the minimum detectable edge by more than 6%. The group and regime structures are ASSUMED shapes, not measured ones.

## 8. Realistic edge, and the adequacy verdict

**Evidence in the repo (all read, none recomputed here).**
- Models of A-like type show no skill: fd-protocol-v1 5D (2023-07 to 2025-01, 396 days): best-5 daily edge over every stock **-0.011 pp** (lower bound -0.155), 10 of 21 folds won; td-protocol-v1 10D (same period): picks **-0.34% per trade against -0.22% for every stock** (about -0.12 pp), 8 of 21 folds won; AUC 0.53 to 0.58. ps12 (25 days, brain vs random): no better than chance. h05 power support: its detectable-edge tables are for per-trade edges of 0.5 to 2.0 pp at 30 to 90 sessions, far larger than anything here.
- Hence the only prior for A_53 itself is "about zero"; an increment of three sector inputs on top can only be small.

**Translating a skill increment into pp (ASSUMED).** Expected top-5 excess = (gain in cross-sectional correlation between score and forward return, "delta IC") x (cross-sectional standard deviation of the forward return) x (mean of the top 5 of 47 standard normals = 1.676). Cross-sectional standard deviation = measured total sd x sqrt(1 - common share): SX5 2.85%, SX10 3.99%. That is 4.8 pp (SX5) and 6.7 pp (SX10) of top-5 excess per unit IC. Assumed range for what the three inputs add: delta IC 0.005 to 0.02 (the repo's models have an AUC of 0.53 to 0.58, i.e. IC of order 0.02 to 0.05 in total). **Realistic paired edge: SX5 0.02 to 0.10 pp; SX10 0.03 to 0.13 pp per trade.** A stretch case of 0.15 pp is shown in the tables.

**Power at those sizes (central cell phi 0.5, rho_AC 0.8; 34 folds, 2.5% bound, R1 + R2):** SX5 0.05 pp: 15%, 0.10 pp: 43%; SX10 0.05 pp: 7%, 0.10 pp: 20%, 0.15 pp: 40%. In the pessimistic corner (phi 0.9, rho 0.5) power at 0.10 pp is 18% (SX5) and 10% (SX10).

**Verdict: the experiment does NOT have adequate power for a realistic edge.** It has adequate power only for edges of about 0.16 (SX5) and 0.24 (SX10) pp or more at the central assumptions, and as much as 0.30 and 0.50 pp at the pessimistic corner. For a realistic 0.05 pp, 4 in 5 runs would not say PASS even though the inputs help. SX5 is better than SX10 by a factor of about 1.5 (it also needs a smaller edge because the 5-day returns are less noisy and its overlap shorter). Chance of a false PASS if the inputs do nothing: 2% to 4% per horizon (about 2% to 4.5% across both horizons with R4).

What this means for use: the pair is a **screening test for a large effect**. A PASS would be informative (a lucky pass is rare), a failure is only weakly informative.

## 9. What INCONCLUSIVE means, and the wording fix

As written, INCONCLUSIVE fires only when R3 fails; here R3 will always hold. A run that cannot reach the lower bound because it is underpowered ends as NO IMPROVEMENT, which reads as a negative finding. **PROPOSED fix** (a wording and reporting rule, no new threshold on the primary quantity, decided before any result): beside R2 always print the one-sided 95% upper bound of the mean of D_t from the same bootstrap. Then:
- IMPROVES: R0 to R4 met (unchanged).
- NO IMPROVEMENT DEMONSTRATED (underpowered): R1 or R2 not met, and the upper bound is above the edge below which the owner no longer cares (E*). Reads: "cannot rule out a gain up to X pp".
- NO IMPROVEMENT: R1 or R2 not met, and the upper bound is at or below E*. Reads: "a gain larger than E* is unlikely".
- INCONCLUSIVE: R3 not met (unchanged).
E* is the owner's number (PROPOSED default: 0.10 pp for SX5 and 0.13 pp for SX10, the top of the realistic range); with the central standard errors (0.06 and 0.08 pp) a zero true edge gives an upper bound near 0.10 and 0.13, so a "NO IMPROVEMENT" outcome needs a mean at or below zero. This keeps the primary pass rule unchanged. If the owner prefers not to add the second word, the minimum rule is: the report prints the upper bound and the sentence "a failure does not show that the inputs do nothing".

## 10. Limitations of this power analysis

1. **iid in time (ASSUMED).** Daily returns are iid; the measured daily-mean autocorrelation is negative at lags above h (-0.15 at 5D) and positive far out at 10D (+0.2 at lags 16 to 18); neither is modelled. The effective sample of D_t is therefore only approximately right.
2. **No regime dependence.** A volatility-regime sensitivity and a sector-factor sensitivity move nothing by more than 6%, but a model whose edge exists only in some market types (the true situation for most signals; rising, sideways and falling stretches behave very differently in td-v1) has less power than the table says: R1 requires 60% of folds, and a regime-limited edge would fail it. The tables assume a constant edge over all 34 folds and the holdout.
3. **Assumed pick persistence (phi) and arm correlation (rho_AC).** Only phi has a (weak) real analogue: nine pairs of one model over three weeks, post-holdout. rho_AC is a pure assumption; it moves the answer by about 2x. Neither has been measured on the two arms, because no model may be fitted here.
4. **The edge is one number.** The model gives every day the same expected gain; real edge varies by day and stock, is probably concentrated in few names, and is largest where it is least estimable.
5. **Heavy tails and gaps.** Tail shape, volatility regimes and groups tested; real jumps (earnings, corporate actions, circuit limits) and dropped windows (15 above 25% moves) are not. Forward returns are close to close (the harness metric), not the barrier trade result for SX10.
6. **Effective sample.** Even in the best case (chance picks) the 642 days give about 650 independent differences; with persistent picks 150 to 350. The market-wide daily mean (199 and 78 effective days) is the wrong yardstick for D_t but the right one for any statement about the market-level outcomes.
7. **47-stock cohort.** Survivor-biased stocks; thin sector groups; the simulation uses all 47 each day (the real count is 45 to 47); the signed cohort is the only place the result applies to.
8. **Programme-wide multiplicity.** Twelve parallel hypotheses on the same prices: a PASS has a high chance (43% to 46% if all were true nulls at 5%) of being a lucky one somewhere in the programme; it is not corrected in the rule.
9. **Stationary-edge holdout.** R4 power assumes the holdout edge equals the development edge; any decay lowers it. The holdout prices were also exposed in earlier diagnostics (ledger).
10. **Simulation noise.** 1,000 simulations per cell: rates +/-0.5 (low rates) to +/-1.6 (50%) points; minimum detectable edges +/-3% (Monte Carlo ranges in the JSON). Cells are not independent (common random numbers across the edge grid).
11. **The bootstrap needs enough blocks.** 642 days with 20-day blocks is 32 blocks; the lower bound of a 20-day block is noisier than the 10-day case and the false-pass rate drifts to 3% to 4.5% at the 2.5% level at the persistent corners.

## 11. S-9 text proposed for both protocols (PROPOSED)

> **S-9 Minimum detectable edge.** Before signing, the study computed the smallest true paired edge (C_56 minus A_53, percentage points of the daily top-5 excess, equal to percentage points per trade) that this procedure (R1 and R2 with the block-2h bootstrap, Holm 2.5% / 5%, R4) would pass 80% of the time, on synthetic data with the dependence measured on the development period (`backend/scripts/sx_power_analysis.py`, seeds recorded, 1,000 simulations per cell, results `docs/brain/evidence/sector_prep/sx_s9_power_v1.json`). Under the central assumptions (persistence of the top picks 0.5, correlation between the two arms' scores 0.8, 34 folds) the answer is **[SX5: about 0.16 pp per trade, 50% power at 0.11 pp; SX10: about 0.24 pp per trade, 50% power at 0.17 pp]**; over the assumed ranges it is **[SX5: 0.11 to 0.30 pp; SX10: 0.15 to 0.50 pp]**. The edge that three sector inputs can realistically add to a 53-input model is **[SX5: 0.02 to 0.10 pp; SX10: 0.03 to 0.13 pp]**, so the chance of a PASS at such an edge is **[SX5: about 15% to 45%; SX10: about 7% to 20%]**. If the true edge is zero the chance of a false PASS is about **[2% to 4% per horizon; 2% to 4.5% across both horizons with R4]**. The experiment is therefore **not adequately powered for a realistic edge**; it can detect a large edge. A PASS only proposes a forward shadow test. A result that does not meet R1 and R2 is **not evidence that the sector inputs do nothing**; the report prints the one-sided 95% upper bound of the mean paired difference beside R2 and the words in section 9 apply. After the run the correlation between the two arms' daily scores is reported (descriptive) so the central assumption can be checked; no threshold, block, seed or metric changes after any result. The programme-wide count of 11 to 12 comparisons is recorded in the register; if the owner wished to correct for it the detectable edge would be about 24% larger.

Bracketed figures are the simulation's central values; they are produced by the script and must be re-copied from the JSON if the script, seeds, measured inputs or assumed ranges change.

## 12. Owner decisions this needs

1. Accept or change the assumed ranges (phi 0.5 central; rho_AC 0.8 central; realistic increment 0.02-0.10 / 0.03-0.13 pp). They are assumptions.
2. Accept the wording fix in section 9 (add the upper bound; two NO IMPROVEMENT words) and set E*, or reject it and keep only the sentence "a failure does not show that the inputs do nothing".
3. Decide whether SX10, with a central minimum detectable edge about 1.5x that of SX5 and a realistic-edge power of 7% to 25%, should be run at all or folded into SX5 as a descriptive extension. That is a programme choice; this note only provides the numbers.
4. Confirm that the burn-in (30 folds) and R4 are adopted; both cost at most 0.01 to 0.06 pp.
