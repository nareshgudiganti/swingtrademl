# Pre-registration: #219 5D large-cap research run (R4 envelope)

Written and pushed **before any training or outcome was looked at** (2026-11-25, IST). Experiment id `r4-219-5d-largecap-v1`.
Authority: owner-approved R4 research envelope, 2026-11-25 00:57 IST (sign-off record of `2026-11-14-5d-paper-trial-protocol-v1.md`, PR #502).
Nothing is registered, activated, promoted or deployed. No database is written. All results on the fixed 52-stock list are
**selection-biased exploratory evidence**.

## Fingerprints (machine copy: `2026-11-25-219-fingerprints.json`)

| Item | Value |
|---|---|
| Code commit | `6747f9c4` (branch `research/219-5d-largecap`), files `brain/lanes/r4_5d.py`, `brain/lanes/r4_5d_run.py` |
| Code sha256 (LF) | r4_5d.py `954f024e5e0da52f…`, r4_5d_run.py `0ccc096e8d3df963…` |
| Feature-set version | `r4-fs53-obvvol-v1`, fingerprint `efacbaa3192fd049…` |
| Data snapshot sha256 | `d95091a114f6210d…` (local dev DB `swing_trade_ml`, newest session 2026-09-07 IST; all local DBs are one snapshot, newest daily candle stamp 2026-09-08 18:30 UTC) |
| Universe sha256 | `811261fcf37e91f2…` (52 symbols, `r4_5d.UNIVERSE`) |
| 5D rule | `hz-rules-v1`, sha256 `3dab34cd06b5756b…` |
| C1 config sha256 | `91d67ff05f5967c2…` |
| C2 config sha256 | `2a1c9d20bdf219b6…` |
| C3 config sha256 | `1ce9f83ba6a28642…` |

The runner refuses to start if any fingerprint above differs from the JSON file (`r4_5d_run run --prereg`).

## Candidates (3 of the 6 allowed across #219-#222)

| Id | What | Training |
|---|---|---|
| C1 | Model 2 as served: `swing_classifier` v2 (sha256 `d3a73b09…`), its own 37 inputs from today's builder (production `obv_slope` since 2026-10-06) | none (evaluation reference) |
| C2 | LightGBM, model 2's own hyperparameters (400 trees, lr 0.05, depth 6, 31 leaves, min_child 50, balanced, seed 42), determinism pinned (`deterministic`, row-wise, 4 threads), StandardScaler | walk-forward refit each run |
| C3 | Logistic regression (C 1.0, L2, lbfgs, 2000 iterations, balanced, seed 42), StandardScaler | walk-forward refit each run |

No tuning. No other candidate is tried in this run. Momentum five is a comparison, not a candidate.

**Feature set `r4-fs53-obvvol-v1`**: today's 53 inputs (names pinned in code) built by the frozen `ml/features.py` (imported, never edited),
with `obv_slope` recomputed in research code as `obv.diff(10) / volume.rolling(20).mean()` (the corrected, window-independent formula).
Models 2/16/17 were trained on the old OBV-level formula, so this is a separate version, never a fix to model 2.

## Label, trade, costs (signed spec, unchanged)

* Model target (H-2b): close of market session 5 >= signal close x 1.02; missing session-5 candle = no label.
* Reference trade (H-2): `h05_rules.simulate_trade`, group large: entry at session-1 open, +2% / −4% from the entry fill, stop first, both-levels candle = stop, gaps at the open, else session-5 close; session 6 never read.
* Costs: 10 bps slippage per side, taxes 11.9 / 10.4 bps, Rs 15.93 per sell, Rs 1,00,000 reference order (~44 bps round trip). Stress (+30 bps per side, charges x2) reported only.

## Eligibility, selection, verdicts

* One common scored pool for every candidate and comparison: in the 52, candle on the signal session, >= 220 bars, all 53 inputs finite.
* Top 5 by score, ties A-Z; repeat rule `h05_rules.repeat_blocked`, memory restarts each run.
* Matured day: >= 10 scored, >= 1 counted pick finished, pool finished. UNRESOLVED rows leave both sides.
* Per 60-session run: SELECTION (picks minus every scored stock, with the endpoint-label veto) and ECONOMIC (picks' own net), 90% block range (blocks 5, 2000 draws, seed 7) via `h05_verdict.run_decision`; >20% unresolved counted picks = INCONCLUSIVE.
* Combined per verdict: >= 2 runs PASS, none FAIL, pooled range wholly above 0 = PASS; pooled range wholly below 0 or >= 2 runs FAIL = FAIL; else INCONCLUSIVE.

## Windows (out-of-sample only)

| Window | Role | Definition |
|---|---|---|
| W_M2 | **Primary**, all candidates | From the session after model 2's last training row (2025-10-10 IST) + 5 + 5 sessions; 3 full runs of 60 (the signed three-run rule as written). Model 2's held-out 20% lies here: its fitting never saw it, but its metrics were viewed in August, so C1 is "held out, not blind" |
| W_FULL | Secondary, C2/C3 and comparisons | From the first session on or after 2024-01-01; every full run of 60. C1 is in-sample here (trained on rows to 2025-10-10) and its W_FULL figures are reported as contaminated, never as evidence |

C2/C3 are refit at each run start on every labelled row with signal index <= run start − 5 − 5 − 1 (purge + embargo), expanding window. Sessions after the last full run are reported, never judged.

Comparisons (shown, never decide): every scored stock, momentum five (20-session return, 21 closes, >20% unexplained overnight gap not ranked; `corporate_actions` is empty locally), C1, random five (200 draws, seed 7, pools sorted by symbol). Paired daily differences C2/C3 minus momentum and minus C1 with block ranges.

## Lessons from fd-protocol-v1 (FAILED, 2026-10-26) applied here

fd_h5 failed both parts (skill 10 of 21 folds, −0.37% a trade; AUC ~0.50-0.57). It mixed the endpoint label with a different trade rule (trailing stop, confidence exits), used today's 49-stock list, and judged 28-day folds. This run uses the signed exit rule, judges by run with block ranges, pins one common pool, retrains with purge + embargo, and fixes everything before training. It still uses a survivor list (stated) and the same +2%/−4% structure, whose after-cost break-even hit rate is about 73%. **A FAIL or INCONCLUSIVE is an acceptable, reportable outcome; no re-run or tuning follows from it.**

## Acceptance checks for the results doc

1. A rerun on the same snapshot gives an identical `metrics_sha256`.
2. Out-of-sample only (purge/embargo test; C1 judged only on W_M2).
3. After costs; stress reported.
4. SELECTION / ECONOMIC per run and combined, with ranges, vs every scored stock, momentum five and C1.
5. Sample sizes (days, picks, pool sizes, unresolved), limitations.

Artifacts (joblib + model card per fit) go to a gitignored local folder and are not committed.
