# Ablation Results, Recovered

Date: 2026-09-15
Status: recovering lost research — Stage 1.8 of `2026-09-14-quant-gap-roadmap-to-10L.md`

Seven model artifacts sat in `backend/data/models/` dated 2026-09-09 with no
written record of what they showed. Three of the seven `.joblib` files are no
longer on disk; their `ml_models` rows survive and are reported below from
that row alone. This document recovers what can be recovered, from the
database rows and the four surviving artifacts' saved `feature_names` lists —
not from memory of why they were run.

All seven predate this session's barrier-label work: every one is
`label_kind = "endpoint"`, scored on the old "was the close higher at the
horizon" question, not "+X% before −Y%". Take the numbers below as evidence
about the *old* label and the old feature set, not as a verdict on the
barrier label — that comparison does not exist yet.

---

## 1. Large-cap feature ablation

Four models, same 47-symbol large-cap universe, same label (5-day horizon,
+2% threshold), same algorithm (LightGBM), same 48k-row single chronological
split — only the feature set differs. Feature deltas confirmed by diffing
each artifact's saved `feature_names` list directly, not inferred from the
model name.

| Model | Features | vs. baseline | Accuracy | Precision | Recall | ROC AUC | Precision @0.60 | n confident |
|---|---|---|---|---|---|---|---|---|
| `exp_baseline_large` | 46 | — | 0.539 | 0.269 | 0.537 | **0.552** | 0.288 | 2,439 |
| `exp_marketonly_large` | 50 | +breadth (2) +VIX (2) | 0.553 | 0.264 | 0.481 | **0.544** | 0.280 | 2,362 |
| `exp_sectoronly_large` | 49 | +sector relative strength/regime (3) | 0.530 | 0.266 | 0.544 | **0.552** | 0.291 | 2,485 |
| `exp_sectorfeat_large` | 53 | +everything above (7) | 0.563 | 0.266 | 0.465 | **0.541** | 0.285 | 2,321 |

**Finding: none of it moved ROC AUC.** 0.541–0.552 across all four — a spread
smaller than run-to-run noise on this sample size. Market breadth and INDIA
VIX, added alone, did not help. Sector relative strength, added alone, did
not help. Both together did not help. Accuracy moves more (0.53–0.56) but
that is the model trading recall for precision at the margin, not real
separation — ROC AUC is the number that would show it if the extra features
were finding signal, and it does not move.

**Caveat:** `exp_baseline_large`'s own 46-feature set is not "no context at
all" — it already includes benchmark-relative strength against NIFTY
(`relative_strength_5d/20d`, `nifty_trend_regime`, `nifty_volatility_20`) per
`ml/features.py`'s `FEATURE_COLUMNS`. What these three ablations tested
specifically is breadth/VIX and *sector*-relative context *on top of* an
already benchmark-aware baseline — not "market context vs. no context at
all". Framed that way, the null result is less surprising: the model already
had a market-relative signal before any of these were added.

## 2. Mid-cap feature ablation

Same three-way comparison, mid-cap universe (150 symbols, 145,128 rows —
roughly 3x the large-cap sample).

| Model | Features | vs. baseline | Accuracy | Precision | Recall | ROC AUC | Precision @0.60 | n confident |
|---|---|---|---|---|---|---|---|---|
| `exp_mid_baseline` | 46 | — | 0.561 | 0.336 | 0.518 | **0.567** | 0.362 | 6,058 |
| `exp_mid_sectoronly` | 49 | +sector (3) | 0.556 | 0.332 | 0.519 | **0.564** | 0.360 | 6,016 |
| `exp_mid_all` | 53 | +sector +breadth +VIX (7) | 0.564 | 0.334 | 0.500 | **0.562** | 0.376 | 7,122 |

**Same finding, same size of null result.** ROC AUC 0.562–0.567 — again
inside noise. The mid-cap dataset is 3x larger than large-cap's, so this is
not a small-sample artifact; more rows did not surface a gap the smaller
large-cap set was hiding. Note there is **no `marketonly`-alone variant for
mid-cap** — the original experiment design tested sector-only and
everything, but never breadth/VIX in isolation for this tier. That is a real
gap in the historical record, not a result — do not read anything into its
absence.

## 3. Large-cap horizon/target sweep

Three models varying the label's horizon and threshold (all endpoint-style,
all large-cap, all LightGBM). Artifacts are missing from disk for these
three; figures below come from the `ml_models` row alone.

| Model | Horizon | Threshold | Accuracy | Precision | Recall | ROC AUC | Precision @0.60 |
|---|---|---|---|---|---|---|---|
| `exp_h5t1` | 5 days | +1% | 0.509 | 0.378 | 0.484 | **0.500** | 0.344 |
| `exp_h10t3` | 10 days | +3% | 0.546 | 0.282 | 0.453 | **0.524** | 0.279 |
| `exp_h20t5` | 20 days | +5% | 0.553 | 0.243 | 0.402 | **0.501** | 0.243 |
| `exp_baseline_large` (for reference) | 5 days | +2% | 0.539 | 0.269 | 0.537 | **0.552** | 0.288 |

**The most consequential finding in this whole recovery.** ROC AUC across
every horizon/threshold combination tried sits at 0.500–0.524 —
indistinguishable from a coin flip. Only the original 5-day/+2% baseline
(0.552) is any real distance from 0.5, and that is itself a modest edge. No
endpoint-label configuration tried here — tighter, looser, longer, shorter —
found a version of "will the close be higher" with real discriminative
power. This is exactly what motivated the barrier-label work already done
this month: the endpoint framing itself may be the ceiling, not the horizon
or threshold chosen within it. That is now a testable question rather than a
guess — the barrier models trained on 2026-09-15 (`swing_classifier_barrier`,
`_midcap_barrier`, `_smallcap_barrier`) are the direct comparison, and their
own walk-forward evidence is no stronger yet (ROC AUC 0.50–0.62 across folds)
— see the training log for that date. Whether reframing the question as a
barrier helps is still open; it has not yet been shown to.

## 4. What this settles, and what it does not

**Settled:** for the endpoint label, on this feature set, on this data —
sector context, market breadth, and INDIA VIX did not produce a measurable
edge, at either cap tier, and no horizon/threshold combination tried
produced strong separation. This is real evidence, not an oversight; the
features are not obviously broken, they simply did not show up in ROC AUC
under this label.

**Not settled:**
- Whether the same features help under the **barrier** label — untested; the
  ablation was never re-run after 1.2.
- Whether a **combination not tried** (e.g. sector + longer horizon, or
  breadth alone without VIX) would differ — the seven runs here are the ones
  that happened to be run, not a full grid.
- Whether **fundamentals**, which contributed to none of these seven, would
  do better than the context features that were tried and did not.

## 5. What to do with this

- Before spending more effort on sector/breadth/VIX feature engineering,
  re-run this same ablation once there is a real barrier-label walk-forward
  record to compare against, rather than assuming the old null result still
  holds.
- Treat the horizon/threshold sweep's flat ROC AUC as the standing reason
  the barrier label was worth building, not as a closed question — it is
  the baseline the barrier label has to beat, and hasn't decisively yet.
- The missing three artifacts are a process lesson on their own: model
  artifacts on a local disk are not a durable record. `ml_models.metrics`
  survived because it is in the database; the joblib files did not because
  they were never backed up. Worth remembering before treating any future
  experiment's disk artifact as retrievable indefinitely.
