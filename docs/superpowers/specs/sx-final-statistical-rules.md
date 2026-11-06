# SX5 / SX10 final statistical rules (for owner review, 2026-11-04)

Status: **PROPOSED. Not signed. Not committed.** Written for the owner, who will not sign until these final definitions are reviewed. Code: `backend/src/swing_trade_ml/ml/sx_verdict.py`; tests: `backend/tests/test_sx_verdict.py` (48 tests, synthetic records only; three cover the MDE_H unit guard). No real arm, holdout, model, database, prod or Kite was touched.

> **UNITS (fixed wording; full table in `sx5-units-gross-net-and-idea-rule.md`).** The quantity is the daily paired difference D_t = (C_56 daily top-5 excess return) minus (A_53 daily top-5 excess return). A daily top-5 excess is the mean forward 5-session return of that day's 5 picks minus the mean forward 5-session return of all eligible stocks that day, written as a FRACTION of the money in a trade: 0.0017 = 0.17 percentage points (pp) = 17 basis points (bps) of one 5-session holding return. Because the daily value is already an average over that day's ideas, "per day" and "per trade" are the same number. Nothing is annualised. MDE_H = 0.0018 means 0.18 pp (18 bps) of one holding return, per trade; typing 0.18 would mean 18 percentage points per trade (100 times too large), and the verdict code refuses any MDE_H >= 0.02 ("looks like percentage points: pass a fraction") and any unit tag other than `fraction_of_return`; `mde_h_from_pp(0.18)` gives 0.0018. SX10 would use the 10-session return. The primary quantity is GROSS (no costs; entry at the decision-day close); costs and the net reading are in the same note, section 2.

## Plain-English summary

- **Three words, three different meanings.** PASS means "the checks agreed", and only proposes a separate forward shadow test; it is not evidence of profitability. FAIL means "a gain of the size we planned for (MDE_H) is unlikely"; it does **not** mean every smaller gain is absent. INCONCLUSIVE means "the experiment could not tell".
- **R4 (the holdout check) is only a same-direction check.** The holdout average difference must be above zero, like the development one, and there must be enough holdout days (at least 100 of the 133 expected). It is not a second significance test.
- **Two horizons, read one after the other.** The first horizon read is judged at the strict 2.5% level and that is never changed. The second is judged at 5% only if the first one rejected "no edge", otherwise also at 2.5%. This keeps the chance of any false win across both at or below 5%. It is a "fallback" schedule, not Holm: Holm needs both results at once.
- **PENDING_HOLDOUT is not a result.** It only says the two development checks are met and the holdout has not been recorded as completed. It may never be reported as a PASS or acted on.
- **"Ideas" per fold** are counted with the no-repeat rule of td-protocol-v1: a stock picked while its earlier idea is still open is not a new idea. This makes the "20 ideas per fold" condition real. It may make some folds ineligible (see decisions D3).
- Every report carries the mandatory sentence for its word.

## Rule 1. R4 final definition (PROPOSED: sign consistency)

**Options considered**
1. *Current code*: holdout mean D_t > 0 and development mean D_t > 0.
2. *Same sign*: identical to option 1 for a positive development edge (a positive development edge is already required by R2).
3. *Holdout one-sided lower bound > some value*: rejected. It is a second inference test, needs a second alpha and a second power calculation, and with 133 days it would be dominated by noise; the protocol asked R4 to be "same sign, reported, not a second chance".

**Recommendation: options 1/2, plus a minimum number of holdout days.** R4 is met only if all of these hold:
- at least one holdout fold, and every holdout fold has status ok;
- at least `min_holdout_days` retained holdout days (retained = both arms present and at least 10 stocks that day), **100** (PROPOSED; 133 expected = about 75%);
- holdout mean D_t strictly above 0;
- development mean D_t strictly above 0.

No bound, p-value or size threshold is used. The holdout interval is printed for information with no weight.

**Edge cases.** Fewer than 100 retained days: R4 not met, reason "not evaluable". Zero ok days (fold skipped, or every day under 10 stocks): R4 not met, reason "zero ok holdout days". Sign flip (holdout mean 0 or negative): not met, reason "signals disagree". More days than 133: allowed, reported next to the expected number (`expected_holdout_days`, informational).

**Interaction with PENDING_HOLDOUT.** R4 is read only when R1 and R2 are met on development and the registry shows COMPLETED. Otherwise the holdout is never opened (a test uses a loader that raises). When R4 is not met the outcome is **INCONCLUSIVE** (never FAIL), with the reason in `outcome_detail`.

Code: `_r4`, parameters `min_holdout_days` (100), `expected_holdout_days` (133). Example: dev mean +0.20 points/day, holdout 120 days mean +0.01 points/day: R4 met, outcome PASS. Same with holdout 99 days: R4 not met, INCONCLUSIVE ("holdout has 99 days, fewer than the required 100 (not evaluable)").

## Rule 2. Single-horizon Holm and the sequential schedule (PROPOSED)

**Problem.** Holm needs both p-values at the same time. SX5 and SX10 may be read at different times.

**Rule.**
- `holm_mode="single_horizon"`: the **first horizon read** uses the one-sided **2.5%** bound for R2. This is never revised, whatever happens to the other horizon, even if the other is never read.
- `holm_mode="second_read"`: the second horizon read gets the **5%** bound if the first read's **R2 was met** (its inference test rejected "no edge"), and the 2.5% bound if not. The code requires the first read's verdict (`first_read=`) and checks that it is of the other horizon, was a single_horizon verdict, used 2.5%, and carries its record hash. The first read's hash is stored in the second record.
- `holm_mode="two_horizon"` (the true Holm: smaller p gets 2.5%, the other 5%) is kept but is valid **only if both p-values are computed before either verdict is acted on**. Do not use it when the horizons are read at different times.
- Which horizon is "first" is fixed by the order in which the registry authorises the reads, recorded before any result is seen.

**Why the family-wise error is at most 5% (the "fallback" procedure).** Let A be the first read (level 2.5%) and B the second (level 5% if A rejected, else 2.5%). P(A falsely rejects) <= 2.5% when A is a true null.
- A and B both true nulls: P(any false rejection) <= P(A rejects) + P(B rejects while A did not) <= 2.5% + 2.5% = 5%.
- A true, B false: only A can be a false rejection: <= 2.5%.
- A false, B true: B is judged at 5% at most: <= 5%.
So the family-wise error is <= 5% in every case. The code test simulates 200,000 uniform p-value pairs in each of the three configurations, with a false null rejected with certainty (worst case), and checks <= 5%. This holds if each bound is a valid nominal one-sided level; the block bootstrap is only approximately so. That approximation is the same one the single-horizon rule has.

**Properties.** It is slightly less powerful than Holm (if B is much stronger than A, Holm would give A the 5% level; this schedule does not), and the 2.5% first-read level is conservative. Gating on A's R2 and not on A's final PASS is valid (R1/R4 only make rejection harder) and keeps the gate to the inference test.

Code: `compute_verdict(..., first_read=...)`, `second_read_alpha`, `_check_first_read`. Example: SX5 read first, R2 met at 2.5% -> SX10 is read with the 5% bound. SX5 R2 not met -> SX10 read with the 2.5% bound.

## Rule 3. PENDING_HOLDOUT wording (PROPOSED)

Produced exactly by `PENDING_HOLDOUT_TEXT` in `render_plain_english`:

> INTERIM STATE, NOT A PROTOCOL OUTCOME: PENDING_HOLDOUT. On the development folds both development checks are met (R1: the new inputs beat the old in at least 60% of the eligible folds; R2: the lower bound of the average daily edge is above zero). The holdout run has not been recorded as COMPLETED, so the holdout check (R4) has not been read. This is not a PASS, not a FAIL and not an INCONCLUSIVE, and it must not be reported, acted on or described as a result. Next step: the owner decides whether to authorise the single holdout run through the registry; only after the registry shows COMPLETED is the verdict called again, with the holdout.

May say: the two development checks are met; the holdout has not been read; the next step is the owner's decision on the holdout run. May not say: "passed", "works", "promising edge", "ready", any effect size as a finding, or any statement that a shadow test is approved. The word never appears after "Outcome:". Code: the PENDING branch of `render_plain_english`; state arises in `compute_verdict` when R1 and R2 are met and `holdout_completed` is false.

## Rule 4. Ideas per fold (PROPOSED: no-repeat count)

**What the harness records.** Per fold, per arm, per day: `date`, `n_stocks`, `top_symbols` (the 5 picks of that day), `excess_vs_all`. There is **no no-repeat rule in the harness** (the same stock can be in the top 5 on consecutive days), and it does not record a trading-day calendar index or the "next-best" stock. The old count was 5 per day, so the "20 ideas" test was met after 4 days and never bound.

**Rule (`idea_rule="no_repeat"`).** Order the fold's recorded days by date; the position is the trading-day clock (days under 10 stocks advance the clock and add no ideas). A (stock, day i) pair is a new idea unless the same stock was counted as an idea on day j with i - j <= h (h = 5 for SX5, 10 for SX10): entry at the next open, exit at the close of the h-th trading day, eligible again from the day after, as in td-protocol-v1 rule 2. Duplicates within a day count once. Primary arm's picks are counted. Eligible fold: at least 10 retained days **and** at least 20 ideas. R3: at least 100 ideas over eligible folds.

**Limits, stated plainly.** The "next-best fills the slot" part of td-protocol-v1 cannot be replayed from the records, so ideas are never over-counted, at most under-counted. The clock resets at each fold start. **Record field needed** (not added; out of scope): a harness `day_index` or trading-calendar position, and picks beyond the top 5, would make the count exact.

**Alternatives implemented:** `idea_rule="raw_per_day"` (the old count, never binds) and `idea_rule="days_only"` (the idea conditions at fold and R3 level are dropped, the 10-day minimum stays; ideas are still reported). Recommendation: `no_repeat`. Example: a fold of 12 days with the same 5 stocks every day: raw 60, no_repeat (h=5) 10 (days 0 and 6), so the fold is ineligible; with 5 new stocks each day it is 60.

**Statistical justification (added 2026-11-04, independent of results; full derivation and tables in `sx5-units-gross-net-and-idea-rule.md` section 3).** Distinct stock episodes are the approximately independent observations (per-stock 5-day return autocorrelation 0.78 / 0.58 / 0.37 at lags 1 to 3, MEASURED); 20 ideas is the R1-share floor, i.e. the smallest fold whose mean is positive more often than 60% when the true edge equals MDE_H (16 at the central assumption, 8 to 23 over the range). It is not a reliability threshold (that would need 129 to 365 ideas, impossible in a 19-day fold), so single-fold votes are individually weak and the inference rests on R2: a design limitation, not a reason to change the rule. On a neutral proxy with random top-5 lists (persistence 0 / 0.5 / 0.9, the real calendar, no arm result) a 19-day fold passes the 20-idea test with probability 1.00 under `no_repeat`, `raw_per_day` and `days_only` alike, and P(fewer than 12 eligible folds) = 0.00; a stricter 36-ideas threshold would make INCONCLUSIVE certain at persistence 0.9 and is not recommended. **Justified variant: `no_repeat`, 20 ideas (the code default). No default was changed.**

## Rule 5. Outcome words (PROPOSED wording)

| Word | When (in the fixed order) | Means | Does NOT mean | Mandatory sentence on the report |
|---|---|---|---|---|
| PASS | R3 met, R1 met, R2 met, R4 met | the checks agreed | that the model works or is profitable | "a PASS only proposes a separately signed forward shadow test; it is not evidence of profitability" |
| FAIL | R3 met, R2 not met, and the 5% upper bound of the mean daily edge is below MDE_H | a gain of MDE_H or more is unlikely | that every smaller positive effect is absent | "FAIL means a gain of MDE_H or more is unlikely; it is not evidence that every smaller positive effect is absent." |
| INCONCLUSIVE | too little data (R3), or R2 not met with the upper bound at or above MDE_H, or R2 met but R1 not met, or R4 not met (signals disagree / holdout not evaluable) | the experiment could not tell | "no effect" or "an effect" | "the experiment could not tell; no conclusion either way" |
| PENDING_HOLDOUT | R1 and R2 met on development, holdout not COMPLETED | interim, see Rule 3 | any result | the full Rule 3 text |

A FAIL is a statement about size: the same data are INCONCLUSIVE when a smaller MDE_H is the target (tested). `render_plain_english` emits the sentence for each word, plus the MDE_H value on FAIL. No word is ever followed by the claim that a model "works".

## Rule 5b. MDE_H unit guard (PROPOSED, code added 2026-11-04)

`VerdictParams` takes `mde_h` as a FRACTION of one holding return per trade (0.0018 = 0.18 pp) and a tag `units="fraction_of_return"`. It refuses a different tag and any `mde_h >= 0.02` ("looks like percentage points: pass a fraction"). `mde_h_from_pp(0.18)` returns 0.0018 and refuses non-numbers, zero, negatives and 2 pp or more. The verdict-code hash and the parameter-set hash change with this (see the sx5 draft for the new illustrative values).

## Rule 6. Tests, hashes and the signing note

Tests: 45 in `test_sx_verdict.py` (was 30 before this change; 15 added or changed): R4 short days, zero ok days, sign flips, no size threshold, holdout status; sequential Holm levels and refusals; FWER simulation; PENDING text; mandatory sentences; outcome table; ideas-per-fold known answers and both alternative variants; hashes. `test_trial_freeze.py` also passes (48 passed together). The test helper now gives each day new symbols (previously the same 5 every day, which the no-repeat rule would correctly count as few ideas).

Hashes: the parameter hash (`VerdictParams.sha256()`) changed because three parameters were added (`idea_rule`, `min_holdout_days`, `expected_holdout_days`) and the code version string is part of it; the code hash (`verdict_code_sha256()`) changed because the module changed. **The signed text must name the parameter hash and the final code hash after all edits.** Code hash of this edit (will change with any further edit, including formatting): see the report; recompute with `verdict_code_sha256()` at signing.

## Decisions marked PROPOSED, for the owner

D1. R4 = same sign (holdout mean > 0 and development mean > 0) with at least 100 holdout days; no bound. D2. Sequential fallback: first read 2.5% never revised; second read 5% only if the first read's R2 was met. D3. Ideas: `no_repeat`; **warning**: with persistent picks the 20-ideas-per-fold and 100-ideas conditions may leave fewer than 12 eligible folds and make the verdict INCONCLUSIVE on data. This cannot be checked here (no real data). If the owner wants to avoid that, choose `days_only` before signing, not after seeing results. D4. `min_holdout_days` = 100. D5. The wording of Rules 3 and 5.
