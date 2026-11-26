# Immutable prediction provenance: finding and minimum proposal (#226, #389)

Written 2026-11-24 (IST). **PROPOSAL ONLY.** Nothing is built, and no frozen trial file changes. The migration needs owner approval.

## Finding (from the 637-row addendum)

- `predictions` rows are **overwritten** when the same stock and bar are scored again (`ml/predict.py:192-198`). The 49 rows of the
  2026-09-06 scan now hold inputs computed with the post-2026-10-05 `obv_slope` formula, so a saved prediction's inputs are not fixed.
- `predictions` has no created-at column, and `candles` has no ingestion timestamp. A later reader cannot tell when a row was written or
  whether the bar it used was final.
- 539 of 637 rows were scored on a last bar that was **not the final bar** stored today. Whether that was a live intraday bar or an
  earlier stored version is **not known**. No local ingestion evidence exists, and `candle_corrections` and `candle_arrivals` are empty.
  It is **not** claimed to be a data correction.
- `ml/predict.py` is a frozen trial file (`backend/tests/trial_freeze.json`), so it is not changed here.

## What already exists (on `main`)

`score_ledger` (#389 slice 2, migration `20261123_1200_identity_phase1.py`, writer `services/identity/ledger.py`):

- Write-once. Database triggers refuse UPDATE, DELETE and TRUNCATE (`20261123_1200_identity_phase1.py:5,25,124`).
- A changed value becomes a numbered revision with `supersedes_id` (`ledger.py:1-10`). A failed score is a `missing` row, never 0.
- Key: security, session date, horizon, source, model name, model version, revision. It also has `input_cutoff`, `scored_at`, `run_ref`, `scan_key`.
- Written from `services/score_history.py:290,306` and `append_from_brain_run` (`ledger.py:263`). Neither file is frozen.

**Gap:** the ledger stores the **score** but not what produced it. There is no input vector or hash, no artifact sha256, no input-formula
version, and no timestamp or completeness flag for the last bar. So it proves *what* score was given and *when*, but not *from which
inputs and model file*.

## Minimum proposal

1. **One additive migration, all columns nullable, append-only triggers unchanged** (owner approval needed per migration):
   `artifact_sha256` (64), `feature_set` (64, e.g. `obv_level_v1` / `obv_volume_v2`), `inputs_sha256` (64), `inputs` (JSONB, the exact
   vector as scored), `last_bar_ts` (timestamptz), `last_bar_final` (boolean or null = unknown).
2. **Writers fill them at write time, outside the frozen files.** `score_history.append_to_ledger` (`services/score_history.py:255`)
   already resolves the `MLModel` row (artifact path, version) but not the inputs. It would also read the just-written `predictions`
   row's `features` JSON and bar timestamp for the same stock and bar, and the artifact sha256, computed once per model file and cached.
   A later overwrite of `predictions` then can't erase the history, because each re-score becomes a new ledger revision. No change to
   `ml/predict.py` or any frozen file. Brain-run rows (`ledger.py:263`) leave the new columns null, because the brain stores no model identity (#385).
3. **`last_bar_final`** = true only when the scored bar's session has closed (after 15:30 IST on that session date, per the market
   calendar) at `scored_at`. Otherwise false. Null when it can't be known. This records the partial-bar risk without changing the trial's scoring.
4. **Tests:** (a) a re-score with different inputs creates revision 2 and revision 1 is unchanged; (b) UPDATE or DELETE on the new
   columns is refused; (c) `inputs_sha256` equals the sha256 of canonical JSON of `inputs`; (d) a bar scored before the session closes
   is saved with `last_bar_final = false`.
5. **Out of scope until the h05 trial ends:** making `ml/predict.py` refuse partial bars or stop overwriting. Those are frozen-file
   changes and need the owner's approval entry.

Ingestion timestamps on `candles` (to separate "earlier bar version" from "confirmed correction" in future) belong to the existing
`candle_arrivals` / `candle_corrections` tables. Recording into them is a Service 1 gap (`docs/architecture/architecture-gaps.md`), not part of this proposal.
