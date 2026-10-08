# Retrain on the real question — evidence (2026-10-08)

Question trained: "does the stock touch **+8% before -4%** within **15 trading days**?"
(the app's real rule; prod models answer "+2% in 5 days").

## What already existed (found, not rebuilt)

The honest triple-barrier label is already in the code and is already the **default**
(`ML_PREDICTION_HORIZON_DAYS=15`, `ML_TARGET_RETURN_PCT=0.08`, `ML_STOP_RETURN_PCT=0.04`):
`ml/features.py::build_label` (daily high/low, same-day target+stop = stop, last 15 rows
dropped, horizon in trading bars), exact per-row `label_end_ts` purging in
`ml/dataset.py::chronological_split`, and expanding-window `walk_forward` in `ml/train.py`.
Barrier models were first trained 2026-09-15 (`docs/superpowers/research/2026-09-15-barrier-model-retrain.md`).
So the prod "+2%/5d" models are simply old; the fix is to retrain and promote, not a new label.
The prod models' endpoint-label rows are `label_kind=endpoint`.

## What this change adds (all opt-in, nothing activated)

- `ml/calibrated_model.py`: `CalibratedEstimator` (isotonic map fitted on the LATER 25% of the
  training dates, base model fitted on the earlier 75%, purged by `label_end_ts`) and
  `reliability_table`. The wrapper has `predict_proba`/`predict`/`feature_importances_`, so
  every serving path (`predict.py`, `ml_swing.py`) works unchanged and train/serve feature
  parity is untouched (same `FEATURE_COLUMNS`, same scaler).
- `fit_and_score`/`walk_forward`/`train_model(calibrate=False)` and CLI `swingtrade train --calibrate`.
  Default off = identical behaviour. Every fit now also stores a `reliability` table in the
  model's `metrics` (additive key).
- Tests: `backend/tests/test_real_question_label.py` (horizon edge bar 15 vs 16, timeout =
  0, stop-then-target = loss, same-day = stop, no look-ahead, defaults = real rules,
  calibration opt-in).

## Training run (local dev DB only, nothing active)

399,321 daily candles, 324 instruments, 2021-08 to 2026-09; watchlisted symbols (49), 47,606 rows.
Saved as NEW names `real15d_raw_20261008:v1` and `real15d_cal_20261008:v1`, status TRAINED.
Existing models/rows and artifacts untouched. 5-fold walk-forward, chronological 80/20 final split
(test = roughly Oct 2025 to Aug 2026).

**Positive rate of the real label: 18.1% in train, 15.8% in the held-out window.**
(Up to 23% in some folds, 12% in fold 4.) This is the number a confidence must beat.

### Held-out window, calibration table

| Stated confidence | Raw model: n, actual hit rate | Calibrated model: n, actual hit rate |
|---|---|---|
| 0.00-0.30 | 3279, 12.7% | 9368, 15.3% |
| 0.30-0.40 | 1825, 13.5% | 144, 39.6% |
| 0.40-0.50 | 1526, 14.5% | 17, 41.2% |
| 0.50-0.60 | 1162, 15.4% | 1, 0% |
| 0.60-0.70 | 739, 17.5% | 1, 0% |
| 0.70-0.80 | 551, 19.8% | 2, 50% |
| 0.80-1.00 | 469, 43.5% | 18, 38.9% |

Raw model: ROC AUC 0.588, precision at 0.60 = 25.1% (1,759 signals). The 70%+ band hits
**20-43%**, not 70%. That is better than the +2%/5d model's ~12% against that model's own
question, but the raw score is still NOT a probability (class_weight="balanced" inflates it).
Calibrated model: ROC AUC 0.577; it essentially stops saying "70%+" (only ~20 of 9,500 rows
reach 0.6+), which is the honest outcome when the real hit rate is ~16%.

### Walk-forward (raw model), ROC AUC / hit rate at conf >= 0.60 (n)

| Fold | Test window | Base rate | AUC | Hit @0.60 (n) |
|---|---|---|---|---|
| 1 | 2023-05 to 2024-01 | 19.7% | 0.500 | 16.1% (62) |
| 2 | 2024-01 to 2024-08 | 22.9% | 0.502 | 22.6% (2204) |
| 3 | 2024-09 to 2025-04 | 18.4% | 0.544 | 21.3% (2812) |
| 4 | 2025-04 to 2025-12 | 12.3% | 0.478 | 12.1% (1183) |
| 5 | 2025-12 to 2026-08 | 17.3% | 0.617 | 28.4% (1519) |

Calibrated walk-forward AUCs: 0.517, 0.505, 0.484, 0.472, 0.604; it produced 0 signals >= 0.6
in four of five folds and 113 in fold 5 (hit rate 55.8%).

## Honest limits

- The edge is weak and unstable: AUC is about 0.50 in 4 of 5 folds and only clearly useful in the
  last one. Do not read the raw model's 0.8+ band (43%) as general; it comes mostly from fold 5.
- A calibrated "70%" is almost never reached; with a ~16% base rate the strength score will mostly
  sit in 0.15-0.40. The UI/threshold (`ML_MIN_CONFIDENCE=0.60`) would need re-basing before a
  calibrated model drives anything, otherwise it produces almost no signals.
- Calibration slice is the latest 25% of training dates (one regime); isotonic on ~9k rows,
  heavily clustered (overlapping 15-day windows, correlated stocks), so effective sample is smaller.
- Candles end 2026-09-08 on this local DB; tier models (mid/small cap) were not retrained here.
- Trades are scored at the signal-day close; intraday same-day order is unknowable (stop-first rule).
- Not run through the shadow strategy; no live evidence yet.

## Owner command to reproduce (local or on the droplet, nothing activates)

```
swingtrade train --name swing_classifier_barrier_cal --walk-forward-folds 5 --calibrate
# omit --calibrate for the raw model; omit --activate (default) so it stays TRAINED
```
Compare in the model's `metrics.reliability` / `metrics.walk_forward`; activation stays a
deliberate step (`POST /api/v1/ml/models/{id}/activate`).
