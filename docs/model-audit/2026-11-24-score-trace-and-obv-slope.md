# Model 2 score trace and the `obv_slope` train/serve mismatch (2026-11-24, IST)

Issues: #226 (score traceability), #272 (verify model inputs; owner criteria of 2026-11-15), #325 (score and label mismatches).
Status: READ-ONLY audit. Nothing was changed, trained, activated or deployed. No prod access. No secrets read.
Baseline: branch `review/local-work-nov12`, HEAD `ab926d9`. The local dev API container runs byte-identical copies of
`ml/features.py`, `ml/predict.py`, `ml/market_context.py`, `ml/dataset.py` (sha256 prefixes matched), so the container's results describe this branch's code.
Model inventory (ids, dates, dataset sizes) belongs to the other auditor (#267, #269-271) and is only referenced here.

## How the evidence was gathered

* Local dev copy of the database (container `swingtrademl-main-local-postgres-1`, already running; only SELECTs). It is a STALE copy:
  newest candles are 2026-09-08 UTC stamps (KEC: last bar stamped 2026-09-06 18:30 UTC = 2026-09-07 IST), predictions 2026-08-04..2026-09-06.
* Throwaway scripts ran inside the already-running dev API container (read-only DB session, rolled back) against the local copies of the artifacts.
  Scripts: `<local session scratchpad>/trace.py` (path redacted for the public repo), `trace3.py`, `cmp.py`
  (raw output: `<scratchpad>/trace_out.txt`). Nothing was written into the repo besides this file.
* Local artifacts, sha256 prefixes: model 2 `swing_classifier_v2.joblib` d3a73b09a7b6..., model 16 `swing_classifier_midcap_v2.joblib` 633259b084da...,
  model 17 `swing_classifier_smallcap_v1.joblib` 75675a4e465c.... The 2026-10-30 incident note says these match prod byte for byte; I did NOT re-verify that.

## Part 1. Score trace

### 1.1 The path from candles to the displayed number

| Step | What happens | File:line |
|---|---|---|
| Candles | newest 400 daily bars of the stock; needs at least 220 | `ml/predict.py:67-69`, `ml/dataset.py:42-69` |
| Context frames | NIFTY, sector index, VIX, breadth, loaded once | `ml/predict.py:76-79` |
| Features | `build_features(...)` builds all 53 columns, the model then picks its own list by name | `ml/predict.py:80-82`, `ml/features.py:218-369` |
| Any NaN input | stock is skipped, nothing imputed | `ml/predict.py:83-88` |
| Scale | the artifact's saved `StandardScaler` | `ml/predict.py:90` |
| Probability | `LGBMClassifier.predict_proba(...)[0,1]` (verified: estimator type LGBMClassifier, scaler StandardScaler, bundle keys `estimator, scaler, feature_names, algorithm, horizon_days, target_return`) | `ml/predict.py:91-95` |
| Brain gets it | active model named `swing_classifier` (model 2) scores EVERY stock | `brain/reader.py:460-496`, `brain/reader.py:42` |
| Opinion | probability p and the buy level stored in an Opinion; reason text "The active model ... scores this stock 76%" | `brain/fallbacks.py:117-145` |
| Decision confidence | `confidence = o.probability` | `brain/modules/m08_decide/engine.py:178` |
| Shown as score/100 | `round(confidence * 100)` | `services/idea_report.py:222-226` |

So **score/100 = round(100 x model-2 probability)**. The probability is a tree-ensemble output, so it cannot be hand-computed; it is reproduced
by loading the artifact (below). Question the model answers: "close at least +2% after 5 trading days" (`horizon_days`/`target_return` in the bundle; saved metadata
`prediction_horizon_days: 5, target_return_pct: 0.02`, `docs/brain/evidence/sector_prep/model2_saved_features_v1.json`). That is a FORWARD question.
The inputs `roc_10, roc_20, return_1d/5d/10d/20d` are PAST returns (`ml/features.py:278-279, 305-308`); they are not the forecast horizon. They also repeat each other:
`return_10d` equals `roc_10` and `return_20d` equals `roc_20` exactly (same value in the KEC table below), and `williams_r` is a straight-line copy of `stoch_k`
(identical scaled value). The model therefore has 37 named inputs but fewer distinct signals.

### 1.2 The 37 inputs (names and order verified)

Order saved in the artifact equals the order of `FEATURE_COLUMNS` filtered to model 2's names: `tests/test_sector_c56_r37.py:129-137` asserts it, and all 637 saved
prediction rows store their `features` JSON keys in exactly the artifact's order (my check: 637 of 637). Count 37 confirmed from the artifact (`n=37`).
Models 16 and 17 add `days_since_52w_high/low, streak, volatility_percentile_rank, cmf_20, relative_strength_5d/20d, nifty_volatility_20, nifty_trend_regime` (46 total; same list for both).
Model 2's 37 are exactly the 37 columns that existed in the first commit `abc9c0b` (2026-08-04 15:33 IST) and use only the stock's own candles (no index, sector, VIX or breadth).

### 1.3 KEC example (what could and could not be done)

* **Not found:** no saved KEC prediction exists anywhere I could read. Local `predictions` has 0 rows for KEC (instrument 3029); no document, issue (#217, #308, #324) or fixture contains a KEC example.
  The only KEC score on file is `stock_score_history` row 2026-10-16 = 0.2876 from `swing_classifier_smallcap_barrier:v1`, a different model, so it is NOT model 2.
  The origin of the "KEC example" in #226 is unknown to me; the owner should say which saved score (date, model version, number) is meant. Prod stored prediction and UI value were not accessed.
* **What I did instead:** replayed KEC on its newest local bar (2026-09-07 IST, close 401.9, 1247 bars, sector index NIFTY INFRA) through the exact current code and the real model-2 artifact.

Model 2 inputs for KEC, as served today (400 bars, current formula) with scaled value z = (x - mean) / scale; the last column is the value on the training basis
(full history, training-era `obv_slope`). Only input 23 differs.

| # | Input | Served value | z | Training-basis value | Source (`ml/features.py`) |
|---|---|---|---|---|---|
| 1 | sma_10_ratio | -0.034266 | -1.410 | same | 251-253 |
| 2 | sma_20_ratio | -0.056412 | -1.657 | same | 251-253 |
| 3 | sma_50_ratio | -0.132831 | -2.414 | same | 251-253 |
| 4 | sma_200_ratio | -0.292806 | -2.878 | same | 251-253 |
| 5 | ema_12_ratio | -0.037672 | -1.668 | same | 254-256 |
| 6 | ema_26_ratio | -0.074756 | -2.199 | same | 254-256 |
| 7 | sma_10_50_cross | -0.102062 | -2.292 | same | 258-259 |
| 8 | sma_50_200_cross | -0.184480 | -2.497 | same | 258, 260 |
| 9 | rsi_14 | 27.3027 | -2.107 | same | 263 (fn 77-82) |
| 10 | macd | -0.041648 | -2.490 | same | 264-266 (fn 85-92) |
| 11 | macd_signal | -0.040121 | -2.548 | same | 264, 267 |
| 12 | macd_hist | -0.001527 | -0.274 | same | 264, 268 |
| 13 | stoch_k | 5.6153 | -1.637 | same | 270-271 (fn 118-124) |
| 14 | stoch_d | 14.2289 | -1.443 | same | 270, 272 |
| 15 | williams_r | -94.3847 | -1.637 | same | 274-276 |
| 16 | roc_10 | -0.068274 | -1.554 | same | 278 |
| 17 | roc_20 | -0.155406 | -2.492 | same | 279 |
| 18 | atr_14_pct | 0.026844 | 0.662 | same | 282-283 (fn 95-100) |
| 19 | bb_position | 0.055823 | -1.534 | same | 285-288 |
| 20 | bb_width | 0.127004 | 0.457 | same | 285-289 |
| 21 | volatility_20 | 0.267568 | 0.356 | same | 291-292 |
| 22 | volume_ratio_20 | 0.642477 | -0.580 | same | 295 |
| **23** | **obv_slope** | **-2.340971** | **-0.329** | **-0.008125** | **296-300 (fn 141-142)** |
| 24 | mfi_14 | 45.4518 | -0.470 | same | 301 (fn 127-138) |
| 25 | return_1d | -0.016277 | -1.071 | same | 305 |
| 26 | return_5d | -0.035054 | -1.092 | same | 306 |
| 27 | return_10d | -0.068274 | -1.554 | same | 307 |
| 28 | return_20d | -0.155406 | -2.492 | same | 308 |
| 29 | high_20_dist | -0.141056 | -2.552 | same | 310 |
| 30 | low_20_dist | 0.005882 | -1.075 | same | 311 |
| 31 | high_52w_dist | -0.571444 | -4.729 | same | 312 |
| 32 | gap_pct | 0 | -0.163 | same | 314 |
| 33 | body_pct | 0.648780 | 0.817 | same | 315-316 |
| 34 | upper_wick_pct | 0.121951 | -0.751 | same | 317-319 |
| 35 | lower_wick_pct | 0.229268 | -0.295 | same | 317-318, 320 |
| 36 | adx_14 | 44.3845 | 2.009 | same | 333 (fn 103-115) |
| 37 | trend_strength | -44.3845 | -1.943 | same | 334 |

KEC probability from the real artifacts (same candles, different input recipes):

| Recipe | Model 2 | Model 16 | Model 17 |
|---|---|---|---|
| Served today: 400 bars, current formula (period B) | **0.7594 -> score 76** | 0.6487 | 0.1890 |
| 400 bars, old formula (what prod served 2026-08 .. 2026-10-06, period A) | 0.7963 -> 80 | 0.6425 | 0.1694 |
| Training basis: full history, old formula | **0.8128 -> 81** | 0.7084 | 0.1654 |
| Full history, current formula | 0.7594 | 0.6487 | 0.1890 |

(Row 4 equals row 1 because every other input, and the new `obv_slope`, do not depend on how many bars are loaded.) So for KEC the served score is 76 where the model
as trained would say 81. KEC also has `high_52w_dist` z = -4.73 (far outside the training range) so the number leans on a tail of the training data.

### 1.4 Reproducing saved scores

* **Stored features to stored probability (exact):** for all 637 saved model-2 prediction rows, `scaler.transform` + `predict_proba` on the stored `features` JSON gives the stored
  `probability` with maximum absolute difference **0.0**. So the model step and the stored inputs are consistent, and the 37 names/order are as saved.
* **Candles to stored features (mostly NOT reproducible locally):** on a random sample of 200 rows, rebuilding the features from the local candles (old formula, 400 bars, bar-date cut)
  reproduced the 36 non-OBV inputs in only 29 rows and the full vector (and probability to 1e-9) in only 13 rows. In the other rows many inputs differ (e.g. rsi up to 8 points),
  which means the local candle history is not what the scan saw (revised or backfilled bars, a different bar count at that time, or a not-yet-closed last bar). I cannot tell which from
  local data. `ml/predict.py` has no check that the newest bar is a completed day (`load_candles` takes whatever is stored), so a partial last bar is possible but NOT proven.
  The 13 exact matches show the old recipe is what produced the saved August-September rows (period A), as expected.
* **Replay of a score the UI showed:** not possible locally (see 1.3).
* The brain stores `confidence` but not which model produced it for decisions (`2026-10-29-score-provenance-note.md` section 2); not re-verified here.

## Part 2. `obv_slope` training versus serving

### 2.1 The two definitions

| | Definition | File:line | In force |
|---|---|---|---|
| Training / old | `obv.diff(10) / obv.rolling(20).mean().abs().replace(0, nan)`: 10-day OBV change over the 20-day mean OBV LEVEL | `git show abc9c0b:backend/src/swing_trade_ml/ml/features.py` line 182; same expression at `7da460c:...` 255, `2bdb681:...` 298, `fcaef35~1:...` 298; reproduced in `brain/lanes/h05_features.py:49-53` | 2026-08-04 15:33 IST to 2026-10-05 21:28 IST |
| Serving / new | `obv.diff(10) / volume.rolling(20).mean().replace(0, nan)`: over the 20-day mean daily VOLUME | `ml/features.py:296-300` | from commit `fcaef35` (2026-10-05 21:28:16 IST); first confirmed deploy containing it `f69134a`, 2026-10-06 20:29 IST (per `2026-10-30-obv-slope-incident.md`; deploy times came from GitHub Actions and are NOT re-verified) |

History proof: `git log -S"obv.diff(10)" -- backend/src/swing_trade_ml/ml/features.py` returns only `abc9c0b` (introduced) and `fcaef35` (changed). Nothing else touched the line.
Serving window: `predict.py` has used `limit=400` since `abc9c0b` (`git log -S"limit=400" -- ml/predict.py`). Training reads the full stored history (`ml/dataset.py:112` `load_candles(db, inst.id, interval)` with no limit, then `:120` `build_features`).
So before 2026-10-05 the formula matched but the window did not (period A: OBV level depends on how far back the cumulative sum starts); since then neither matches (period B).

### 2.2 Which artifacts were trained under which definition

| Model | `trained_at` (UTC, local registry) | Feature list | Code version at that time | `obv_slope` used in training |
|---|---|---|---|---|
| 2 `swing_classifier` v2 | 2026-08-05 09:32 | 37 | `abc9c0b` | old (level denominator), full history |
| 16 `swing_classifier_midcap` v2 | 2026-08-12 15:12 | 46 | after `7da460c` (2026-08-06) | old, full history |
| 17 `swing_classifier_smallcap` v1 | 2026-08-20 18:34 | 46 | same | old, full history |

All three predate `fcaef35` by seven weeks or more, so all three expect the old definition. Direct proof from the artifacts themselves: the saved scaler for `obv_slope`
has mean/scale 0.0158 / 7.169 (model 2), 0.0850 / 2.664 (model 16), 0.3040 / 46.48 (model 17), i.e. a spread that differs a lot between models (the old formula divides by an OBV level, which can be close to zero); the
training-basis values on the newest local bars have a standard deviation of only 0.129 (table below), so the saved scale mostly reflects rare extreme rows. The earlier lane check (`brain/lanes/h05_parity.py`) shows every other input's saved scaler
is reproduced from each model's own training data and `obv_slope` only with the old formula. I did not repeat the scaler reproduction (needs the training data and the h05 CLI).

### 2.3 Size of the difference (320 stocks, newest local bar of each)

| Quantity | Result |
|---|---|
| `obv_slope` served (new, 400 bars) vs training basis (old, full) | rank correlation 0.910; median absolute gap 2.63; served std 4.12 vs training-basis std 0.129 (the two are on different scales; z-scores differ by whole units) |
| Old formula, 400 bars vs old, full history (period A gap) | median absolute gap 0.035; rank correlation 0.916 |

Score movement versus the training-basis score (303 stocks that had every input):

| Model | Served today (period B): mean / p95 / max abs change in probability | Rank corr | Top-5 overlap | Stocks crossing the 0.60 buy level | Period A for comparison: mean abs change / rank corr / crossings |
|---|---|---|---|---|---|
| 2 | 0.057 / 0.147 / 0.252 | 0.811 | 3 of 5 | 42 | 0.018 / 0.962 / 13 |
| 16 | 0.079 / 0.171 / 0.227 | 0.874 | 2 of 5 | 69 | 0.028 / 0.944 / 26 |
| 17 | 0.039 / 0.097 / 0.174 | 0.933 | 4 of 5 | 3 | 0.012 / 0.981 / 0 |

Mean served probability also shifts: model 16 averages 0.674 served vs 0.608 on the training basis (the served recipe is more generous, +6.6 points on average); model 2 is 0.486 vs 0.505.
The 0.60 line is the default buy level (`settings.ML_MIN_CONFIDENCE`, used at `brain/reader.py:497`); I used 0.60 as in the earlier notes, not re-read from prod settings.
These numbers are on 2026-09 data replayed with today's code, not a recorded trial score. They agree in direction with the 2026-10-30 note (one-day replay: model-2 rank correlation 0.687 in period B); the size differs because that note used one signal day (2026-09-07) and I used each stock's newest bar. Treat both as indicative.

### 2.4 Other inputs: any train/serve skew?

* **Definition changes** since training-era code: I executed `abc9c0b`'s `build_features` and `7da460c`'s on KEC's real candles and compared to the current builder: model 2's 37 inputs differ ONLY in `obv_slope`;
  model 16/17's 46 inputs differ ONLY in `obv_slope`. This agrees with the pinned test `tests/test_sector_c56_r37.py:149-163` (snapshot `d2f723d`) and `tests/test_h05_historical_features.py`.
  Caveat: the context frames in my check reused KEC's own candles, so the 9 context inputs of models 16/17 are checked for formula identity only, not for data identity.
* **Window-length skew** (400 bars served vs full history trained): across the newest bar of 320 stocks, every other input differs by at most about 3e-9 (relative; largest: `bb_position` 3.3e-9, `ema_26_ratio` 1.6e-9). No skew from window length.
  `days_since_52w_*`, `high_52w_dist`, `volatility_percentile_rank`, `vix_percentile_rank` (252-bar windows) are exactly equal in the 400-bar window.
* **Not checked:** data skew in the context inputs between training time and now (training read index/sector/VIX/breadth as they were stored in August; commit `2145a20` (2026-10-13, "stop breadth counting missing stocks as bearish") may have changed how breadth is counted; I did not check which file or by how much, and breadth is not an input of any of the three models (it is in the 53 but not in the 37/46 lists)). Candle revisions between training and serving. Sector map changes (`ml/sector_map.py` unmapped-symbol warnings appear for index/instrument names such as BHARTIARTL, ASIANPAINT: sector context for those uses a fallback; not examined).
* **Not an input problem but related (#325 / #226):** the 5-day +2% score is shown as a 15-day brain score; see `2026-10-29-score-provenance-note.md` and #341. Not re-audited.

## Part 3. Candidate remedies (none is to be applied now; the h05 trial is sealed)

Frozen files per `backend/tests/trial_freeze.json` / `tests/trial_freeze.py:12-38`: `ml/features.py`, `ml/predict.py`, `ml/market_context.py`, `ml/real_question.py`, `ml/calibrated_model.py`, `ml/sector_map.py`,
`brain/reader.py`, `brain/fallbacks.py`, `brain/opinions.py`, `brain/service.py` and the rest of the brain core, everything under `brain/modules` and `strategies`, plus `services/engine.py, risk.py, limits.py, deployable.py, exit_policy.py, avoid.py`.
NOT frozen: `ml/dataset.py`, `ml/train.py`, `ml/registry.py`, `brain/lanes/*`, tests, docs. Any change to a frozen file needs the owner's approval entry (`scripts/approve_trial_change.py`) and, if it changes picks, a new trial version.

| # | Remedy | Fixes | Trade-offs | Frozen files touched | Approvals needed |
|---|---|---|---|---|---|
| R1 | Serve the old definition again for models 2/16/17 (restore the level formula in the served path, ideally with full history or a window-safe equivalent) | Restores the scores the models were trained on | Needs more than 400 bars for consistency (period A still had a window skew); undoes the intent of `fcaef35` (brain snapshots consistent with each other); changes every score during the trial if done now | `ml/features.py` (formula) and possibly `ml/predict.py` (window), maybe `brain/reader.py` | Owner approval on the freeze manifest; new version of the trial; needs a test (parity) |
| R2 | Retrain models 2/16/17 on the new definition as NEW model versions (separate names/versions, not activated) | Train and serve agree; no frozen code change | Retraining changes the models' behaviour (different dataset age, features), so it needs the full old-vs-new comparison; model activation is owner-only; training on today's data can leak if cut-off dates are not kept | None for training (`ml/train.py`, `ml/dataset.py` are not frozen); activation would touch the registry (DB), not frozen files | Owner approval for training evidence and for activation (AGENTS.md: "Require approval for schema migrations and model activation") |
| R3 | Separately versioned candidate pair per #272 criteria: keep old-input baseline (the h05 lane already scores the old formula, `brain/lanes/h05_features.py`) and add a new-input candidate model; compare under an approved protocol; decide after the trial | Exactly the owner's 2026-11-15 criteria; no effect on the running trial | Slowest; needs a protocol and enough days of data; two scores to explain | None if built inside `brain/lanes/` and a new training path | Protocol sign-off; owner decision after the trial |
| R4 | Leave as is and document: the sealed trial measures "the system as deployed", with period-B inputs | Zero risk to the trial | Scores keep disagreeing with what the models learned (see 2.3); every explanation shown to users must say so | None | None (already the 2026-10-30 position) |
| R5 | Add a parity check only (read-only): per artifact report training-time vs scoring-time `obv_slope` definition and flag any mismatch (#272 test criterion) | Makes the mismatch visible permanently, and catches the same mistake for future artifacts | Needs the artifact to carry its feature-formula identity (today the bundle stores only names, so a formula id or a pinned hash would have to be added at training time) | None if it lives in `brain/lanes/` or `tests/`; saving formula identity inside the artifact would touch `ml/train.py`/registry (not frozen) | Owner approval for the test; no model activation |

Suggested order, for the owner to decide: R4 now, R5 as a test-only change, R3 after the trial, then R1 vs R2 on the evidence R3 produces.

## Gaps and not verified

1. No saved KEC prediction or prod UI value was available; KEC was replayed from the stale local copy (bar 2026-09-07 IST). The KEC in #226 is not identified.
2. Prod stored predictions, the prod registry and prod artifacts were not accessed; "local artifacts equal prod" rests on the 2026-10-30 note.
3. Candle-to-stored-feature reproduction worked for 13 of 200 sampled rows only; the reason (revised bars, bar count, partial last bar) is unknown.
4. Deploy dates for period B come from the incident note (GitHub Actions), not from the server.
5. Scaler-versus-training-data reproduction (h05 parity) was not repeated; training datasets are not stored in the repo.
6. The numbers in 2.3 use one recent bar per stock on 2026-09 data and a 0.60 buy level from earlier notes, not a recorded trial score.
7. No completed-candle check, adjusted-price or split check was performed on the inputs (#272 asks for completed candles and point-in-time features); only the formula and window checks above were done.
8. Context inputs (index, sector, VIX, breadth) of models 16/17 were not checked for data (only formula) skew.
9. Test suite not run (hangs without Postgres; hard rule).

## Exit-condition check

* **#226** (verify artifact input names and order; trace KEC from stored prediction and model version through displayed score; record unavailable evidence; distinguish forecast horizon from past-return inputs):
  names/order verified (1.2) = met; chain to displayed score documented with file:line (1.1) = met; KEC from a STORED prediction = NOT met (none exists locally; unavailable evidence recorded in 1.3 and the gaps list);
  horizon vs past-return distinction recorded (1.1) = met. A different saved example (637 model-2 rows) reproduces exactly from stored features, which shows the method works. Cannot be closed until the owner names the KEC score or prod values are read with approval.
* **#272** (candles, point-in-time features, missing values, training/scoring parity per artifact; verify `obv_slope` against code and evidence; record baseline SHA, sources, results, gaps):
  obv_slope verified against code, git history and artifacts (Part 2) = met; parity per artifact for the other inputs = met for definitions and window (2.4), NOT met for context data and completed candles;
  baseline SHA `ab926d9` recorded; gaps recorded. The owner's after-trial criteria (old baseline vs separately versioned candidate; parity check test) are future work and not started (R3, R5).
* **#325** (reconcile the same prediction across API, UI and reports; regression examples): not in scope here. Relevant finding: for the same stock the served score and the training-basis score differ by up to 0.25 (mean 0.057 for model 2), so any reconciliation must name which recipe produced the number. The 5-day-score-versus-15-day-plan mismatch is tracked in #341.

## Addendum 2026-11-24: input reconstruction investigation

Question: why did rebuilding model-2 inputs from local candles match only 13 of 200 sampled saved predictions? Read-only; SELECT only; scripts in
`<local session scratchpad>` (path redacted for the public repo) (`recon.py`, `recon2.py`, `recon3.py`; outputs `recon.json`, `recon2.json`).
All 637 saved model-2 rows (13 scan dates, 49 stocks each) were classified, not a sample. Correction to the text above: the `load_candles(... limit=400)` call is `ml/predict.py:77` (not 67-69).

**Method.** For every row: find the candle with the same `ts`; take the 400 bars ending there; rebuild the 37 inputs with the feature code that was live when the rows were written
(`git show abc9c0b:backend/src/swing_trade_ml/ml/features.py`, copy in the scratchpad; model 2's 37 inputs are identical in `7da460c`, shown earlier); compare each input with the stored `features` JSON (tolerance 1e-6 relative).
Then test shifted bars (D-1, D+1, D+-2) and test substituting the stored last-bar close (`price_at_prediction`) and the volume implied by the stored `volume_ratio_20` into the final candle.

**Limitation (evidence that does not exist locally).** Local `candle_corrections`, `candle_arrivals` and `corporate_actions` all have 0 rows; `candles` has no ingestion timestamp; `predictions` has no created-at column.
All local DBs are the same snapshot (newest daily candle 2026-09-08 18:30 UTC); no fresher approved non-prod copy exists, and prod and backups were not used. So "the bar was corrected later" versus "the bar was not yet final at scan time" cannot be separated by timestamps, only by the numbers below.

### Result (637 rows)

| Bucket | Rows | Dates (ts, UTC stamp) | Evidence |
|---|---|---|---|
| Exact reproduction (all 37 inputs, and the probability to 1e-9) | 49 | 2026-08-20 | stored close equals final close and implied volume equals final volume in 49 of 49 |
| (d) Last bar was not the final bar when scored | 539 | 2026-08-04, 08-05, 08-24, 08-25, 08-26, 08-27, 08-30, 08-31, 09-01, 09-02, 09-03 | see below |
| (c) Feature-code difference (new `obv_slope`), everything else exact | 49 | 2026-09-06 | stored `obv_slope` equals the NEW formula (400 bars) in 49 of 49 (max diff 0); old formula 0 of 49 |
| (a) Stale or missing source data (bar absent, or fewer than 220 bars) | 0 | | every row has its bar; the window is 400 bars in all 637 (at least 1239 bars to date) |
| (b) Candle corrections, splits, bonus in the window | not detectable | | the three tables are empty; for the 539 rows the earlier bars match the DB exactly (below), so no change to earlier bars was seen |
| (e) Unexplained | 0 for the inputs that could be tested (see caveat) | | |

**Bucket (d), 539 rows.** In all 539: (1) the stored `price_at_prediction` lies inside the final candle's [low, high] (539 of 539) but equals the final close in only 26 rows (median gap 0.27%);
(2) the volume implied by the stored `volume_ratio_20` is below the final candle's volume in 539 of 539 (median 95.7% of it), and a day's volume can only grow;
(3) the stored `return_1d` implies a previous close equal to the DB's previous close (exact in all 588 mismatching rows, buckets d and c), so bars before the last one match;
(4) shifted bars never match (D-1, D+1, D+-2: 0 matches), so the bar is the right one and IST stamping (18:30 UTC = next IST date) is aligned;
(5) after replacing only the last bar's close and volume with the stored values (and widening high/low to include the stored close), the 21 inputs that do not depend on the last bar's own high/low
(sma/ema ratios, crosses, rsi, macd x3, roc x2, return x4, volatility_20, volume_ratio_20, old-formula obv_slope) reproduce exactly in 539 of 539 rows.
That is the signature of a bar that was still partial (intraday, or an earlier snapshot) at scan time and was completed later. It fits `ml/predict.py:77`, which reads whatever newest bar is stored (no completed-bar check).
What cannot be told from local data: whether the scan read a live intraday bar or an earlier stored version of the bar (no timestamps).
Size before substitution, median / max absolute difference over these 539 rows: return_1d 0.0029 / 0.033; rsi_14 0.99 / 15.4 points; stoch_k 4.1 / 51 points; bb_position 0.034 / 0.55;
volume_ratio_20 0.034 / 3.5; mfi_14 0.14 / 14.7; obv_slope (old formula) 0.0022 / 47; adx_14 0.16 / 2.7 (79 rows); upper_wick_pct 0.096 / 0.61 (283 rows).
Inputs that depend on the last bar's own high and low (stoch_k/d, williams_r, bb_*, mfi_14, atr, wicks, body, high/low distances, adx) could not be tested because the partial bar's high and low are unknown; for those the statement is "consistent", not "proven".

**Bucket (c), 49 rows (2026-09-06).** Every input except `obv_slope` reproduces exactly (including close and volume); `obv_slope` differs by 2.1 to 3.4 on the three examples and equals the new formula exactly.
These are the newest bar of the local snapshot. `_upsert_prediction` overwrites `features` and `probability` on conflict (`ml/predict.py:192-198`), so these rows were evidently re-scored by code containing `fcaef35`
(2026-10-05 or later) on the same bar, replacing what was stored. Which run did it is not recorded. Consequence for traceability: a saved prediction row is NOT immutable; its inputs can be replaced by a later scan of the same bar.

**Worked examples.**
1. ADANIENT, ts 2026-08-04: stored price 3045.0 vs final close 3050.0 (final range 3037.3-3085.9); implied volume 860,325 vs final 870,914; 33 inputs differ against the final bar (largest stoch_k 2.08, williams_r 2.08);
   after substituting close and volume all 21 testable inputs match. Bucket (d).
2. HDFCBANK, ts 2026-08-25: stored 727.6 vs final 727.2 (range 724.15-731.0); implied volume 20,351,781 vs final 21,156,463; 33 inputs differ (stoch_k 1.78); after substitution all match. Bucket (d).
3. ICICIBANK, ts 2026-08-20: stored price 1420.0 = final close, volume equal, nothing differs. Exact reproduction. (ONGC, ts 2026-09-06: stored obv_slope differs from the old-formula rebuild by 2.13 and equals the new formula; bucket (c).)

**Answer.** 13 of 200 was 49 of 637 (7.7%): only the 2026-08-20 scan used a final bar and the old code. 85% of rows (539 of 637) were scored on a bar that was not final (bucket d); 8% (49 of 637) were later overwritten under the new `obv_slope` code (bucket c).
No row failed because of missing data, a one-day shift or time-zone stamping. Candle corrections and corporate actions could not be tested (no records locally); earlier bars matched the DB everywhere.
This explains the "unknown reason" in section 1.4 for the tested inputs; the score trace itself is unchanged (stored inputs reproduce stored probabilities exactly, 637 of 637).

**Not verified:** whether the partial bar came from a live intraday read or an earlier stored version; inputs that depend on the partial bar's high and low; the date and run that rewrote the 2026-09-06 rows; anything in prod (saved prod rows may differ).
Exit condition for #226 stays unmet (no saved KEC prediction).
