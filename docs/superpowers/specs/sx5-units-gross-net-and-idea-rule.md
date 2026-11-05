# SX5: units, gross versus net, and the statistical case for the ideas-per-fold rule (PROPOSED, unsigned)

Date: 2026-11-04 (owner clarifications). Status: **analysis and wording only. Nothing signed, nothing committed.** No model was fitted, no arm or holdout evaluated, no holdout-period (2026-02-01 to 2026-08-15) outcome computed, no prod, Kite or `.env`. Code: `backend/src/swing_trade_ml/ml/sx_verdict.py` (unit guard), `backend/scripts/sx_idea_rule_simulation.py` (neutral simulation; tests `backend/tests/test_sx_idea_rule_simulation.py`), results `docs/brain/evidence/sector_prep/sx_idea_rule_sim_v1.json`. Labels: **MEASURED** (from development data), **ASSUMED** (modelling choice), **PROPOSED** (for the owner).

## 1. Units (the fixed wording, repeated in every SX document)

> **UNITS.** The quantity is the daily paired difference D_t = (C_56 daily top-5 excess return) minus (A_53 daily top-5 excess return). A daily top-5 excess is the mean forward 5-session return of that day's 5 picks minus the mean forward 5-session return of all eligible stocks that day, written as a FRACTION of the money in a trade: 0.0017 = 0.17 percentage points (pp) = 17 basis points (bps) of one 5-session holding return. Because the daily value is already an average over that day's ideas, "per day" and "per trade" are the same number. Nothing here is annualised. MDE_H = 0.0018 means 0.18 pp (18 bps) of one holding return, per trade. Typing 0.18 would mean 18 percentage points per trade (100 times too large). SX10 would use the 10-session return.

| Written as | Meaning | Where used |
|---|---|---|
| 0.0018 (fraction) | 0.18 pp = 18 bps of one holding return, per trade | the code (`VerdictParams.mde_h`) |
| 0.18 pp | the same number in percentage points | documents, owner sign line |
| 18 bps | the same number in basis points | cost tables |
| 0.18 as a fraction | **18 percentage points per trade: a unit error** | refused by the code |
| per year | not shown; 0.18 pp per 5-session trade is not "0.18 pp a year" and is not multiplied by trades per year anywhere | never used |

**Unit guard (code, PROPOSED, tests added).** `VerdictParams` now (a) carries `units="fraction_of_return"` and refuses any other tag; (b) refuses `mde_h >= 0.02` (2 pp per trade, more than five times the largest value in the 0.12 to 0.34 pp range) with the message "looks like percentage points: pass a FRACTION (0.0018 for 0.18 pp; use mde_h_from_pp)"; (c) offers `mde_h_from_pp(0.18) = 0.0018`, which itself refuses non-numbers, zero, negatives and 2 pp or more. A value that is too small is not refused (the existing tests use 1e-6 as "very wide"; the guard is one-sided on purpose). The verdict code hash and every parameter-set hash therefore change (the parameter JSON gains `units`); the signing text must use the new hashes (section 6).

**Recommended signed values (PROPOSED, the owner signs).** SX5 **MDE_H = 0.18 pp = 0.0018.** Reason: 80% power for the PASS rule (R1 + R2 + R4) is **0.183 pp** on the 565 counted days (R1 + R2 alone: **0.170 pp**); the plausible range over the assumed corners is **0.12 to 0.34 pp**. The central assumptions are **ASSUMED**: day-to-day persistence of the top picks 0.5 and correlation between the two arms' scores 0.8; neither can be measured before the run. **E\* = 0.37 pp = 0.0037 (the break-even gain, see section 2.4) is a REPORTED SENTENCE, not an outcome rule:** no outcome word depends on it unless the owner signs it into the rule.

## 2. Gross versus net

### 2.1 What the primary quantity is (GROSS)
D_t is **gross**: forward returns from the harness (entry at the decision-day close, exit at the close of the 5th session after), no costs, no slippage, no taxes, no +2/-4 barrier. It is also **raw**: no stop or target. The protocol's PASS, FAIL and INCONCLUSIVE depend on gross D_t only. This is not changed.

### 2.2 Costs (MEASURED from the repo's cost model, docs/brain/COSTS-CHECK-2026-10.md)
Round trip = buy taxes 11.9 bps + sell taxes 10.4 bps + slippage twice + the flat depository fee on the sell (Rs 15.93).
- **Rs 40,000 trade, 5 bps slippage a side: 22.3 + 10 + 3.98 = 36.3 bps = 0.363%** (the SX default).
- **Rs 1,00,000 trade, 10 bps slippage a side (the h05 large-cap setting): 22.3 + 20 + 1.59 = 43.9 bps = 0.439%.**
- **Flag, not edited.** `brain/lanes/h05_protocol.py` `COST_UNITS["depository_charge"]` says Rs 15.93 is "about 15.9 bps of a Rs 1,00,000 order". It is **about 1.59 bps** (15.93 / 100,000). Consequently `round_trip_cost_bps_approx` {large 58, mid 78, small 88} is about **14 bps too high**: the same arithmetic gives about 44 / 64 / 74. The sx script `round_trip_cost_bps` uses the correct 1.59. Recommend the owner has the h05 file corrected in its own change (it is hashed into the h05 protocol, so the change needs its own review). Nothing in SX depends on it.

### 2.3 Why costs partly cancel in C minus A, and when they do not
D_t = gross(C) minus gross(A) on the same days. If both arms pay the same cost per idea, the cost subtracts out. The cancellation is exact when **both arms have the same new-idea share** s (new ideas, after the td-protocol-v1 no-repeat rule, divided by 5 picks times retained days). It fails when the arms rotate picks at different speeds:

> net paired difference = gross paired difference minus RT x (s_C minus s_A)   [pp per trade slot; RT = round-trip cost]

where the cost of a day's slot is RT times the probability that the slot is a newly bought stock (a pick still open from an earlier idea is not bought again). **First-order and ASSUMED**: cost is spread evenly over a day's five slots; held picks earn their excess without extra cost.

Neutral illustration (random top-5 lists, **no arm result used**; SX5 calendar, 565 counted days; new-idea share s = 0.689 at pick persistence 0, 0.560 at 0.5, 0.337 at 0.9):

| Arm persistence (C versus A) | s_C minus s_A | Cost shift at RT 0.363% | at RT 0.439% | Versus MDE_H 0.18 pp |
|---|---|---|---|---|
| equal (any) | 0 | 0 | 0 | none: costs cancel |
| 0.5 versus 0.0 | -0.129 | -0.047 pp | -0.057 pp | 26% to 31% |
| 0.9 versus 0.5 | -0.223 | -0.081 pp | -0.098 pp | 45% to 54% |
| 0.9 versus 0.0 | -0.352 | -0.128 pp | -0.155 pp | 71% to 86% |

A stickier C (the more probable direction, since sector inputs move slowly) **pays less**, so net is **better** than gross by the shift; a faster C pays more. So "net improvement" differs from the gross paired difference by (turnover difference) times (round-trip cost). Which arm is stickier is **unknown before the run** (descriptive pick-repeat shares of both arms will be reported after it, labelled descriptive).

### 2.4 E\* and costs
E\* = 0.37 pp is the **break-even** gain: one round trip costs 0.36% to 0.44%, buying every stock under the traded +2/-4 rule lost 0.36% to 0.38% a trade (fd_v1, h05; MEASURED in the repo), and the A-like top-5 showed no edge, so the top-5 would need about +0.37 pp over A to earn zero after costs. It compares **net-of-everything traded outcomes** with a **gross raw** paired difference only after adjustment for (i) the turnover shift above, (ii) next-open entry and the barrier rule, which the harness does not model. Hence E\* is a **reported sentence** ("a gain of this size would not by itself have paid for trading"), never a gate.

### 2.5 The diagnostic after-cost result (DIAGNOSTIC X1, no promotion weight unless explicitly signed)
Predeclared executable rule, in words: on each retained decision day take each arm's top 5. Apply td-protocol-v1 rule 2 exactly as `count_ideas(rule="no_repeat")` does: a stock counted as an idea on day i is open through day i + 5 and is not a new idea again until day i + 6. Every new idea is charged one round trip, **0.363% (primary) and 0.439% (sensitivity)**. The diagnostic is gross D_t minus RT x (s_C minus s_A), with its mean, its one-sided 95% block-bootstrap bounds (same block and seed as the primary) and the two shares s, reported side by side with the gross figure. **Entry:** X1 uses the harness's own **decision-day close** forward return, because it is a pure function of the immutable per-fold records (no new price access, no new fit) and so is reproducible. A real trade cannot enter at a close it only learns after the session; the h05 trade enters at the **next session's open** with buy slippage against it, adds the overnight gap and uses the +2%/-4% barrier path. The gap is common to both arms to first order and mostly cancels in D_t, but adds noise and a small bias; the barrier path changes the payoff shape. X1 therefore **estimates a ceiling for the after-cost paired difference, not an executable one**. The primary quantity is not changed. X1 never changes an outcome word.

## 3. The ideas-per-fold rule: statistical justification (independent of results)

### 3.1 Rule
A counted fold is eligible if both arms are `ok`, it has at least 10 retained test days and at least **20 ideas** (`idea_rule="no_repeat"`). R3 (data sufficiency): at least 12 eligible folds, at least 100 ideas over them, at least 2h retained days. Variants in code: `no_repeat` (default), `raw_per_day` (5 a day, never binds), `days_only` (no idea condition).

### 3.2 What the threshold protects against
R1 counts each eligible fold as **one equal vote** (the sign of the fold mean of D_t). A fold whose mean rests on very few independent observations has a sign that is almost a coin flip, yet it casts the same vote as a well-measured fold. Two things are needed: (i) ideas must be counted as **independent** observations, and (ii) a minimum number of them.

**(i) Independence (MEASURED, development data, docs/superpowers/specs/2026-11-08-sx-s9-power-analysis.md and sx_s9_power_v1.json).** One stock's 5-session forward return is autocorrelated at lags 1/2/3/4 of 0.78/0.58/0.37/0.16, its label 0.57/0.38/0.23/0.09: the same stock picked on consecutive days is **one** observation seen several times. The market-wide part (cross-stock correlation of forward returns 0.27) cancels inside every top-5-minus-all excess and inside C minus A, so it does not reduce the count; the daily mean series stays autocorrelated (0.77/0.56/0.34/0.09), which is why bootstrap blocks are 2h days. Hence **distinct stock episodes under the no-repeat rule (open through day i + h) are the right count of approximately independent observations**; the raw 5-a-day count is not (it counts the same stock up to 6 times) and "days only" ignores the picks.

**(ii) Size.** Let sigma_I be the standard deviation of one idea's paired difference and delta the true paired edge. A fold mean over N independent ideas has standard error sigma_I / sqrt(N) and is positive with probability Phi(delta sqrt(N) / sigma_I). In the S-9 structure (ASSUMED) the standard deviation of the daily five-pick paired difference is 0.93 / 1.27 / 1.56 pp (optimistic / central / pessimistic), so **sigma_I = that x sqrt(5) = 2.1 / 2.85 / 3.5 pp** (the central value equals the MEASURED cross-sectional standard deviation of one stock's 5-day excess, 2.85%). For R1 to be able to fire at all, a fold must be positive more often than R1's 60% share when the true edge equals MDE (0.183 pp):

| Criterion | N needed, optimistic / central / pessimistic sigma_I |
|---|---|
| P(fold positive at MDE) at least 0.60 (R1's own share; the **floor**) | 8 / **16** / 23 |
| P(fold positive at MDE) at least 0.65 | 19 / 36 / 54 |
| P(fold positive at MDE) at least 0.70 | 35 / 67 / 100 |
| Fold-mean standard error no larger than MDE (a "reliable fold") | 129 / 243 / 365 |

At the current threshold of 20 ideas, P(fold positive at MDE) = 0.65 / 0.61 / 0.59, and the fold-mean standard error is 0.46 / 0.64 / 0.78 pp (3 to 4 times MDE). **Reading:** 20 ideas is at the **floor** (R1 can fire when the edge is at MDE) and sits inside the 8 to 23 range of the floor across the sigma_I assumptions. It is **not** a reliability threshold: no per-fold threshold of that kind is attainable, because a 19-day fold contains at most about 65 distinct ideas even with random picks (section 3.3). This is the reason S-9 treats R1 as a consistency check and R2, the pooled bootstrap, as the inference.

### 3.3 Simulated pass frequencies (NEUTRAL pick proxy; no arm result, no return)
Real SX5 development calendar (30 counted folds, 565 days; folds of 13 to 21 days; 45 to 47 eligible stocks a day). Each day's top 5 are the five highest of an AR(1) score with persistence phi (names only), counted by the code's own `count_ideas`. 1,000 simulated runs per row. `no_repeat` counts distinct episodes; the fold clock resets at each fold start.

| phi (top-5 repeat share) | Median / 5th percentile ideas in a 19-day fold (no_repeat) | P(19-day fold has >= 20 ideas) | P(13-day last fold has >= 20) | Mean eligible folds of 30 | P(fewer than 12 eligible folds) | P(R3 data fail) |
|---|---|---|---|---|---|---|
| 0 (10%) | 65 / 61 | 1.000 | 1.000 | 30.0 | 0.000 | 0.000 |
| 0.5 (32%) | 53 / 48 | 1.000 | 1.000 | 30.0 | 0.000 | 0.000 |
| 0.9 (67%) | 32 / 28 | 1.000 | 0.947 | 29.9 | 0.000 | 0.000 |
| 0.95 / 0.98 / 0.995 (200 runs) | 28 / 24 / 22 | 1.000 | not shown | 29.4 / 28.4 / 25.2 | 0.000 | 0.000 |

Variants at the same phi (0 / 0.5 / 0.9): `raw_per_day` and `days_only` pass every fold with probability 1.000 (mean eligible folds 30.0); `no_repeat` is the only variant that can fail a fold, and only in the stickiest cases. **Stricter thresholds, same proxy** (the 0.65 criterion, 36 ideas): P(19-day fold passes) = 1.00 / 1.00 / **0.11**, mean eligible folds 30.0 / 29.7 / **4.0**, **P(fewer than 12 eligible folds) = 0 / 0 / 1.00**. So a threshold of 36 would make INCONCLUSIVE-by-data **certain** when the top picks are sticky (phi 0.9; the only measured analogue, the stored production score, has rank correlation 0.59 and a 40% top-5 repeat share, between phi 0.5 and 0.9). SX10 (deferred, h = 10) at phi 0.9: median 25 ideas, P(19-day fold >= 20) = 0.989, mean eligible folds 28.7, P(< 12) = 0; last 13-day fold passes with probability 0.30.

### 3.4 Conclusion
1. **The current default (`no_repeat`, 20 ideas, R3 12 folds and 100 ideas) is the statistically justified variant** by the argument above: `no_repeat` because it counts approximately independent observations; 20 because it is the R1-share floor (16 at the central assumption, 8 to 23 over the range). `raw_per_day` is not justified (it overcounts a repeated stock up to 6 times and cannot bind, so it protects against nothing). `days_only` is not justified (it ignores the picks the vote rests on).
2. **The rule does not force INCONCLUSIVE by itself** on the neutral proxy: P(fewer than 12 eligible folds) is 0.000 for every phi up to 0.995 on the SX5 calendar. A highly repetitive model (phi near 1) approaches 5 ideas times ceil(19/6) = 20 per fold, i.e. the threshold, but the 12-fold minimum still holds in the runs shown (25 of 30 eligible at phi 0.995).
3. **Design limitation, reported to the owner and NOT a reason to change the rule.** Any threshold that made a single fold's vote reliable (standard error at most MDE) needs 129 to 365 ideas, which a 19-day fold cannot contain. Individual fold votes are therefore weak, R1 adds little to the minimum detectable edge (0.01 to 0.02 pp, S-9) and the inference rests on R2. A stricter value (36 and above) would make INCONCLUSIVE-by-data likely for sticky pick lists and is **not recommended**. The rule is fixed before any result and must not be loosened or tightened after one.
4. **No change to any default was made.** `idea_rule="no_repeat"` and `min_fold_picks=20` stay as they were. (The earlier text of S-6 in the two drafts said the 20-pick condition "can never bind" because it counted 5 a day; that text described the superseded `raw_per_day` count and is corrected in this round.)

## 4. SX10
Status **DEFERRED**: no confirmatory training, no holdout use, no registry authorisation; revisit only through a new protocol id (see `sx10-power-and-redesign-recommendation.md`). The locked holdout is not changed to improve power. The raw 10-session return calculation text is kept.

## 5. What changed in code and hashes
- `ml/sx_verdict.py`: `MDE_H_UNITS`, `MDE_H_MAX_PLAUSIBLE`, `mde_h_from_pp`, `VerdictParams.units`, the guard in `__post_init__`. **The verdict-code sha256 and parameter-set sha256 change** (SX5 illustrative at MDE_H 0.0018: parameter set `324d7f7bba075d7398780395cbcdb5842eb2b4dc7dc03288d86a1fbae5189a8b`; code `109661cad3511c373840b76ad864f303f2e525b958e5d4edabb1d8af9af99b72`, CRLF-normalised, working copy; both are recomputed at signing).
- `tests/test_sx_verdict.py`: three guard tests; one existing test used `mde_h=0.02` to differ from the base and now uses 0.015.
- New: `scripts/sx_idea_rule_simulation.py`, its test file and `sx_idea_rule_sim_v1.json`.

## 6. Owner decisions still open
1. Sign SX5 MDE_H = 0.18 pp = 0.0018, or another number (never after a result).
2. Whether E\* = 0.37 pp is only a reported sentence (recommended) or is signed into an outcome rule.
3. Accept the ideas rule unchanged (recommended) knowing fold votes are individually weak, or sign a different value now.
4. Whether to have the h05 depository-fee text and approximate round-trip table corrected (separate change).
5. Whether diagnostic X1 is signed as described (no weight) or dropped.
