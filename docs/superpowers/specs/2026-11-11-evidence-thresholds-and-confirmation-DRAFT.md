# Evidence thresholds and fresh confirmation — DRAFT (2026-11-11)

**Status: DRAFT. Nothing here is signed. Every number marked PROPOSED needs the owner's decision.**
Nothing in this note changes h05, Phase B, the sealed trial, or any code.

## Why this note exists

An outside review (pasted 2026-11-11) named four gaps. This note records what is already covered, and
proposes the missing rules *before* the next comparison, so no one can pick the rules after seeing results.

## 1. What is already settled (verified in code, 2026-11-11)

| Rule | Where | Value |
|---|---|---|
| Uncertainty measured in blocks of signal days, not single picks | `h05_protocol.py` verdict_rule | blocks of 5 days, 90% range |
| PASS / FAIL / INCONCLUSIVE | `h05_verdict.py` | PASS = whole range above zero; FAIL = whole range below; else INCONCLUSIVE |
| Final verdict per group | `h05_verdict.py` | 3 runs of 60 signal sessions; at least 2 pass, none fail, pooled range above zero |
| Stop-before-target, gap fills at the open | `h05_rules.py`, `replay_scoring.py` | same candle touching both = the stop |
| Half out at +5% (15-day trades) | `replay_scoring.py`, `portfolio_sim.py` | half sold at +5%; stop is NOT moved up afterwards (cautious) |
| h05 trade is a different plan from the swing plan | `h05_rules.py` | h05 = +2% / −4% / 5 sessions, no half-out, on purpose |

## 2. Gaps and proposed rules

### G1. How big an edge is worth acting on (PROPOSED)

Today a PASS only means "above zero". Proposal: a model is worth acting on only if
(a) the 90% range is above zero **and** (b) the average edge after costs is at least **PROPOSED: 0.30% per trade**
(about twice the assumed round-trip slippage; owner to set). Below that, report "real but too small to matter".

### G2. Independent evidence needed (h05 already has it; PROPOSED for 10D/15D)

CORRECTION (2026-11-11, from the live h05 report): h05 already requires **40 matured signal days per group per run**
(unresolved item U2, still marked PROPOSED in the report). So this gap is covered for h05; it is open only for 10D/15D.

Five picks on one day are one observation, not five. Proposal for the 10D and 15D comparisons:
at least **PROPOSED: 40 independent signal blocks** (non-overlapping windows of the horizon length) per
group before any verdict other than INCONCLUSIVE. Fewer blocks are reported as "insufficient evidence".

### G3. Score the app actually serves (needs owner approval, touches the signed trial)

h05 stores both scores but not the input values. Proposal (code, before 30 Nov): add an append-only
record of the exact inputs, model version and shown score per prediction, **for new lanes first**;
adding it to `h05_signals` needs a protocol note and the owner's approval. The `obv_slope` train/serve
mismatch stays an owner decision after the trial.

### G4. A fresh window for the winner (PROPOSED)

Held-back stocks share the same dates as training, so they test "other stocks", not "other time".
Proposal: whichever Phase B survivor is locked on 4 Dec is confirmed only on **dates after the lock
(forward lane, first 60 signal sessions)**. A survivor that fails there is dropped; no retuning.
Report cap tier and market regime with their sample sizes; regimes are defined before the test, never after.

## 3. Next signed comparison (PROPOSED)

Model-only versus model + Brain WATCH filter, on the **same daily candidates**, same dates, same trade plan,
judged with the block rule and G1/G2 above. Answers: "do high-scoring WATCH stocks do better?"

## 4. Wording

Say **"forward evidence"**, not "proof". A forward pass supports one model version, horizon, universe and rule.

## Owner decisions needed

- [ ] G1 minimum edge (0.30% proposed)
- [ ] G2 minimum independent blocks (40 proposed)
- [ ] G3 approval to add the input record (new lanes first)
- [ ] G4 confirmation window = forward lane after 4 Dec lock
- [ ] Section 3 comparison approved as the next signed test
