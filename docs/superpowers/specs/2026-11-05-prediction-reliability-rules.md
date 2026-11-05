# Prediction Reliability: rules (2026-11-05)

Status: rules written before code. Every number marked PROPOSED must be signed by the owner before any real
outcome is read through this report. Code: `backend/src/swing_trade_ml/brain/prediction_reliability.py`.

This report measures evidence. It never guarantees accuracy or profit, and it changes nothing: it only reads
the database (SELECT), places no orders and edits no threshold, model or frozen trial file.

## What is tracked (each separately)

1. The Brain's nightly Top-5 by score.
2. The Brain's TRADE decisions.
3. High-score predictions: score of 0.80 or more, still at most 5 a day.
4. Lane picks (10D, 15D shadow lanes) and the 5D evaluation lane (h05, all eligible stocks, Top-5 selected).

Each is compared with matched baselines: every eligible stock scored the same day (Brain, h05), or the
same-day average of the cap group (lanes, already stored as `baseline_net_return`). Brain and h05 also show
Top-5 against ranks 6-20.

## Counting rules

- Only completed outcomes count: target, stop, timeout (brain, lanes), or a matured label / resolved
  trade (h05). Open or unresolved ideas are shown as a count and never enter a rate or an average.
- Horizons (5D, 10D, 15D) and every model or version are separate series. They are never pooled, and no
  total across them is printed.
- No existing threshold is changed. The sample gates are reused: Brain 15 sessions and 30 ideas
  (`trial_journal.MIN_SESSIONS`, `GATE_MIN_IDEAS`); lanes 60 matured days (`lane_review.CHECKPOINTS[0]`);
  5D lane 40 matured signal days (`h05_protocol` `min_evidence_per_group`).
- Sealed trial: for any signal day on or after `trial_seal.SEALED_FROM` (while `SEALED` is true) only counts
  (picked, completed, open) are printed. No rate, average, interval or bucket is computed from those days,
  and no total mixes them in, so a result cannot be recovered by subtraction. A series whose evidence is all
  sealed is INSUFFICIENT DATA, and HEALTHY can never come from sealed data.

## Measures

- Target-hit rate with a Wilson 95% interval.
- Calibration: the model's stated chance against the hit rate it really had, by band
  (`ml.calibrated_model.reliability_table`), plus the Brier score (lower is better) against the naive score
  of always saying "the base rate". The lane and h05 scores are shown as the stated chance; they may not be
  calibrated, and the report says so.
- Hypothetical net profit and loss per pick after costs (the stored net returns), with a block-bootstrap
  lower bound on the daily average (`walk_forward.bootstrap_low`, blocks of `BLOCK_DAYS` = 15 days).
- Excess over the matched baseline.
- Sample sizes: picked, completed, open.
- Overlap: picks inside one holding horizon are not independent. The report gives the effective sample,
  the number of independent blocks (picks at least one horizon apart), next to the raw count.
- Drift: reported as "not measured" unless reference and recent score samples are supplied, then PSI
  (`m09_learn.drift.psi`). Nothing is invented when it is missing.

## Health states (PROPOSED, owner to sign before any real outcome is read)

All thresholds are named constants in one place in the module (`HEALTH_RULES`).

- INSUFFICIENT DATA: below the reused sample gates above (days and completed picks), or evidence is
  sealed, or the matched baseline is missing. No other word is allowed.
- FAIL (any one, gates met): the hit rate's Wilson upper bound is below the baseline hit rate; or average net
  result is negative and also below the baseline; or the Brier score is worse than the naive score by more
  than 0.02 (PROPOSED).
- HEALTHY (all, gates met, unsealed): Wilson lower bound of the hit rate above the baseline hit rate (when a
  baseline hit rate exists); average excess over baseline above 0; block-bootstrap lower bound of the net
  result above 0 (PROPOSED: 0.0); Brier score no worse than naive.
- WATCH: gates met, not FAIL, not HEALTHY, or drift PSI at or above 0.2 (PROPOSED).

## Known gaps

- The Brain's own Top-5 is rebuilt from `brain_decisions` on each run. There is no frozen record of it and
  no model-version column, so Brain figures cannot be tied to a model version. This is a limitation, not
  fixed here (no tables, no migrations).
- Brain scores are used as stated chances only where the Brain stored a score source.
- Lanes record only their Top-5, so ranks 6-20 and a baseline hit rate are not available for them.
- Survivor bias and unmodelled liquidity limits stay as stated in the lane review.
