# h05: TMCV "invalid_features" and the obv_slope difference (investigation note)

Prepared: 2026-11-07 (read-only; nothing in h05 code, protocol, hash, tables, sealed records or production models was changed).
Evidence read: h05 code on `main`, local Docker Postgres (SELECT only, read-only transaction, test-default login, database `swing_trade_ml`),
the committed incident notes, and one read of prod `GET /api/v1/research/h05/report` (no key printed or stored).

## 1. TMCV "not scored: invalid_features" (5 of 5 sessions, 2-6 Nov 2026)

**Verdict: expected behaviour under the accepted protocol, not a data bug. Nothing must change.**

Root cause (verified):
- TMCV is the post-demerger Tata Motors commercial-vehicle line. Local data: 204 daily bars, 2025-11-12 to 2026-09-07 (the local data ends 2026-09-08),
  no zero or missing volume, no calendar gaps. It is in the large group (model 2, 37 inputs).
- The h05 scoring rule (`h05_service._score_stock`): a stock is "short_history" below `MIN_BARS = 220` bars; otherwise
  `h05_features.score_training_basis` returns None when ANY input of that model is NaN on the newest bar, reported as `invalid_features`.
  Nothing is imputed (as in training and in production).
- The exact input: `high_52w_dist = close / high.rolling(252).max() - 1` (`ml/features.py:312`) has no `min_periods`, so it is NaN until a stock has
  **252** bars. On TMCV's local frame it is the only model-2 input that is NaN on the newest bar; every other input is finite from bar 200 at the latest
  (`sma_200_ratio`, `sma_50_200_cross` = bar 200).
- Bars on the prod signal days: 204 on 2026-09-07 plus the sessions since. Upper bound with no holidays: 244 (2 Nov) to 248 (6 Nov); with the usual
  holidays in that stretch about 241 to 245. Always between 220 and 251, so `short_history` no longer applies (the early dry run on 7 Sep said
  `short_history`, 204 of 220) and `high_52w_dist` is still NaN. Prod report confirms: TMCV is the only not-scored stock in the large group
  (`not_scored_events: TMCV, invalid_features, 5 days`).
- Sector mapping: `sector_map.unmapped symbol=TMCV` (falls back to NIFTY 50). Model 2 has no sector inputs, so it plays no part here.

Impact on the 5D evaluation: one of 52 large stocks is absent from the daily candidate list until it reaches 252 bars (estimate: about 17-18 Nov 2026;
exact day depends on the NSE holiday calendar, confirm from the next daily report). Absence is recorded per day, the group's baseline is computed on the
same eligible stocks, and the group still has 51 scored stocks (protocol minimum is 10 eligible per day). When TMCV becomes scorable it enters the
frozen universe's ranking; it was not in the training data (`trained_on_symbol` is recorded as False), which h05 already reports. Its history starts at
listing, so its "52-week" window is "since listing", not a data error.

Cosmetic mismatch, no action: the protocol's `MIN_BARS = 220` is lower than the real need (252 for `high_52w_dist`), so stocks with 220-251 bars show
`invalid_features` instead of `short_history`. Changing the constant would change the protocol hash and needs an amendment; it is not needed.

## 2. obv_slope (train/serve difference, known incident)

How it is computed (code and the committed incident note):
- **Training, models 2/16/17 (trained Aug 2026):** `obv.diff(10) / abs(obv.rolling(20).mean())`, the OBV LEVEL in the denominator, on the full stored
  history. (The value depends on how much history is loaded.)
- **Serving, production since the deploy of 2026-10-06 20:29 IST (`f69134a`, first confirmed deploy containing `fcaef35`):**
  `obv.diff(10) / volume.rolling(20).mean()` (`ml/features.py:300`) on the newest 400 bars (`ml/predict.py`, `limit=400`). Before that (period A) the old
  formula on 400 bars.
- **h05 `training_basis` score (PRIMARY, used to rank and select):** the saved model on training-compatible inputs, old obv_slope formula, full history.
  **h05 `production_path` score (DIAGNOSTIC only):** what production serves today. Selection and verdicts use the primary score only
  (`h05_service`: ranking uses `r["score"]`; `score_production_path` is stored and shown beside it).

Parity numbers from the prod report (run 1): `training_basis` is OK for all three groups (large: max mean shift 0.032 sd, spread ratio 0.982-1.013;
mid and small 0.0 / 1.0). `production_path` fails on `obv_slope` only: large spread ratio 0.522 and mean shift 0.077 sd; mid 1.526 and 0.401; small 0.102
and 0.018. The committed one-day replay (7 Sep, not a trial number): rank correlation production vs training inputs, period B: large 0.687, mid 0.868,
small 0.933; top-5 overlap 3, 4, 4 of 5.

Impact on the 5D verdict: **the primary score is unaffected**, so the h05 verdict is a clean test of "the saved models with training-compatible
inputs" and the report already says so (`scoring_label`). It is NOT a test of what production ships. Two consequences:
- An h05 PASS does not by itself describe the live system. In production the large group's top-5 would differ by about 2 of 5 stocks on the one
  replayed day. Do not quote an h05 PASS as production performance.
- A FAIL or INCONCLUSIVE is not caused by obv_slope.
The sealed 15-day trial and the v1 path measure the system as deployed (period B). They are not recomputed or relabelled.

Nothing must change before the 5D evaluation can be trusted. Recorded scores stay as stored.

## Owner decisions after the evaluation (not before)

1. Whether to fix the serving difference and when.
2. Which fix: serve the old definition for models 2/16/17 (needs full history or a 400-bar-safe equivalent), or retrain on the new definition; either is a new
   version with its own evidence.
3. Whether to confirm, on the server, the exact commit running from 2026-10-06 (this cannot be checked from here).
4. If h05 passes: that production serving is reconciled with the training inputs BEFORE any h05 result is used to justify enabling anything.
