# First Barrier-Label Retrain

Date: 2026-09-15
Status: Stage 1.7 of `2026-09-14-quant-gap-roadmap-to-10L.md` — retrained, not promoted

## What was done

All three cap-tier models retrained on the barrier label (+8% before −4%,
within 15 trading days) against the real local database — 399,321 daily
candles, 324 instruments, Aug 2021–Sep 2026 — using each tier's real
production watchlist (the exact symbol list each live strategy trades), with
5-fold walk-forward validation.

Trained under **new, isolated model names** —
`swing_classifier_barrier`, `swing_classifier_midcap_barrier`,
`swing_classifier_smallcap_barrier` — never the live `swing_classifier` /
`_midcap` / `_smallcap` names. `activate_model()` and `get_active_model()`
are both scoped by name (verified in `ml/registry.py` before running
anything), so activating these three cannot archive or otherwise disturb the
models the paper strategies are actually trading against. Confirmed after
the fact: all three original ACTIVE rows are unchanged.

Registered as three new **advisory** shadow strategies —
`ml_swing_main_barrier`, `ml_swing_midcap_barrier`, `ml_swing_smallcap_barrier`
— each mirroring its auto counterpart's exact symbol list. `execution_mode =
"advisory"` means these can never place an order (`services/execution.py`,
`core/strategy_policy.is_advisory`); they only ever write a `Signal` row,
scored by the same `job_evaluate_signals` every other signal is. That is the
entire comparison mechanism — no new code, no switchover, no gap in the
paper record. Smoke-tested with one real scan of the large-cap shadow before
trusting it to the unattended 15:45 job: 51 signals generated across 52
instruments, zero orders placed, zero errors.

## Results

| Model | Symbols | Rows | Accuracy | Precision | Recall | ROC AUC | Precision @0.60 (n) |
|---|---|---|---|---|---|---|---|
| `swing_classifier_barrier` (large) | 51 | 49,528 | 0.664 | 0.209 | 0.395 | 0.583 | 0.240 (1,814) |
| `swing_classifier_midcap_barrier` | 150 | 143,628 | 0.602 | 0.273 | 0.426 | 0.564 | 0.327 (5,816) |
| `swing_classifier_smallcap_barrier` | 104 | 98,181 | 0.586 | 0.304 | 0.428 | 0.556 | 0.345 (4,018) |

### Walk-forward, 5 folds each (expanding window, purged by exact label window)

**Large cap** — ROC AUC by fold: 0.502, 0.509, 0.542, 0.495, 0.616.
**Mid cap** — 0.560, 0.519, 0.588, 0.551, 0.572.
**Small cap** — 0.548, 0.507, 0.549, 0.424, 0.587.

## Reading this honestly

**The held-out ROC AUC (0.556–0.583) is modest, not strong** — meaningfully
above the 0.500–0.524 the old endpoint label's horizon sweep produced (see
`2026-09-15-ablation-results-recovered.md` §3), but this is evidence of a
real if small edge, not evidence of a working trading model yet. Two of
fifteen individual folds landed at or below 0.50 (large-cap fold 4: 0.495;
small-cap fold 4: 0.424) — the edge is not stable across every market
condition captured in this history, which is exactly what walk-forward
exists to expose rather than hide.

**Precision at the 0.60 confidence threshold is the number that matters
more than accuracy here**, and it is genuinely encouraging in places: mid
and small cap both clear 0.32–0.35 against roughly a 0.25–0.30 base positive
rate — a real lift when the model is confident, even though its overall
discrimination (ROC AUC) is only modest. Large cap's lift is smaller (0.240
vs. a 0.16–0.18 base rate). This is precisely the pattern a calibration
report is built to quantify properly — see `ml/calibration.py` (Stage 1.6) —
rather than eyeballing it from a single number.

**None of this is promoted.** All three barrier models are `ACTIVE` only
under their own new names, feeding advisory shadow strategies that place no
orders. The live paper strategies keep trading the old endpoint models
exactly as before. Promotion is the next decision, and it should wait for:

- enough shadow-strategy signals to have resolved (`outcome` populated by
  `job_evaluate_signals`) to build a real calibration table via
  `ml/calibration.py`'s `signal_calibration()`, not just the training-time
  numbers above;
- a side-by-side comparison against the live endpoint models' realised
  accuracy over the same calendar period, not a comparison against a
  different historical window;
- the same scrutiny any model promotion gets — a deliberate act, never
  automatic.

## What this does and does not answer

**Answers:** the barrier label is trainable, produces a real (if modest)
signal, and is now running unattended, generating comparable evidence every
trading day without needing to be revisited.

**Does not answer:** whether it beats the endpoint models it shadows. That
needs the shadow strategies to run for a real stretch of paper trading days
before there is enough resolved-signal evidence to say so honestly — this
document is the starting point for that comparison, not its conclusion.
