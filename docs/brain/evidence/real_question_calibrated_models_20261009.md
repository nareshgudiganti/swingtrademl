# The real-question models, calibrated: evidence and how to switch them on (2026-10-09)

Plain-English summary first, numbers after. Everything here was measured on the local
development database (candles up to 2026-09-08). Nothing has been deployed, nothing has been
copied to production, and **the switch is OFF by default**.

## The short version

- Today every production model is asked "will this stock rise 2% within 5 days?". The app does not
  trade that. It trades "+8% before -4%, within 15 trading days".
- We trained models on the real question (three of them: large, mid and small caps) and added a
  "calibration" step, so a score of 0.40 now means "about 4 in 10 of these really hit the target
  first", instead of an inflated number.
- **It works better than the old models, but the edge is modest and not steady.** On the held-out
  Nov 2025 to Aug 2026 window the mid- and small-cap calibrated scores were honest and useful.
  The large-cap one is mostly flat and almost never says "buy".
- Switching it on in paper is one setting (`ML_REAL_QUESTION_SUFFIX=_barrier_cal`). Removing the
  setting is the rollback. Orders, sizing, stops and limits are not touched.

## What changed in the code

| Piece | What it does |
|---|---|
| `ml/real_question.py` (new) | The one place that knows whether the switch is on: picks the model name, the buy bar and the weakness line. |
| `core/config.py` | `ML_REAL_QUESTION_SUFFIX` (empty = off), `ML_REAL_QUESTION_MIN_CONFIDENCE` (0.40), `ML_REAL_QUESTION_EXIT_CONFIDENCE` (0.10). The last two are only read while the suffix is set. |
| `strategies/ml_swing.py`, `ml/predict.py` | Look up `<model_name><suffix>` instead of `<model_name>` when the switch is on. The strategy rows are not edited. |
| `services/exit_policy.py`, `execution.py`, `score_history.py` | Use the same buy bar / weakness line for alerts and the Strong / Easing / Weak labels, so the screens match the bot. A per-strategy `exit_confidence` override still wins. |
| `cli.py` | `swingtrade train` gained `--symbols` and `--symbols-from-model` (so the mid/small tier stock lists can be reproduced). `--calibrate` came with the earlier commit. |
| Tests | `backend/tests/test_real_question_switch.py` (off = no change, on = right model and bars, missing model = no signal, off again = restored, BUY levels still -4% / +8%), plus the earlier `test_real_question_label.py`. |

Safety rules built in: if the switch is on but the calibrated model does not exist, the strategy
produces **no signal** (it never quietly falls back to the old model). The BUY stop and target are
still computed from `ML_STOP_RETURN_PCT` / `ML_TARGET_RETURN_PCT` exactly as before. Open
positions keep the levels they were bought with. The brain's own model lookup is not changed.

## How the models were trained

Trained under new names, status TRAINED (not active), so no existing model changed:
`swing_classifier_barrier_cal`, `swing_classifier_midcap_barrier_cal`,
`swing_classifier_smallcap_barrier_cal` (local model ids 33, 34, 35). Same stock lists as the
earlier raw barrier models (51 / 150 / 104 stocks). Label: +8% reached before -4%, within 15
trading days (same-day touch of both counts as the stop; no result by day 15 counts as a miss).
The first 75% of training dates fit the model; the later 25% teach the calibration map; the
test window comes after both and is purged against label overlap. Test window for all tables:
**2025-11-02 to 2026-08-16**. 5-fold walk-forward was also run for each model.

## Is the stated confidence honest now? (reliability table, held-out window)

"Stated" = the score the model gives. "Really hit" = the share that actually reached +8% before -4%.

**Large caps** (9,551 stock-days; real hit rate overall 15.8%)

| Stated score | Raw model: n, really hit | Calibrated: n, really hit |
|---|---|---|
| under 0.30 | 3,961, 13.0% | 9,368, 15.3% |
| 0.30 to 0.40 | 1,765, 13.9% | 144, 39.6% |
| 0.40 to 0.50 | 1,493, 15.9% | 17, 41.2% |
| 0.50 to 0.60 | 1,131, 17.1% | 1 |
| 0.60 to 0.70 | 719, 18.4% | 1 |
| 0.70 to 0.80 | 464, 21.6% | 2 |
| 0.80 and up | 408, 40.9% | 18, 38.9% |

**Mid caps** (29,236 stock-days; real hit rate overall 23.3%)

| Stated score | Raw model: n, really hit | Calibrated: n, really hit |
|---|---|---|
| under 0.30 | 6,306, 18.5% | 22,192, 19.2% |
| 0.30 to 0.40 | 5,766, 21.3% | 5,345, 31.6% |
| 0.40 to 0.50 | 6,110, 21.4% | 1,642, 49.2% |
| 0.50 to 0.60 | 4,752, 23.0% | 57, 70.2% |
| 0.60 to 0.70 | 3,001, 24.1% | 0 |
| 0.70 to 0.80 | 1,613, 29.9% | 0 |
| 0.80 and up | 1,688, 47.9% | 0 |

**Small caps** (20,157 stock-days; real hit rate overall 26.7%)

| Stated score | Raw model: n, really hit | Calibrated: n, really hit |
|---|---|---|
| under 0.30 | 3,775, 21.8% | 17,478, 24.3% |
| 0.30 to 0.40 | 4,533, 25.3% | 2,332, 39.5% |
| 0.40 to 0.50 | 4,585, 26.7% | 129, 55.8% |
| 0.50 to 0.60 | 3,444, 26.2% | 124, 64.5% |
| 0.60 to 0.70 | 2,000, 29.6% | 15, 73.3% |
| 0.70 to 0.80 | 1,147, 36.2% | 79, 54.4% |

How to read it: the raw models say "0.60 to 0.80" for stocks that really hit only 18 to 36% of the
time, so their score is not a probability. After calibration the score is roughly honest for mid
and small caps (0.40 to 0.50 hits about half; the table rises as the score rises). Large caps
barely produce scores above 0.30, so there is little to read.

### Where a "buy at 0.40 or more" bar lands (held-out window)

| Tier | Share of stock-days at or above 0.40 | Number | Really hit |
|---|---|---|---|
| Large | 0.4% | 39 | 38.5% |
| Mid | 5.8% | 1,699 | 49.9% |
| Small | 1.7% | 347 | 59.4% |

Rough break-even for a +8% / -4% trade is about 1 hit in 3 (a bit better than that because
misses that merely time out lose less than 4%, but costs and the half-out at +5% are not
modelled here). So 0.40 is the lowest bar that sits clearly above break-even in the table for mid
and small caps. For large caps the sample (39) is too small to trust.

## Compared with the old "+2% in 5 days" models

| | Old (active in prod) | Real question, raw | Real question, calibrated |
|---|---|---|---|
| Question | +2% in 5 days | +8% before -4% in 15 days | same |
| ROC AUC large / mid / small | 0.528 / 0.544 / 0.525 | 0.583 / 0.564 / 0.556 | 0.577 / 0.619 / 0.599 |
| Share of "yes" outcomes in test | 26% / 32% / 29% | 16% / 23% / 27% | same |
| Hit rate when score >= 0.60 | 28% / 36% / 32% | 24% / 33% / 34% | rarely reaches 0.60 |
| Does the score mean what it says? | No (and for a question the app does not trade) | No | Mostly yes for mid / small |

(AUC: 0.50 = coin flip, 1.00 = perfect.) The old models' `hit rate at 0.60` is against **their own
question** and, as the table shows, is only a few points above their base rate. The real-question
raw model's 24% / 33% / 34% at 0.60 is against the harder real question. The old artifacts are not on the
local disk, so this comparison uses the numbers stored in each model's record, not a fresh re-score.

## Honest limits (weak spots)

1. **The edge is modest and unstable.** Walk-forward AUC per fold (oldest to newest):
   large (calibrated) 0.517, 0.505, 0.484, 0.472, 0.604; mid 0.560, 0.523, 0.578, 0.542, 0.605;
   small 0.523, 0.511, 0.533, 0.441, 0.521. Large and small caps were at or below coin-flip in
   some folds. Mid caps were the steadiest.
2. **Calibration is learned on one recent regime** (the latest 25% of training dates), so the
   honest-looking table above is one out-of-sample window, not a guarantee.
3. **Large cap is nearly silent.** Calibrated scores sit in 0.12 to 0.32; only 183 of 9,551
   stock-days reach 0.30 (hit 39%) and 39 reach 0.40. When we scored today's last bars for all 49
   watchlist stocks the highest large-cap score was 0.275, so the large-cap strategy would
   produce **zero buys right now** in calibrated mode. That is consistent with the stressed market
   but means large-cap paper trading will be very thin.
4. **The weakness exit almost never fires.** With calibrated scores the "model wants out" line was
   rebased from 0.35 to 0.10, but fewer than 0.2% of stock-days fall at or below 0.10 and those
   were far too few to judge (20 large-cap days, none hit; 36 mid-cap days, 14% hit; 3 small-cap
   days). In calibrated mode the
   -4% stop and the 30-day time stop therefore carry the exits. This is a real change to how
   positions leave and is the owner's call.
5. In four of five walk-forward folds the calibrated large cap and mid cap models issued no score
   at or above 0.60; only the newest fold (Dec 2025 to Aug 2026) did. That fold is also the
   best one, so be careful not to over-read the 0.60+ hit rates (56% and 59%).
6. Local data ends 2026-09-08; costs, slippage and the half-out at +5% are not part of these hit
   rates. No shadow or live-paper evidence exists yet for the calibrated models.

## Turning it on in paper (owner steps)

Do nothing until the code containing this change is on production; with the setting empty the
app behaves exactly as today.

1. **Train on the droplet** (inside the api or worker container, same data volume; nothing
   becomes active):
   - `swingtrade train --name swing_classifier_barrier_cal --walk-forward-folds 5 --calibrate`
   - `swingtrade train --name swing_classifier_midcap_barrier_cal --symbols-from-model swing_classifier_midcap --walk-forward-folds 5 --calibrate`
   - `swingtrade train --name swing_classifier_smallcap_barrier_cal --symbols-from-model swing_classifier_smallcap --walk-forward-folds 5 --calibrate`

   Check each model's `metrics.reliability` (stated score vs really hit) before going on. If a
   0.40+ band is not well above the break-even of about 1 in 3, stop here.
2. **Activate the three new models** (`POST /api/v1/ml/models/{id}/activate`). They have their own
   names, so the old active models are not touched.
3. **Flip the switch**: add `ML_REAL_QUESTION_SUFFIX=_barrier_cal` to the droplet's environment
   and restart api and worker (`docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d api worker`).
   Optionally set `ML_REAL_QUESTION_MIN_CONFIDENCE` / `ML_REAL_QUESTION_EXIT_CONFIDENCE`.
4. **Watch**: the next scan scores with `*_barrier_cal`; signals show `model: swing_classifier_..._barrier_cal`
   in their details. Expect very few large-cap buys.
5. **Roll back**: remove (or empty) `ML_REAL_QUESTION_SUFFIX`, restart api and worker. The old
   models are untouched and take over at the next scan. Open positions keep their stop and target.

Deliberately not done: no models were copied to production, nothing was pushed or deployed, and
no strategy rows, order, sizing, stop or limit code was changed.
