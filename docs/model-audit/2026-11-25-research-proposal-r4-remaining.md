# Proposal: how to use the remaining R4 research budget (3 of 6 candidate slots)

Date: 2026-11-25 (IST). Feature 1 (#218). Proposal only.
Nothing in this document has been run. Nothing was trained, scored or written to any database, and no production system was touched.
It proposes no change to live trading rules: the brain stays at +8% / −4% within 15 trading days with half out at +5%, and the v1 second horizon stays at +2% in 5 days.

Inputs read: `2026-11-25-219-results.md` (+ `.json`, pre-registration, fingerprints), `2026-11-24-research-candidates-10d-15d.md`,
`2026-11-24-as-built-models-2-16-17.md`, the signed spec `docs/superpowers/specs/2026-11-14-5d-paper-trial-protocol-v1.md` and its `.SIGNOFF.md`,
and the issue texts of #219 to #222.

## Plain-English summary

**Where we are.** Three 5-day models have now been tested properly (#219). None of them made money after costs. None picked stocks better than simply buying every stock on the list.
An earlier 5-day study (fd_h5) and a 10-day study (td_h10) failed in the same way. Three of the six test slots the owner approved are used. Three are left.

**Why it keeps failing.** There are two separate problems:

1. **The test trade loses money for almost every stock.** The reference trade aims for +2% and stops out at −4%, within 5 sessions.
   After about 0.44% in costs, a win is worth about +1.56% and a loss costs about −4.44%. You would need to be right about 3 times in 4 (around 74%) just to break even.
   The average large-cap stock lost about 0.45% per trade under this rule. So the "makes money" test (ECONOMIC) is close to impossible for any stock-picker under this rule.
2. **The models are not good at ranking.** The "better than the average stock" test (SELECTION) came out at about zero.
   This test does not depend on the trade rule being profitable, so it is the one where a real improvement could still show.

**What we recommend.**

* **First choice (2 slots):** retrain the same two model types to answer a different question: "will this stock do better than most others over the next 5 days?" instead of "will it rise 2%?".
  The test is about picking the best stocks of the day, so the model should be taught that.
  **This needs a new, owner-signed protocol version (v2)**, because the signed v1 fixes what the model is taught.
* **Second choice (1 slot, inside the signed rules):** check the mid-cap model that is already live (model 16) the same way model 2 was checked (#221).
  It is unlikely to show an edge. The value is knowing whether a model we already show to people works.
* **Third choice (no slot, inside the signed rules):** a cheap check of whether the shared model does better on some scan patterns than others (#220), before anyone builds one model per pattern.
* **Park option:** stop here, keep the three slots, and wait for new data or new input types. That costs nothing, but Feature 1 then has no 5-day model that passes.

**Honest odds.** The first choice has the best chance, but it is still low: roughly 1 in 6 to 1 in 8 of a SELECTION pass.
Even if it passes, the trade rule above will very probably still lose money (ECONOMIC FAIL). So no result here leads to a paper trial by itself. A PASS is evidence for the owner, never an automatic next step (signed rule H-11b).

## 1. What the evidence says (facts the hypotheses rest on)

| Fact | Source |
|---|---|
| C1 (model 2 as served), C2 (LightGBM), C3 (logistic) all INCONCLUSIVE on SELECTION and FAIL on ECONOMIC in the primary window W_M2. The pooled edge versus every stock was +0.00, −0.14 and −0.22 percent per trade, and every range includes zero | `2026-11-25-219-results.md` lines 29-35 |
| Label AUC in W_M2: 0.529 / 0.558 / 0.528 (0.50 = coin flip) | same, lines 31-33 |
| The average scored stock lost about −0.46% per trade under +2% / −4% / 5 sessions after costs | same, lines 19 and 35 |
| Momentum five also FAIL on ECONOMIC, INCONCLUSIVE on SELECTION. No candidate was separable from it | same, lines 34 and 37-38 |
| Model 2's in-sample AUC (0.77-0.85) drops to 0.50-0.54 after its training cut: its stored figures overstate it | same, line 51 |
| Training positive rate 0.27-0.29: the absolute "+2% at session 5" label mostly records how the whole market moved | same, line 64 |
| fd_h5 (5D, 21 folds): predictive 10 of 21, economic 3 of 17, −0.37% a trade. td_h10 (10D): −0.34% a trade, both FAIL | `2026-11-24-research-candidates-10d-15d.md` line 39 |
| Models 16 (mid) and 17 (small): test AUC 0.544 / 0.525 on a single split. Trained on 24 and 30 stocks, cuts 2025-10-28 and 2025-11-05 | `2026-11-24-as-built-models-2-16-17.md` comparison table |
| Group slippage in the h05 protocol: large 10, mid 20, small 25 bps per side | `backend/src/swing_trade_ml/brain/lanes/h05_protocol.py:103` |

Indicative break-even hit rates under +2% / −4% (they treat every trade as a full win or a full loss, so they ignore trades that expire at the session-5 close): large about 74% (round trip ~44 bps), mid about 77% (~64 bps), small about 79% (~74 bps).
**For mid and small caps, ECONOMIC is harder still.**

### What the signed envelope allows (and does not)

Signed R4 envelope (`.SIGNOFF.md` line 17): local machine and local dev database only. 5D only, in the order #219 → #220 → #221/#222. Today's 53 inputs plus the corrected `obv_slope` as its own version. LightGBM and logistic regression, with momentum as the comparison.
At most 6 candidates, each fingerprinted before training. Judged out-of-sample, after costs, against every eligible stock, momentum and model 2 as served. Nothing activated, promoted or deployed.

Also signed and binding on every candidate: H-2 (the reference trade +2% / −4% / 5 sessions), **H-2b (the model target: session-5 close ≥ signal close × 1.02)**, H-7 (SELECTION and ECONOMIC never merged), H-11 / H-11b (60-session runs, three-run rule, a PASS is never automatic promotion).
Any change to these is a new file `-v2.md` (`.SIGNOFF.md` line 11).

Not covered by v1 at all (each needs v2 or its own protocol): a different training target, a different reference exit, the +8% / −4% / 15-day brain rule (that is 15D, behind the selection-lab gate), new input types (fundamentals, news), production data.

## 2. Ranked hypotheses

### H1 (rank 1): teach the model to rank, not to call a +2% move. **Needs a v2 protocol for the training target**

**Question.** Does a model trained on a cross-sectional target ("is this stock in the top 30% of the day's pool over the next 5 sessions?") beat every scored stock on SELECTION, where the same inputs trained on the absolute +2% target did not?

**Why (evidence).**
* SELECTION measures picks minus the average of that day's pool. On a day when everything rises, every stock is a "+2% winner" under H-2b, so the model mostly learns market direction: positive rate 0.27-0.29, AUC about 0.53.
  A relative target removes the market move from the label and leaves only what SELECTION rewards.
* The repo already designed this exact idea for 15D. Lab candidate S1 uses a "beats the group" label, top 30% per day (`2026-11-24-research-candidates-10d-15d.md` line 54; design rev 3.1). It is not built and not run, so there is no result to lean on, only a design precedent.
* It changes one thing only. Inputs, algorithms, hyperparameters, universe, windows, purge/embargo, costs and verdicts all stay as in #219, so a paired comparison with C2/C3 isolates the target.

**Candidates to fingerprint (2 slots: C4, C5).**

| Id | Config (everything not listed is identical to #219's C2 / C3 and its pre-registration) |
|---|---|
| C4 | LightGBM, model 2's hyperparameters (400 trees, lr 0.05, depth 6, 31 leaves, min_child 50, subsample/colsample 0.8, balanced, seed 42), determinism pinned (`deterministic`, row-wise, 4 threads), StandardScaler. Feature set `r4-fs53-obvvol-v1`. **Target `rel5-top30-v1`** |
| C5 | Logistic regression (C 1.0, L2, lbfgs, 2000 iterations, balanced, seed 42), StandardScaler, same feature set, **target `rel5-top30-v1`** |

Target `rel5-top30-v1` (to be written into the v2 file and fingerprinted):
* r = session-5 close / session-1 open − 1. This uses the entry anchor of H-2, so the label measures a return a trade could actually capture. It does not reward the overnight gap after the signal.
* The day's pool is the same common scored pool as #219: the 52 stocks, a candle on the signal session, at least 220 bars, all 53 inputs finite.
* label = 1 if r is in the top 30% of that day's pool (ties broken A-Z). Days with fewer than 10 stocks in the pool give no labels. A missing session-1 open or session-5 close gives no label.
* Refit as in #219: expanding window on rows whose signal index ≤ run start − 11 sessions (label end, 5-session purge plus 5-session embargo).

Windows: W_M2 is primary (3 runs of 60 from 2025-10-28, the signed three-run rule exactly as written). W_FULL is secondary, reported only, and uses the 11-run extension labelled as an extension, as in #219 post-review note 3.

**Inside the signed envelope:** local only, 5D, large cap, 53 inputs plus corrected `obv_slope`, LightGBM and logistic, at most 6 candidates fingerprinted before training, judged by H-2 / H-7 / H-11 / H-11b against every stock, momentum and model 2.
**Outside v1, so it needs a NEW owner-signed `2026-11-xx-5d-paper-trial-protocol-v2.md`:** the training target (H-2b is "session-5 close ≥ signal close × 1.02"). Proposed v2 scope: one change only. H-2b becomes per-candidate, with `rel5-top30-v1` added as a research target.
The reference trade H-2 and every verdict rule stay as signed. This must never be assumed: without the v2 signature, H1 does not run.

**Pre-registered pass / fail (written before training).**
* H1 succeeds only if **C4 or C5 is SELECTION PASS in W_M2** under the signed rule: at least 2 of 3 runs PASS, none FAIL, pooled 90% block range wholly above 0. In addition, its W_FULL pooled SELECTION range must not lie wholly below 0.
* H1 fails if neither candidate reaches SELECTION PASS in W_M2. INCONCLUSIVE counts as fail for the purpose of continuing.
* ECONOMIC is reported for each candidate and is expected to FAIL. It does not decide H1, but it is never hidden or merged (H-7).
* Comparison only, never deciding: paired daily differences C4 − C2, C5 − C3, C4/C5 − momentum, C4/C5 − C1 in W_M2, plus label AUC and the score-decile spread.
* A PASS is evidence for the owner, not a qualification (H-11b). Before any R5 step, it must be confirmed on a later window that nobody has seen: data after 2026-09-07, from a local refresh obtained through an approved route.

**Leakage risks and guards.**
* The label uses the pool of the signal day only, built from stocks eligible on that day. No future index membership is used, but the survivor list stays (stated).
* The label ends at session 5. The purge and embargo of #219 (11 sessions) carry over unchanged, and a test asserts every card's `train_end` precedes its run.
* The cross-sectional rank must be computed inside each training fold from the rows that fold may see. Ranking across the whole dataset first would be harmless for this label, but the rule is "compute in fold" so the code never needs that argument.
* **Window reuse.** W_M2's outcomes for these 52 stocks were already seen in #219. A new target tested on the same window is a "second look", so a PASS is weaker evidence than a first look. That is why the unseen-window confirmation above is mandatory.
* Code fingerprint: use `code_fingerprint_v2`, which also hashes the reused modules (#219 post-review note 2).

**Cost.** Local CPU only. 2 candidates × 14 fits (3 W_M2 + 11 W_FULL) is the same order as #219 (28 artifacts), plus the required reproducibility rerun.
Engineering is about 1 to 2 days: target function plus tests, v2 text, pre-registration, review. No new data, no paid service.

**Expected chance of success: low, roughly 10 to 20% for a SELECTION PASS.** The same 53 technical inputs reached AUC ~0.53 on two targets already, and a relabel cannot add information the inputs do not hold. It can only stop the model wasting it on market direction.
The chance that it also passes ECONOMIC under +2% / −4% is well under 5%, because the pool itself loses about 0.45% a trade.

**Stop rule.** If H1 fails, **stop 5-day model research inside R4.** Do not try other relative thresholds (top 20%, median), other hyperparameters or other lists on the same window: that is tuning after seeing outcomes.
The remaining slot goes to H2 (verification) or is parked.

### H2 (rank 2): verify the live mid-cap model 16 as served (#221). **Inside the signed envelope, with one cost clarification**

**Question.** Does model 16 (`swing_classifier_midcap` v2, live in production) rank mid-cap stocks better than every scored mid-cap stock and momentum five out-of-sample, after costs?

**Why (evidence).**
* Issue #221 asks for exactly this. A live model that has never had an out-of-sample, after-cost check is a product risk, whatever the result.
* Mid caps usually spread out more from one another than large caps, which leaves more room for a ranking to matter. That is the only argument for an edge, and it is weak.
* Against it: test AUC 0.544 on one unpurged split. Model 16 was trained on only 24 stocks, and its obv_slope has been served with a different formula since 2026-10-06 (as with model 2). The higher costs push the break-even hit rate to about 77%.

**Candidate (1 slot: C6).** Model 16 as served: sha256 `633259b084da…` (the full hash is in the as-built record), its own 46 inputs from today's builder, no training. This follows the C1 precedent, which counted one slot.
Universe: the v1 mid `ml_swing` strategy list as h05 builds it (`brain/lanes/h05_models.py:169-202`; 150 stocks locally, 24 of them in model 16's training set), frozen and hashed in the pre-registration.
Report separately, without a verdict, the subset of 24 training symbols versus the 126 others.

**Inside the envelope:** local only, 5D, #221 is named in the signed order, a model-as-served reference, momentum comparison, the H-2 trade, the H-7 / H-11 verdicts.
**Clarification needed (not a v2):** the signed cost table (spec 4.3) is titled "large cap". Using the h05 mid group values (20 bps slippage per side, same taxes and charges) should be confirmed by the owner in writing before the pre-registration.
The spec's universe section names the 52-stock large-cap list. The R4 envelope extends research to #221/#222, so a mid list is in scope for research, but every result is "selection-biased exploratory evidence" (no point-in-time membership).

**Window.** From model 16's cut (2025-10-28) plus 11 sessions to the snapshot end (2026-09-07). That is roughly 200 sessions, enough for 3 runs of 60 if the session count confirms it. If fewer than 3 full runs fit, the result is reported as INCONCLUSIVE by construction and is not stretched.

**Pre-registered pass / fail.** As H1: SELECTION PASS in its window under the three-run rule is a "pass", ECONOMIC is reported, and C6 versus momentum is a paired comparison only.
A FAIL or INCONCLUSIVE is the expected, acceptable answer. It is input for the R3 decision on how model 16's score is shown, which is not decided here.

**Leakage risks.** Training symbols overlap the scored list (24 of 150), so it is out-of-sample in time only for those names. That is why the subset is reported separately.
The mid list is today's list (survivors). Unadjusted candles with an empty local `corporate_actions` table make mid caps more exposed to split or bonus gaps: keep the >20% overnight-gap flag from #219 and report the count.

**Cost.** Smallest of the three: no training, one scoring pass and the reproducibility rerun. About 1 day of engineering, mostly the universe and cost pre-registration.

**Expected chance of success: very low, about 5 to 10% for SELECTION, under 3% for ECONOMIC.** The value is the verification, not the odds.

**Stop rule.** Whatever the result, do not train a new mid-cap candidate on the +2% target inside R4. Small caps (#222, model 17) get no slot under this plan. Model 17's cut (2025-11-05) leaves an even tighter window, and it has the same weaknesses at higher cost.

### H3 (rank 3): do scan patterns change the shared model's results? (#220). **Inside the envelope, uses no slot**

**Question.** Within #219's existing out-of-sample picks, do the shared scorer's results differ by scan pattern enough to justify building pattern-specific models?

**Why.** #220 asks for "one shared scorer with pattern tags or filters against pattern-specific models where sample sizes support evaluation". The approval table sets "shared model before per-pattern" (`2026-11-24-279-approval-table.md` row 5) and defers pattern models until the large-cap verdict (H-14). That verdict is now in, and the shared scorer has no edge.
Building per-pattern models on the same target before seeing whether any pattern subgroup differs would spend slots blind.

**Config.** No new candidate. A pre-registered descriptive table over the already saved W_M2 and W_FULL pick and pool outcomes of C2 and C3: picks minus pool, by pattern tag, with block ranges and counts.
Patterns are recomputed point-in-time by a pinned pattern-code version. Any subgroup with fewer than 60 matured days is reported "too few, no reading".
It produces no verdict and no PASS. Only if one pattern shows a pooled range wholly above 0 with enough days would a later pattern-specific candidate be proposed, using a slot and its own pre-registration.

**Inside the envelope:** yes (#220 is named, no candidate, no training). It is post-hoc on outcomes already seen, so it is labelled exploratory and can never decide anything.
**Leakage risk:** pattern tags must come from completed bars on the signal session. Whether the scan tags stored by v1 reach back to 2024 locally has not been checked. The tags are therefore recomputed, never read from tables that may have been written later.
**Cost:** half a day or less. **Chance that it finds a usable pattern: under 5%.** Several patterns are tested at once, so one may look good by luck. The rule "a later pre-registered candidate, never this table" handles that.
**Stop rule:** if no subgroup shows a range wholly above 0, close #220 with "shared scorer, no pattern split justified".

### Option P: do nothing, park the remaining 3 slots

| For | Against |
|---|---|
| Costs nothing. It avoids spending slots on a structure (the +2% / −4% / 5-session reference trade) that two careful runs show the average stock loses on | Feature 1 (#218) keeps no 5D model that passes, and #220-#222 stay open without answers |
| Keeps the budget for a better moment: fresh data after 2026-09-07, point-in-time membership, or new input types (breadth, fundamentals, news), each of which needs its own approval anyway | The live mid and small models (16, 17) stay unverified (H2 is the cheapest way to close that) |
| Avoids reusing W_M2 a second time (window reuse) | Waiting does not improve the 53 technical inputs. If the owner wants better accuracy, the route is new inputs, which R4 does not cover |

Park is the right call if the owner does not want to sign a v2 now and does not need the mid-model verification soon.

## 3. Recommended allocation and order

| Plan | Slots | Order | Needs |
|---|---|---|---|
| **A (recommended)** | H1: C4 + C5 (2), H2: C6 (1), H3: 0 | H3 first (cheap, half a day), then H1, then H2 | v2 signature for the H1 target. Cost clarification for H2 |
| B (no v2) | H2: C6 (1), H3: 0, 2 slots parked | H3, H2 | Cost clarification for H2 |
| C | H1: C4 only (1), H2: C6 (1), 1 parked | H3, H1, H2 | v2 signature. Logistic is dropped because C2 and C3 behaved alike |
| P | 0 used | none | none |

Global stop rule: if H1 fails, R4 model work ends after H2 (or at once under plan P). A sixth candidate is never "spent to finish the budget".

## 4. What this proposal does not do

* It does not change H-2, the brain's +8% / −4% / 15-day rule, the v1 +2% / 5-day rule, any risk limit or any live setting.
* It does not touch model 2, 16 or 17 in production, the h05 trial, or any frozen file (`ml/features.py`, `ml/predict.py`, the protocol-frozen trainers).
* It writes no database row and creates no issue. Any run needs: the owner's choice of plan, the v2 signature for H1, and a pre-registration pushed before training.
