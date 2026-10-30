# Diagnostic review: 5-day and 15-day evidence, and what it means for 10D (2026-10-26)

Diagnostic only. It compares two existing, signed, completed results and tunes nothing. Nothing in it changes a
protocol, a setting or the 15D trial. 5D and 15D numbers stay labelled and are never pooled.

## 1. The two results side by side (same window, same 49 stocks, same folds)

Window: 2023-07-01 to 2025-01-31, 21 folds of 28 days. Both used costs and 0.10% slippage and entered at the next open.

| | 5D (fd-protocol-v1, run 26 Oct) | 15D (wf-protocol-v1, run 12 Oct) |
|---|---|---|
| Trade rule | +2% target / −4% stop, trailing stop, model-confidence exit, 30-calendar-day time stop | +8% target / −4% stop, 15 trading days |
| Model question | close 5 days later ≥ +2% (endpoint) | reach +8% before −4% within 15 days (barrier) |
| Skill: folds beating every stock | 10 of 21 (48%) | 7 of 21 (33%) |
| Skill: daily edge over every stock, lower bound | −0.155% (edge −0.011%) | −0.51% (edge −0.19%) |
| Model-picked trades, average after costs | −0.37% (best 5), −0.42% (buy rule) | −0.20% |
| **Every stock, average after costs** | **−0.36%** | **−0.02%** |
| Model AUC across folds | 0.48–0.62 | 0.45–0.61 |
| Verdict | skill FAIL, economic FAIL | skill FAIL, economic FAIL |

## 2. What the 5D failure says

**Prediction quality.** Neither model separates winners from losers: fold AUCs sit between about 0.45 and 0.62 and
average roughly 0.52 in both. The 5D picks were no better than every stock (edge −0.011%), and the 15D picks were
worse than every stock. The 5D failure repeats the 15D finding with a different label, a different trade length
and a different model question. That points to the inputs (the features) carrying little signal for these
stocks, not to one wrong horizon.

**Costs.** Round-trip cost and slippage came to about 0.35–0.37% per trade (a +2% win nets 1.63%; a −4% loss nets
−4.35%). That is about 18% of the 5D target but under 5% of the 15D target. At 5D the *base* strategy
(every stock) already loses 0.36% per trade, so a model has to add more than 0.36% per trade just to reach zero,
and it added nothing. Costs hurt shorter horizons more; this is arithmetic, not a finding about the model.
Costs are worse under stress: 2× charges and fills 0.30% worse took 5D to about −1.2% per trade.

**Exit rules.** The 5D rule pays little for a win and a lot for a loss: it needs about 73% of trades to win after
costs to break even, and the best 5 won 51% and the buy rule 59%. The 5D trades ended: best 5 — 1,006 target, 509
stop, 464 confidence exit; buy rule — 2,884 target, 1,687 stop, 311 confidence exit. The structure fails even with
a good hit rate. That asymmetry is specific to +2% / −4%. The proposed 10D rule is the other way round (+6% /
−3.5%, 1.71 : 1), so the 5D payoff problem does not carry over. The 10D rule would still need a real hit rate:
about 41% of trades reaching the target after costs if no trade timed out (the 15D history shows most trades end
by time exit, so this is a rough guide only).

**Data contamination.** The confirmation window is now spent four times: by the 15D wf-protocol-v1, the cost
and pause checks, the horizon grids and the 5D run. Any further horizon run on it is
a re-use of studied data, so a pass there is weak evidence and a fail is not independent either. The 2025-10 to
2026-08 window looks better for 15D (model beat every stock in 8 of 12 windows, edge +0.22% per day, lower
bound +0.02%), but it was seen after the fact and is not a pass of a frozen protocol. Do not read it as evidence
that tuning would work.

## 3. Implications for the proposed 10D model

1. **Expect a FAIL.** Two different models at two horizons found no skill on the same data. A third model from the
   same features, scored on the same window, starts with a low prior. A 10D history FAIL costs little but adds
   no independent information, and a 10D PASS on a window used four times would only justify a shadow lane.
2. **Cost is not the main risk at 10D.** Costs are about 6% of a +6% target. The risk is prediction quality, which
   is where all three horizons currently stand.
3. **Do not retune from these results.** The 5D failure gives no basis to change +6% / −3.5% or any other 10D
   number. That decision rule stands: the setting follows the written noise rule and nothing else.
4. **The protocol holds up.** The pass thresholds, the block bootstrap and the sealed forward test behaved as
   designed on 5D: they refused a result that looked acceptable at some folds (10 of 21 won).

## 4. Options for the owner (not decided)

- **A. Hold 10D.** Keep `td-protocol-v1` as an unsigned draft; do not build the 10D model, history run or lane
  (Atlas hz10–hz14 stay paused). Put effort where evidence is already accumulating: the frozen 15D C1 trial and
  Phase B (from 9 Nov). My recommendation, because no horizon has shown skill and the inputs are the shared problem.
- **B. Sign and run 10D history as a cheap gate.** Low cost, low expectation, and it uses the window a fifth time.
- **C. Test 10D only on data not yet used for any horizon** (for example the Phase B reject set of 129 stocks) — this
  needs a change to the Phase B reject-only rule and the owner's approval, and is the only way a 10D history result
  would be independent.
- **D. New research hypothesis** about the inputs (features), under its own protocol, before any further horizon
  run. This is the question the three results point to, and it is a different decision from choosing a horizon.

## 5. Not recommended

Changing the 5D target or stop, adding a stronger exit to rescue 5D, switching 10D to the best-looking 5D or 15D
fold results, or reading the 2025-10..2026-08 window as support for any new rule.
