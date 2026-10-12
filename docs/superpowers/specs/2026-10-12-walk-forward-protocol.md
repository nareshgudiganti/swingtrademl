# Walk-forward validation protocol (wf-protocol-v1) — FROZEN 2026-10-12

Status: frozen on 2026-10-12 after the owner signed off every item (sections 8 and 9). The commit is tagged
`wf-protocol-v1`. The confirmation run is done once; no setting changes after seeing a result.

Tool: `backend/src/swing_trade_ml/brain/walk_forward.py` (read-only evidence; registers `wf_*` trial
models locally, never activated, no live change). Its report prints the protocol version.

## 1. What "window" means here

| Name | Meaning | Length |
|---|---|---|
| Holding window | How long one trade may last | up to 15 trading days |
| Label window | The 15 days a training row looks ahead to learn its answer | 15 trading days |
| Training window | Data a model learns from, ending at its cutoff | all history up to cutoff |
| **Test window (fold)** | One block of days a retrained model is judged on. **The 60% counts these.** | 28 calendar days |
| Replay window | Days a full brain replay covers (layer 2) | about 1 month |
| M18 gate unit | What lets the owner leave Practice | 30 finished ideas, not a window |

Passing this test never counts toward the M18 gate.

Fold boundaries: folds are back to back from the first test day, each 28 calendar days, cutoff = the
day before the fold starts. A trade belongs to the fold of the day it was decided. Trades near a fold's
end finish after it ends; they stay in that fold. Because a trade can last 15 trading days, trades from
neighbouring folds overlap in time, which is why the confidence check uses 15-day blocks (section 5).

## 2. What is tested

Layer 1 only: the model's daily top-5 ranking against baselines. Layer 2 (the full brain: risk check,
sectors, score over 80) gets its own protocol after layer 1.

## 3. Fixed settings

| Setting | Value |
|---|---|
| Rule scored | next-day open entry, +8% / -4%, half out at +5%, 15 trading days, costs and slippage |
| Model labels | +8% before -4% within 15 days |
| Picks per day | best 5 by model score |
| Fold length / retrain | 28 calendar days / once per fold |
| Universe | today's 49 watchlisted stocks (survivor bias, stated in the report) |
| Baselines | every stock (= random expected value); 5 strongest 20-day risers |

## 4. Sample

Candles run 2021-08 to 2026-09. Models need about 2 years of history, so the first test day is
**2023-07-01**.

**The proposed sample 2023-07 to 2025-09 is not clean.** `docs/brain/evidence/` holds horizon-grid runs on
2025-02-03 to 2025-06-30 and 2025-08-01 to 2025-12-31. Those compared holding times, targets and stops
on days inside it. The settled +8% / -4% / 15-day rule predates them, and I have not found a rule that
was changed because of them, but those two periods have been looked at.

Proposed split:

| Sample | Dates | Folds | Use |
|---|---|---|---|
| **Confirmation (untouched)** | 2023-07-01 to 2025-01-31 | 21 | pass or fail |
| Seen | 2025-02-01 to 2026-08-15 | about 18 | reported, never counted for pass or fail |

21 folds clears the 12-fold minimum. Model features and settings were built over the whole history
earlier in 2026, so "untouched" means "no test or tuning of this protocol on it", not "never seen by
any developer".

## 5. Decision rule

An **eligible fold** has at least 10 test days and at least 20 finished model ideas.

Two independent answers. Each needs at least 12 eligible folds and 100 finished model ideas, otherwise it
is "insufficient", not "fail".

| Part | Fold counts as won when | Also required |
|---|---|---|
| **Predictive skill** | model's average result per day beats every-stock's | at least 60% of eligible folds won, and the lower bound of the daily edge over every-stock is above zero, using 15-day blocks |
| **Economic value** | model's average result per day after costs is above zero | at least 60% of eligible folds won, and the average per trade over all folds is above zero |

The 60% is provisional until sign-off, then frozen. It is an acceptance threshold, not proof. It is
never changed after seeing a result. Layer 1 has no account simulation, so it cannot measure a true
drawdown; the report shows the worst eligible fold instead.

| Predictive | Economic | Reading |
|---|---|---|
| pass | pass | strongest evidence the model is useful |
| pass | fail | picks beat random, trades do not make money |
| fail | pass | trades made money, beating random not shown |
| fail | fail | no evidence of skill and no profit |

## 6. Report must show

Per fold: test days, market type, model, baselines, days won, model AUC. Overall: ideas, hit rate,
average per trade, edge with lower bound, folds won by market type, the two answers, worst eligible fold,
and the limits (survivor bias, daily candles cannot say which of target or stop came first).

## 7. Known limits

- Survivor bias: universe is today's watchlist.
- The tested model is trained to this rule; it is not the exact model in prod.
- AUC per fold can fall below 0.5; folds share one market; 21 folds is a small sample.
- No sizing, sector cap, drawdown halt or risk check is tested here.
- A pass does not justify automatic live trading. Layer 2 and the manual-approval stage still come first.

## 8. Decisions recorded (owner, 2026-10-12)

| Item | Decision |
|---|---|
| Evaluation unit | 28-day folds with explicit boundaries (section 1) |
| Acceptance threshold | 60% of eligible folds, provisional until frozen; counted per part (section 5) |
| Confirmation period | only if untouched; narrowed to 2023-07-01 to 2025-01-31 (section 4) |
| Verdict | two parts: predictive skill, economic value |
| Scope | layer 1 only |

## 9. Sign-offs (owner, 2026-10-12)

- [x] Confirmation sample 2023-07-01 to 2025-01-31 (21 folds), on condition that no other model or strategy
  decision was informed by results from this period. Seen periods are excluded from pass or fail.
- [x] Section 5 definitions: both parts, 10 test days and 20 ideas per eligible fold, at least 12 eligible
  folds and 100 ideas per part; insufficient evidence gives `insufficient`, not `fail`.
- [x] No drawdown gate in layer 1. The report shows the worst eligible fold and says it is not portfolio
  maximum drawdown. Portfolio-level drawdown validation is a requirement for layer 2.

## 10. Freezing mechanics

1. Sign-off on section 9.
2. Commit this file and `walk_forward.py`; tag `wf-protocol-v1`.
3. Run once on the confirmation sample. No re-runs with changed settings.
4. Any later change is `wf-protocol-v2`; old results stay on record.
5. Output goes to `docs/brain/evidence/`, never counted toward the M18 gate.
