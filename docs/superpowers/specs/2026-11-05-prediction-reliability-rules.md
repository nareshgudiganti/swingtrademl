# Prediction Reliability: rules (2026-11-05)

Status: **owner-approved 2026-11-05** (decisions 1 to 8 below). Code:
`backend/src/swing_trade_ml/brain/prediction_reliability.py`.

This report measures evidence. It never guarantees accuracy or profit, and it changes nothing: it only reads
the database (SELECT), places no orders and edits no threshold, model or frozen trial file.

**States are diagnostic only.** HEALTHY, WATCH, FAIL and INSUFFICIENT DATA are labels printed on a report.
Nothing may activate, retrain, disable, promote or change any model, rule or order because of a state, and
the module imports nothing that could (a test checks the imports and that the module makes no write calls).

## Owner decisions (2026-11-05)

1. States stay HEALTHY, WATCH, FAIL, INSUFFICIENT DATA.
2. All existing minimum sample gates are unchanged (below).
3. Advantage over a baseline is a paired, date-blocked comparison: the per-day difference (pick set minus
   baseline), then the existing block bootstrap (`walk_forward.bootstrap_low`, `BLOCK_DAYS` = 15). No unpaired
   comparison gates a state any more.
4. Accuracy (hit rate), economics (net result), ranking (Top 5 against ranks 6-20), calibration and drift are
   separate measurements. There is no blended or single score.
5. Brier is information only. It gates a state only for a series explicitly flagged `calibrated` (the series
   key `"calibrated": True`). The default is not calibrated, and no series is flagged today, so Brier never
   gates. The old Brier FAIL rule and Brier HEALTHY condition apply only to a flagged series.
6. PSI of 0.20 or more is a WATCH warning only when a valid reference sample exists (a reference and a recent
   sample, each with at least `m09_learn.drift.MIN_ROWS` = 50 scores). Otherwise drift is "not measured" and
   has no effect. The report does not supply a reference sample yet, so today drift is always "not measured".
7. Missing required evidence never produces HEALTHY, and a missing observation is never turned into 0: it is
   None / "not recorded".
8. States are diagnostic only (above).

## What is tracked (each separately)

1. The Brain's nightly Top-5 by score.
2. The Brain's TRADE decisions.
3. High-score predictions: score of 0.80 or more, still at most 5 a day.
4. Lane picks (10D, 15D shadow lanes) and the 5D evaluation lane (h05, all eligible stocks, Top-5 selected).

Each is compared with matched baselines: every eligible stock scored the same day (Brain, h05), or the
same-day average of the cap group (lanes, already stored as `baseline_net_return`). Brain and h05 also show
Top-5 against ranks 6-20 (the "ranking" measurement, paired by day, never part of a state).

## Counting rules

- Only completed outcomes count: target, stop, timeout (brain, lanes), or a matured label / resolved
  trade (h05). Open or unresolved ideas are shown as a count and never enter a rate or an average.
- Horizons (5D, 10D, 15D) and every model or version are separate series. They are never pooled, and no
  total across them is printed.
- No existing threshold is changed. The sample gates are reused: Brain 15 sessions and 30 ideas
  (`trial_journal.MIN_SESSIONS`, `GATE_MIN_IDEAS`); lanes 60 matured days (`lane_review.CHECKPOINTS[0]`);
  5D lane 40 matured signal days (`h05_protocol` `min_evidence_per_group`).
- Sealed trial: for any signal day on or after `trial_seal.SEALED_FROM` (while `SEALED` is true) only counts
  (picked, finished, open) are printed. No rate, average, interval or bucket is computed from those days,
  and no total mixes them in: every figure is computed from the unsealed days alone, and the sealed counts
  are a separate field, so a result cannot be recovered by subtraction. A series whose evidence is all
  sealed is INSUFFICIENT DATA, and HEALTHY can never come from sealed data. The ranking measurement and any
  drift sample also use unsealed days only. Tests change the sealed results and assert the whole report and
  the dated report file are byte-identical.

## Measures (shown separately)

- Accuracy: target-hit rate with a Wilson 95% interval (shown, not a gate).
- Economics: hypothetical net profit and loss per pick after costs (stored net returns), with a
  block-bootstrap lower bound on the daily average.
- Advantage over the matched baseline, paired by day: mean of (pick-set day average minus baseline day
  average), days where both exist. Brain and h05 use `walk_forward.daily_edge` (the trial journal's own
  function). Lanes use each pick's stored same-day baseline (return minus baseline, averaged per day, picks
  without a stored baseline left out). Both the net-result gap and the hit-rate gap are computed (the hit-rate
  gap only where a baseline hit rate exists), each with 5th and 95th percentile block-bootstrap bounds.
  These need at least `max(5, 2 * BLOCK_DAYS)` = 30 paired days; with fewer there is no bound.
- Ranking: Top 5 minus ranks 6-20, paired by day, same bounds. Information only.
- Calibration: the model's stated chance against the hit rate it really had, by band
  (`ml.calibrated_model.reliability_table`), plus the Brier score against the naive score of always saying
  "the base rate". Information only unless the series is flagged calibrated (decision 5). The report prints
  "score not established as calibrated".
- Sample sizes: picked, completed, open.
- Overlap: picks inside one holding horizon are not independent; the number of independent blocks (picks at
  least one horizon apart) is shown next to the raw count.
- Drift: PSI (`m09_learn.drift.psi`) only with a valid reference sample (decision 6), else "not measured".

## Health states

All thresholds are named constants in one place (`HEALTH_RULES`). Evaluated in this order, per set (Top 5,
TRADE, score 0.80 or more):

- INSUFFICIENT DATA: sealed evidence; or below the reused sample gates (days or completed picks); or no
  matched baseline (paired gap is None).
- FAIL (gates met, any one): the upper bound of the paired net-result gap is below 0; or the upper bound of
  the paired hit-rate gap is below 0; or average net result is negative and the paired gap is also negative;
  or (only for a series flagged calibrated) Brier worse than naive by more than 0.02.
- WATCH: gates met, not FAIL, and not HEALTHY because a required piece of evidence is missing or not clearly
  positive, or because drift PSI is 0.20 or more with a valid reference sample.
- HEALTHY (all, gates met, unsealed, nothing required missing): lower bound of the paired net-result gap
  above 0; lower bound of the daily net result above 0; lower bound of the paired hit-rate gap above 0; and
  (only for a series flagged calibrated) Brier no worse than naive; and no drift warning.

Required evidence for HEALTHY: the paired net-result bound, the net-result bound and the paired hit-rate
bound. Consequence to review: lane picks store a baseline return but no baseline hit rate, so a lane series
can reach at most WATCH ("baseline hit rate not recorded"). The Brain with fewer than 30 paired days also
stays at WATCH. This follows from decision 7 (cautious); the owner can relax it.

## Reused and not reused (review of 2026-11-05)

Correction: the earlier note that `score_bands` does not exist was false. It exists at
`services/brain_observatory/score_bands.py`, and the files below were reviewed against this module.

| Existing code | Reused? | Why |
|---|---|---|
| `walk_forward.bootstrap_low`, `BLOCK_DAYS` | Reused | Identical definition (block bootstrap of a day-ordered series). Upper bound is the same function on negated gaps. |
| `walk_forward.daily_edge` | Reused (Brain, h05, ranking) | Identical definition: per day mean of picks minus mean of the comparison group, finished only, days where both exist. Fed through a one-attribute adapter. |
| `trial_journal` constants (`MIN_SESSIONS`, `GATE_MIN_IDEAS`, `SCORE_LINE`, `TOP_N`), `lane_review.CHECKPOINTS` | Reused (imported) | The sample gates and set definitions, unchanged. |
| `h05_protocol.RUN_VALUES` (40 matured signal days) | Value copied, not imported | An existing test forbids any file outside the 5D lane package from importing it. A test asserts the copy equals the protocol value. |
| `trial_journal.load_sessions`, `replay_score.load_bars`, `walk_forward.outcomes_for` | Reused | The same readers and next-open net-of-costs outcome the journal uses. |
| `ml.calibrated_model.reliability_table` | Reused | Same banding and fields for a reliability table. |
| `m09_learn.drift.psi`, `MIN_ROWS` | Reused | Same PSI and minimum size. |
| `trial_seal` (`is_sealed_day`, `counts_only`, texts) | Reused | The one seal. Its `COUNT_FIELDS` includes `finished` and not `completed`, so sealed counts use the key `finished`. |
| `services/brain_observatory/score_bands.py` | Not reused | Different population and definition: M09 stored grade (entry at the decision close, gross, no costs), model-source ideas only, seven fixed score bands, hit rate only. Ours is net of costs, covers lanes and h05, and uses the shared reliability table bands. |
| `services/brain_observatory/outcomes.py` (stored grades, computed figures, forward gate) | Not reused | Returns gate verdicts and category-specific (practice / backtest / paper) figures with its own stage filtering and baselines (random, momentum, NIFTY). Our series are per horizon / model / group, with one baseline each. Its stage-history filter would change the Brain population. |
| `brain/trial_journal.py` summaries / `gate` | Not reused (only helpers above) | Journal sets include v1 buys and blocked ideas and a CLEARLY_WORSE rule on a different population; its gate decides the M18 gate, which this report must not touch. |
| `brain/scoreboard.py` (`group_stats`, `daily_gap`) | Not reused | Development data (walk-forward folds), DataFrame based, ranks groups 6-10 / 11-15 / 16-20, status set excludes `expiry`, refuses windows reaching sealed days. Different population. |
| Wilson interval, Brier score, effective blocks | Own implementation | No equivalent function exists in the repository. |

## Known gaps

- The Brain's own Top-5 is rebuilt from `brain_decisions` on each run. There is no frozen record of it and
  no model-version column, so Brain figures cannot be tied to a model version. This is a limitation, not
  fixed here (no tables, no migrations).
- Brain scores are used as stated chances only where the Brain stored a score source.
- Lanes record only their Top-5, so ranks 6-20 and a baseline hit rate are not available for them.
- For h05, the hit rate is the endpoint label (+2% after five sessions) while net result is the fixed-rule
  shadow trade; they are separate outcomes of the same pick, kept separate.
- Survivor bias and unmodelled liquidity limits stay as stated in the lane review.
