# Corrections to earlier statements about the existing models (2026-10-30)

Status: **record, 2026-10-30.** Documentation only. It changes no model, setting, protocol, trial rule or result.
Earlier statements are quoted as they were made and stay where they were made; this file says which were wrong or
incomplete, what is now known, and how it was checked. Nothing earlier was silently rewritten.

How the facts were checked (all read-only):

- the three production model **files**, downloaded from prod with `GET /api/v1/ml/backup/models.zip` and compared
  by sha256 with prod's own manifest;
- the production **registry** (`GET /api/v1/ml/models`), which matches the local registry rows for ids 2 / 16 / 17;
- today's feature code **replayed on each model's own training stocks and period** and compared with the mean and
  spread that model's saved scaler learned (`swingtrade`-independent: `python -m swing_trade_ml.brain.lanes.h05_cli parity`).

| # | Earlier statement (where) | Corrected finding | Evidence |
|---|---|---|---|
| C1 | "The same 53 features the model uses" (`docs/superpowers/plans/2026-10-01-brain-m02-perception.md`, goal line; `docs/brain/BUILD_NOTES.md`, M02 row). Repeated by me as "all three models share the same 53 chart inputs" in the 2026-10-29 model review page | **53 is the size of today's feature builder (`FEATURE_COLUMNS`). The three production 5-day models use fewer: large cap 37, mid cap 46, small cap 46.** The large model lacks the 4 newer technical inputs, the 4 index-relative inputs, the 3 sector inputs, the 2 VIX inputs and the 2 breadth inputs (16 in all); the mid and small models lack the 3 sector, 2 VIX and 2 breadth inputs (7 in all). The 53 is correct only for models trained after the Sep 2026 feature work (the barrier models) | Each artifact's own `feature_names` (37 / 46 / 46) equals its registry row; the saved order follows the code's order |
| C2 | Mid- and small-cap prod models "trained on 150 / 104 mid- and small-cap stocks" (my review page; and by juxtaposition wherever the v1 lists 52 / 150 / 104 sit next to models 16 / 17 in the 2026-10-29 notes) | **Training stocks: large 49, mid 24, small 30** (data to 2025-10-09, 2025-10-28 and 2025-11-05). The **51 / 150 / 104** training lists belong to a *different* set of models: the barrier models of 2026-09-15 and the calibrated models of 2026-10-08/09 (`real_question_calibrated_models_20261009.md`, `audit-data-integrity` section 2). The numbers 52 / 150 / 104 are v1's **trading** lists | `ml_models.training_symbols` for ids 2 / 16 / 17: 49 / 24 / 30 |
| C3 | "Trading/evaluation universe and training universe" were treated as one set | **They are separate.** h05 scores 52 / 148 / 102 stocks (v1's lists minus two names in both mid and small lists). Of those, only some were in each model's training list; most mid- and small-cap names were never seen in training. h05 stores `trained_on_symbol` on every row and reports the two subsets as a diagnostic | `h05_cli check`, section 4 of the protocol |
| C4 | Model score audit D1–D12 treat the production score as the output of the model *as trained* (`2026-10-29-audit-model-scores.md`, section 1, S1–S4) | **New finding D13: since the 2026-10-05 deploy (`fcaef35`) the `obv_slope` input is computed with a different formula than the one the saved models were trained on.** It is the only one of 37 / 45 / 45 compared inputs that is not reproduced; with the old formula on full history the saved scalers are reproduced almost exactly. On 2026-09-07 the production-path scores correlate with the training-basis scores 0.69 / 0.87 / 0.93 (large / mid / small) and the large-cap top 5 overlaps 3 of 5. This affects the v1 bot and the brain (model 2) since that deploy, so it is inside the sealed trial. **Not fixed here**: `ml/features.py` is trial-frozen | parity report, section 5 of the protocol; `git show fcaef35 -- ml/features.py` |
| C5 | "Model rows exist locally, so the models can be checked locally" (implied by the local registry) | The local registry holds the rows for ids 2 / 16 / 17, but **the model files are not on the laptop**: their paths are the server's container paths. Verification used prod's backup zip | `ls backend/data/models` has no `swing_classifier_*` file |
| C6 | "~302 stocks scored by the brain" and "52 / 150 / 104" (several notes) | Consistent, but worth stating once: 52 + 150 + 104 = 306 names; two names appear in both the mid and small lists, giving 304 distinct names, of which h05 excludes the two ambiguous ones (302 left, 52 / 148 / 102) | `h05_cli check` |

## What these corrections do and do not change

- They do **not** change the sealed trial, Phase B, any signed protocol or any earlier result.
- C4 is the only finding with a possible effect on past results: the trial's scores since 2026-10-14 came from the
  changed `obv_slope`. The size of the effect on outcomes is unknown; the effect on scores is measured above.
  Whether to restore the training formula for serving is a separate decision for after the trial evaluation.
- The h05 lane's primary score uses the inputs each saved model expects; the production-path score is stored next to
  it as a diagnostic, so the gap is measured on every signal day rather than argued.
