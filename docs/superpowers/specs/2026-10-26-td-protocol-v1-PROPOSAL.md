# Ten-day strategy protocol (td-protocol-v1) — PROPOSAL rev 2, not signed

Status: **PROPOSAL for owner review, 2026-10-26. Not approved for signing and not approved to run.** No 10D
model is built and no 10D result exists for this protocol. It becomes frozen only when the owner signs
section 11 and the signed commit is tagged `td-protocol-v1`. 15D is not touched by anything here.

## 1. Why a 10-day horizon

Three horizons: 5, 10 and 15 trading days. 15D (+8% / −4%) is the locked C1 trial. 5D is the v1 bot, covered
by fd-protocol-v1. 10D has no rule and no evidence. This protocol fixes the rule, the counting and the
pass/fail test in advance, so results cannot shape them. The aim is to find out whether 10D shows repeatable
skill, positive after-cost results and acceptable risk — not to make 10D operational.

## 2. The setting: a research hypothesis, three candidates, none optimised

The setting is **an unvalidated hypothesis**. It was not tuned on trading results and will not be.

| Candidate | Target / stop | Reward : risk | Break-even hit rate (before costs) | Stop ÷ median daily range (2.08%) |
|---|---|---|---|---|
| T1-b (owner's first idea) | +6% / −3% | 2.00 : 1 | 33.3% | 1.44× — below the 1.5× rule |
| **T1-c (owner's alternative, now recommended for decision)** | **+6% / −3.5%** | **1.71 : 1** | **36.8%** | **1.68× — passes** |
| T1-a (my earlier suggestion) | +7% / −3.5% | 2.00 : 1 | 33.3% | 1.68× — passes; target further away |

**Owner decision 2026-10-26:** +7% / −3.5% is **not** adopted. +6% / −3.5% is to be evaluated as the alternative.

### First-principles rationale

1. **Time scaling.** Price moves widen about with the square root of time. 15D's +8% / −4% scaled to 10 days
   (√(10/15) ≈ 0.82) gives about +6.5% and −3.3%. The target rounds to **+6%** (kept just under 6.5%, so it is not
   made harder to reach, which was the concern with +7%). The stop rounds to **−3.5%** (up from 3.3%, because the
   noise check below shows 3% is too tight).
2. **Noise rule, fixed before the check:** the stop must be at least 1.5× the median daily range, otherwise
   ordinary daily movement stops the trade out.
3. **Cost of the lower ratio, stated plainly.** +6% / −3.5% has a reward-to-risk of 1.71 : 1, not the 2 : 1 of the
   15D rule. It needs 36.8% of trades to hit the target to break even before costs (vs 33.3%), and a few points
   more after costs. This is a trade-off I accept for a stop that is outside everyday noise; the report states
   the after-cost break-even hit rate. 6/3.5 is not chosen because it looks best; it follows from points 1–2.

### Volatility check (26 Oct, read-only, 49 model stocks, candles 2021-08-05 to 2023-06-30 only, 23,030 stock-days)

| Measure | Value |
|---|---|
| Median daily range (high − low, % of close) | 2.08% (25th–75th percentile 1.56%–2.84%) |
| Median best move up within the next 10 bars | +3.39% |
| Median worst move down within the next 10 bars | −3.02% |
| Share of stock-days reaching +6% within 10 bars | 25.0% |
| Share touching −3% within 10 bars | 50.3% (−2%: 64.7%) |

These describe the market before the confirmation window. They were used only to apply the written noise rule,
not to search for the best setting; no 10D rule was scored on them and no trading result was looked at. No grid
outcome informed the choice: the earlier horizon grids tested 10D at 2/2, 3/3, 5/3, 5/4 and 8/4; none of the three
candidates above was among them.

## 3. Contamination — disclosed up front

- **Confirmation window 2023-07-01 to 2025-01-31.** Used for the 15D wf-protocol-v1 (spent), cost stress,
  bad-market windows, pause checks, and (once run) 5D. No 10D rule was ever scored there, but the market in that
  period has been studied. The exposure ledger lists every use.
- **2025-02 onward.** Horizon grids evaluated 10D variants in 2025-02..06, 2025-08..12 and 2026-05..08, so 10D
  outcomes there have been seen.
- **Consequence.** A 10D history result is **a gate to start a shadow lane, never proof.** Proof comes only from
  the prospective (forward) data in section 6.

## 4. Candidate budget and separation

10D is its own protocol and its own **one** candidate setting (the one the owner signs). It is not a Phase B
candidate, does not count toward Phase B's three, and the Phase B reject set (129 stocks) is not used to confirm
it. One history run, once. A failed run is preserved and a different setting is `td-protocol-v2`, a new
protocol with the failure on record, never a re-run.

## 5. Historical gate (one run; decides only whether a shadow lane may start)

Tool modelled on `five_day.py` (new file, 5D and 15D files untouched). Sample 2023-07-01 to 2025-01-31, folds of
28 calendar days (21), the model retrained once per fold with outcomes known by its cutoff, a **barrier label**:
did the stock reach the target before the stop within 10 trading days. The model's question and the trade are the
same, unlike 5D. Costs per `docs/brain/COSTS-CHECK-2026-10.md`, 0.10% slippage per side, entry at the next
open, levels from the entry price, stop checked before target on a day touching both, sold at the close of the
10th trading day after entry if neither is hit.

**Statistical rule (same machinery as wf-protocol-v1, so horizons are judged alike):**

| Item | Value |
|---|---|
| Eligible fold | at least 10 test days and 20 finished best-5 ideas |
| Enough data | at least 12 eligible folds and at least 100 finished ideas, else INCONCLUSIVE |
| Picks | best 5 by model score per day (skill); the same 5 are scored for economics |
| Predictive skill part | average result per day beats **every stock** in ≥ 60% of eligible folds **and** the lower bound of the daily edge over every stock is above zero |
| Lower bound | 5th percentile of the average daily edge, block bootstrap, **block = 10 trading days** (the hold length; wf used 15), 2,000 draws, seed 7 |
| Economic value part | average result per day after costs above zero in ≥ 60% of eligible folds **and** average per trade after costs above zero over all folds |
| Benchmarks (reported beside, evidence-defs-v2) | every stock, 200 random-5 accounts, 5 strongest 20-day risers, NIFTY 50 held, cash |
| Report also shows | break-even hit rate after costs, worst fold, worst account fall, hit rate, per-market-type results |

**Outcome words (history):**
- **PASS** — both parts pass.
- **FAIL** — enough data, and at least one part does not pass.
- **INCONCLUSIVE** — fewer than 12 eligible folds or fewer than 100 finished ideas.

**What happens:** only PASS allows a 10D shadow lane to be proposed (and even then the owner must approve its
counting rules). FAIL or INCONCLUSIVE: no lane starts; the result is kept as diagnostic evidence. No threshold is
changed after the result is seen.

## 6. Forward validation: the real evidence

**Lane.** Shadow only (`h10`): no broker or paper orders, no position slots, not shown to customers.

**Lock date.** The day the lane's counting rules are live on prod and the switch is on. Nothing counts before it.
The stock list is frozen at the lock date (the 49 model stocks).

**Counting rules (to be frozen at signing):**
1. Each trading day after the close, the h10 model scores the stock list and the **top 5 by score** are counted
   as that day's ideas.
2. **No repeats:** a stock with a counted idea still open is skipped (the next-best fills the slot); it is
   eligible again from the day after its idea finishes.
3. **Every top-5 idea is counted whether or not the portfolio risk gate or a real order would have blocked it.**
   The original model signal is stored with the reason it would have been blocked, so model quality can be
   judged apart from account execution.
4. Entry at the next trading day's open, levels from the entry price, stop before target, exit at the close of
   the 10th trading day; ₹1,00,000 per idea for costing; 0.10% slippage per side; costs per the cost check.
5. Ideas on a day with missing or stale data are not counted, and the day is logged.
6. Results are recorded the day an idea finishes and stay **sealed** (counts and errors only) until the checkpoints.
7. WATCH/WAIT/AVOID outcomes for the same stocks may be stored as diagnostics, never in the official numbers.

**Checkpoints.** Month 3: sanity only (counts, missing days, errors); no returns. Month 6: verdict. One
pre-set extension to month 9 only if fewer than 100 finished ideas at month 6. No early stop, no optional
stopping. Hard stop at month 9.

**Forward rule.** Unit = calendar month (28-day folds are too few in six months). Eligible month: at least 10
trading days and 10 finished ideas.

| Part | Needs |
|---|---|
| Skill | average daily result beats every stock **and** random-5 in ≥ 60% of eligible months, at least 4 eligible months, and the block-bootstrap lower bound of the daily edge over every stock above zero |
| Profit | average per idea after costs above zero overall, and above zero in ≥ 60% of eligible months |
| Beats the market | after costs, above NIFTY 50 held over the same period |
| Risk | worst fall of the equal-capital idea account inside the 15% halt; no single month above 50% of total net profit |
| Reliability | at least 100 finished ideas; results shown separately for rising and falling market months |

**Outcome words (forward):**
- **PASS** — every row above passes.
- **FAIL** — enough data (≥ 100 ideas, ≥ 4 eligible months) and at least one row fails.
- **INCONCLUSIVE** — under 100 finished ideas at the hard stop, or under 4 eligible months.

A PASS means "worth a paper-trading trial", nothing more. Paper orders need a separate explicit approval; real
money needs a separate go-live decision. 10D never counts toward the M18 gate or the 15D trial.

## 7. Evidence kept

Every run: signed protocol file and tag, code commit, run manifest, dataset and DB identifiers, folds, settings,
benchmarks, costs, slippage, full results and logs, committed to `docs/brain/evidence/td_v1/`, with an
exposure-ledger row written before any result exists. Failed experiments and WATCH outcomes live in the
diagnostic store, labelled "diagnostic — not official trial evidence".

## 8. Known limits

Survivor bias (today's 49 stocks). Daily bars cannot order target and stop within one day (counted as the
stop, cautious). 10D history is contaminated (section 3), so it gates but does not prove. The shadow lane
measures ideas, not a real account. Regime dependence: six months may show one kind of market.

## 9. What this protocol does not do

It does not change 15D or 5D. It does not authorise orders, paper or real, or customer recommendations.

## 10. Items the owner must still set

The numeric choices below are my proposals, copied from the 15D machinery where one exists; the forward-month
rule (section 6) is new and has no 15D precedent.

## 11. Owner decisions (to sign — nothing signed)

- [ ] T1 Setting: **T1-c +6% / −3.5%** (1.71 : 1, as the owner's alternative), or T1-b +6% / −3%, 10 trading days.
- [ ] T2 Counting rules and stock list (section 6).
- [ ] T3 Historical gate and outcome words (section 5).
- [ ] T4 Forward rule and outcome words, including the month-based unit and the 50% single-month limit (section 6).
- [ ] T5 Checkpoints: month 3 sanity, month 6 verdict, one extension to 9.
- [ ] T6 Own candidate budget; not a Phase B candidate; Phase B reject set not used.

## 12. Freezing mechanics

1. Owner signs section 11.
2. Build the tool and tests (tests first; no live code and no frozen file touched).
3. Merge the signed file and tool to main; tag that merge `td-protocol-v1`. A run refuses without the tag, or if
   a frozen file changed since, or if a result/ledger row exists.
4. Run history once. Start the forward clock only after its counting rules are approved.
5. Any later change is `td-protocol-v2`; old results stay on record.
