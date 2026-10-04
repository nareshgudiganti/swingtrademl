# Brain M06 · Calibrated Meta-Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One honest probability per stock — the chance of reaching +8% before −4% within 15 trading days — combining the barrier model, the swing model and market/stock context, proven on months no model has seen; switched on only if it beats the simpler alternative.

**Architecture:**
- *Offline* (`swingtrade brain meta-train`): build a dataset of stock-days from the unseen window (after the base models' `train_end`, plus a 15-day purge), with the barrier label from `ml.features.build_label`; score the base models on those rows; evaluate three candidates by monthly walk-forward (train on earlier months, test on the next): (a) raw barrier probability, (b) barrier probability calibrated with isotonic regression, (c) a small logistic meta-model on 8 inputs. Pick the best by out-of-sample Brier score, with (c) adopted only if it beats (b). Fit the winner on the whole window and save it with its report (metrics per fold, calibration buckets) as `brain_meta_vN.joblib` + `.json` in `MODEL_ARTIFACT_DIR`.
- *Runtime* (module `M06`, step `reason`, default SHADOW): for each stock, score the base models on M02's dated snapshot features, apply the saved combiner, and write an `Opinion(source="combined", calibrated=True)` whose threshold is the break-even probability for a positive expected result after costs plus a margin. M08 then shows the calibrated chance with its track record and computes expected result in R from it.

**Spec:** build book M06; owner decision 2026-10-01 (one calibrated model); principles P7 (shadow before trust), P8 (only data known then), P11 (evidence, not promises).

## Global Constraints

- Label: `build_label(df)` defaults (+8% / −4% / 15 trading bars; same-bar touch = stop).
- Unseen window starts after the later of the two base models' `train_end`, plus 15 trading days.
- Meta inputs (8): logit(p_barrier), logit(p_swing), `nifty_trend_regime`, `breadth_pct_above_sma50`, `vix_percentile_rank`, `relative_strength_20d`, `high_52w_dist`, `sector_trend_regime`.
- Walk-forward: monthly, expanding window, at least 3 months of training before the first test month.
- Adoption: meta-model only if its OOS Brier < calibrated barrier's; otherwise the calibrated barrier probability is the combiner. Report always saved.
- Threshold = break-even p (EV = 0 at a typical position) + 0.05.
- Missing base model or artifact → M06 writes nothing; the reason fallback answers. Never raise.

## Review Focus

1. No row whose label window overlaps model training enters the evaluation (purge). (Task 1 test)
2. A fold never trains on months after its test month. (Task 2 test)
3. When the meta-model does not beat calibration, the report says so and the calibrated barrier is used. (Task 2 test)
4. A calibrated probability below the threshold is WAIT with the honest chance shown. (Task 4 test)
5. Production lacks the barrier model files: M06 writes nothing and says why in its health. (Task 4 test)

### Task 1: Dataset (pure split + DB builder)
### Task 2: Trainer, walk-forward evaluation, calibration buckets, adoption
### Task 3: Artifact + `swingtrade brain meta-train` + report
### Task 4: M06 module, `Opinion.calibrated`, M08 evidence/EV from a calibrated opinion
### Task 5: Train on the check DB, report the real numbers honestly, local run
