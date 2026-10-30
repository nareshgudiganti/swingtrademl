# Incident note: `obv_slope` train/serve difference (recorded 2026-10-30)

Status: **documented only.** Nothing was patched in production, no history was rewritten, no recorded score was
changed, and the sealed 15-day trial was not touched. This note was written without reading any sealed-trial result.
Decision on any fix: the owner's, after the trial evaluation (audit item D13, fix proposal F15).

## What happened

One of the inputs the three production 5-day models (ids 2, 16, 17) were trained on, `obv_slope`, is **not served
the way it was trained**, and the difference has had two forms.

| Period | What production served | Versus training |
|---|---|---|
| **A. from first serving to the deploy on 2026-10-06** | the OLD formula (10-day OBV change ÷ 20-day mean OBV *level*), computed on the newest **400** bars (`predict.py` has used `limit=400` since the first commit) | training used the **full** stored history. The OBV level depends on how much history is loaded, so the value differed (a smaller difference) |
| **B. since the deploy on 2026-10-06** | the NEW formula (10-day OBV change ÷ 20-day mean **volume**) on the newest 400 bars | a different definition than training (a larger difference) |

The change into B was commit `fcaef35` ("Service 1 P0 and Phase 1 gate tooling…", 2026-10-05 21:28 IST), a 6-line change in
`ml/features.py`. Its own comment says why: the OBV-level denominator "differed between full-history training and M02's
400-bar window". The intent was good (make the brain's 400-bar snapshots consistent with each other); it did not check the
three saved models, which still expect the old definition.

## Dates (from GitHub Actions, not from the server; SSH to prod is blocked)

| When (IST unless marked) | Event |
|---|---|
| 2026-08-05 / 08-12 / 08-20 | models 2 / 16 / 17 trained (local registry `trained_at`; artifacts are byte-identical to prod, sha256 matched) |
| 2026-10-05 21:28 | `fcaef35` committed. Its own deploy run: backend tests failed, **deploy skipped** |
| 2026-10-05 21:45 | `0bdaa76`: deploy run failed (tests); deploy skipped |
| 2026-10-06 19:26 | `203be0b`: backend tests failed, deploy skipped |
| 2026-10-06 20:00-20:07 | `c96dfd9`: tests passed, **deploy step failed over SSH**. Whether any code reached the server is unknown |
| 2026-10-06 20:25-20:29 | `f69134a`: tests passed, **deploy succeeded**. This is the **first confirmed deployment containing the new formula** |
| 2026-10-14 | sealed trial starts; every trial score is therefore from period B |

So: period B began no earlier than 2026-10-06 and, on the evidence available, at 20:29 IST that day. Every later deploy
contains it too. Not yet verified: the exact commit running on the server hour by hour (needs the server or an uptime-stamped
`/status` record).

## What is affected

* The v1 `ml_swing` path (all three models) and the brain's scoring path (`brain/reader.py` calls `predict_instrument` with the
  production model) have served the shifted input in period B.
* Models trained and served on the same code (for example M06's own dataset builder, `ml/asof.py`, drift checks) are
  internally consistent and are not what this note is about; it concerns the three **saved** models 2/16/17.
* The h05 lane is not affected: it scores on the training-compatible inputs and stores the served score as a diagnostic.

## Size of the effect (a replay on one day, not a recorded trial score)

Signal day 2026-09-07, local data, the same saved models. Rank correlation between the production-path score and the score
on the exact training inputs:

| Group | Period A (old formula, 400 bars) | Period B (new formula, 400 bars) | Top-5 overlap in B |
|---|---|---|---|
| Large (model 2) | 0.929 | 0.687 | 3 of 5 |
| Mid (model 16) | 0.942 | 0.868 | 4 of 5 |
| Small (model 17) | 0.980 | 0.933 | 4 of 5 |

This is one day replayed with today's code. It shows the direction and rough size, not the trial's actual numbers.

## How it was proven (not from scaler statistics alone)

1. Saved scalers vs the model's own training data: every input reproduces except `obv_slope` (`h05_cli parity`).
2. **Historical code**: `ml/features.py` as committed before the change (git blob `d2f723d`, the parent of `fcaef35`; and the earlier
   `7da460c`) was run on the real full history of 36 stocks. Largest absolute difference from the lane's training-basis inputs,
   over every input of each model (about 35,000 complete rows): **0** for all three groups, for both historical versions.
3. Test `tests/test_h05_historical_features.py` repeats this on synthetic candles from a vendored copy of that historical file
   (sha256 pinned) and shows: all other inputs identical, today's `obv_slope` different, the lane's `obv_slope` identical to the historical one,
   and an identical saved-model score from either path.

## What stays exactly as it is

* **Recorded scores and ideas are the trial's data.** They are what the system actually produced; none is recomputed, overwritten or
  relabelled. The h05 tables and these notes sit next to them and never write into brain, signal or order tables.
* **Interpretation of the sealed trial:** it measures the system *as deployed*, including the period-B `obv_slope`. Its result must not be
  described as the performance of "the models as trained", and it must not be retro-corrected. If the owner later fixes the input (serve the old
  formula for these models, or retrain on the new one), that is a new version with its own evidence.
* The freeze test (`tests/trial_freeze.py`, `trial_freeze.json`) is unchanged; `ml/features.py` and `ml/predict.py` are untouched.

## Owner decisions this leaves open

1. Fix or not, and when (after the trial evaluation).
2. Which fix: serve the old definition for models 2/16/17 (needs full history, or a 400-bar-safe equivalent), or retrain them on the new definition.
3. Whether to confirm the exact commit on the server for 2026-10-06 (a server-side check; this session cannot SSH).
