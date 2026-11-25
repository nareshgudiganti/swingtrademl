# G1 shared decision note: the 5-session score and the 15-day plan (#282 G1, Feature 2 G9)

Status: **for owner decision. No code change. Frozen files not modified.** Prepared 25 Nov 2026 (IST).

## The facts (verified in code on main, eacbb42d)

- The Brain scores each stock with a 5-session model. The stored decision's score comes from that model.
- The trade plan (target +8%, stop -4%, half out at +5%, 15 sessions) comes from one policy object:
  `backend/src/swing_trade_ml/brain/modules/m08_decide/policy.py` (`DEFAULT_POLICY`). This file is on the frozen list.
- A TRADE idea is therefore a 5-session score with a 15-session plan. The stock page labels the plan as 15 days and the
  "out by" day counts 15 sessions. The score is not labelled as a 5-session score.
- The same 15-session plan is served by `services/trading_rules.py` (`brain_plan.max_sessions`). That endpoint is
  shared (#416, PR #479 merged 24 Nov).

## Why this is an architecture decision, not a display fix

Two separate facts are being shown as one: the model that produced the score (5 sessions) and the rule that sets the
exit (15 sessions). Relabelling alone would hide a real mismatch. Fixing the mismatch means either retraining or
rescoring (a model change) or changing the plan horizon (a policy change). Both are frozen or gated.

## Options

| Option | What changes | Behaviour change | Frozen files | Approval needed |
|---|---|---|---|---|
| A. Label only: "score from the 5-session model; plan is a 15-session rule" | Text on stock page and Today | Wording only | None | Owner wording approval |
| B. Show the 5-session horizon as the plan window | Plan window and "out by" day | Changes the exit date shown to users | `policy.py` or the decision contract | Owner and trial-freeze approval |
| C. Rescore or retrain on the 15-session horizon | Model and score | Changes scores | Model and score files | Owner and model-activation approval (out of scope now) |

## Recommendation

Option A now, because it changes no behaviour and no frozen file, and it stops the screens from implying the score
predicts 15 days. Options B and C wait for the owner's decision after the trial. Both are listed in #282 section 8
item 1.

## Coordination

- Feature 2 G9 ("5-session model shows 5D") is the same question, seen from the Today screen. One decision covers both.
- #341 (gated post-trial) is the bug record for the same mismatch.
- #326 (explicit 5D/10D/15D flags) is the planned display fix. It needs this decision first.

## Owner decision needed

1. Approve option A (label only), or choose B or C.
2. Confirm the wording for option A.
