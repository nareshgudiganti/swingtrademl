# As-of model scoring for brain replays — design

Status: DRAFT for owner review (2026-10-11). No code written.

## Why

`brain replay-score` (built 2026-10-11) replays past days and scores every idea, but a replay finds no
brain ideas. `DatedReader.model_probability` returns None unless the run is live, because the model
scores the newest bars (`ml/predict.py::predict_instrument` loads the latest 400 candles). M08 needs that
score to say TRADE, so every replayed day ends WAIT or WATCH. First run, 2026-08-03..05: 0 brain ideas.

Without this, "last month" can only be judged from the few days the live brain has run.

## Goal and success

Let a replay score each past day with a model that had never seen that day or any outcome known by then.
Success: a replay of about 25 trading days produces real TRADE and blocked ideas, and the report says which
model scored them, what that model was trained on, and that no day it scored was in its training data.

## Scope rules

- Local databases and research only. Never sets a model ACTIVE, never changes the live model, never
  touches prod. As-of models are registered as TRAINED under their own name.
- Replays only. The live scoring path (`predict_instrument`, the nightly run) is unchanged.
- No change to M08 rules, the risk gate, sizing, stops or limits.

## Design

1. **Train with a cutoff.** Add a `cutoff: date | None` argument to `ml/train.py::train_model`. When set,
   keep only training rows whose label window ended on or before the cutoff (`label_end_ts <= cutoff`), so
   no row's outcome was unknown at the cutoff. The model is named `swing_classifier_asof_<YYYYMMDD>` and
   stored TRAINED, with `train_end` = the cutoff. Walk-forward folds and calibration stay as they are.
2. **Score any past day.** New `ml/asof.py::score_days(db, instrument, model, days) -> dict[date, float]`.
   It builds features once per stock from the full candle and market-context frames (index, sector, VIX,
   breadth) and reads the row for each day. This is cheaper than slicing per day, and equal to slicing only
   if every feature is causal (uses data up to and including that day). That is tested, not assumed (see
   Tests, item 1).
3. **Reader uses it in replays.** `DatedReader` gets an optional `asof_model` (an `MLModel`). When the run is
   not live and `asof_model` is set, `model_probability` returns `(probability, threshold, label)` from the
   cached scores, and only for a day strictly after the model's cutoff (recorded in `metrics["asof_cutoff"]`; a model's `train_end` is earlier, because the last quarter of the data is held out for testing). Otherwise
   it returns None, as today. The threshold is `settings.ML_MIN_CONFIDENCE`, not the accepted buy level,
   which is learned from later outcomes and would leak. `brain/fallbacks.py` also skips the model opinion in
   every replay; it must stop skipping when the reader carries an as-of model.
4. **Thread it through.** `run_replay_week(..., model_name=None)` and `service.run_brain(..., asof_model=None)`
   pass the model to the reader. `brain replay-score --asof-model NAME` selects it, and the command refuses
   any window that starts on or before the model's training end, unless `--allow-in-sample` is given; then
   the report's first line says IN-SAMPLE.
5. **Report.** `replay_score` adds the model name, its training window, the first and last scored day and the
   count of days where no score existed, and prints them in the plain summary.

## First real run

Train `swing_classifier_asof_20260710` on data up to 2026-07-10, replay 2026-07-13 to 2026-08-14 (about 25
trading days). Local candles end 2026-09-08, so every idea has its 15 trading days. The point-in-time
watchlist only exists from 2026-10-05, so the report's limits line about today's watchlist applies.

## Tests

1. **Feature causality:** for several stocks and days, features built from candles cut at day D equal the
   row for D built from the full history. If this fails, features are not causal: stop and report it.
2. **Cutoff purge:** a model trained with a cutoff has no training row whose label ends after it.
3. **Reader:** returns None for a day on or before `train_end` plus the horizon, and for a live-off run with
   no `asof_model`; returns a score after.
4. **No look-ahead end to end:** adding wild future bars does not change a replayed day's score (extends
   `test_brain_no_lookahead.py`).
5. **Replay produces ideas:** on a synthetic market with a tiny trained model, at least one TRADE or blocked
   idea appears.

## Open risks

- M05 memory and the M09 learning loop may also read data newer than the replayed day. M05 is bounded by
  `DatedReader` as_of (to be confirmed by reading `brain_experience` access); M09 buy level is avoided above.
- Training time for a cutoff model on the local database (to be measured).
- Replay speed: about 25 seconds a day for 10 stocks in the first test. A full watchlist for 25 days may take
  hours; measure before the real run and use `--symbols` to start small.
- A model trained on 4 years of data, then tested on one month, is one sample. It shows whether the pipeline
  works and gives a first estimate, nothing more.

## Not in this spec

M06 combiner replays (it is in SHADOW), live-model changes, adjusted prices, news, a portfolio simulator.
