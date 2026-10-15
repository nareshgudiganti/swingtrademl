# Paper balance and drawdown — reconciliation record (2026-10-15)

Evidence plan task A1 (`docs/superpowers/specs/2026-10-15-evidence-and-pilot-plan.md`). Read-only: nothing was
changed in the database. **No snapshot row was overwritten or deleted**; this file is the correction trail.

## 1. What was suspected

A local check on 2026-10-04 showed the paper account at **+435%** and a drawdown measured from the replaced
run's peak. The question: are prod's paper numbers wrong too?

## 2. Prod, checked 2026-10-15 (read-only API, `/portfolio/summary` and `/portfolio/equity-curve?all_time=true`)

| Figure | Prod value |
|---|---|
| Measured since | 2026-09-28 (`PAPER_TRIAL_START_DATE`) |
| Starting capital (trial opening equity) | ₹9,79,791.66 |
| Total value | ₹9,76,758.44 |
| Return since the trial start | −0.31% |
| Maximum drawdown in the trial | 0.77% |
| Current drawdown | 0.68% |

**The +435% bug is not on prod.** The opening equity is the expected ₹9,79,792 (paper trial baseline).

## 3. The one leftover: stored `drawdown_pct` on 2026-09-28 to 2026-10-09

Snapshot rows store a `drawdown_pct` column. On the first ten trial days it was measured from the
replaced run's peak (≈ ₹10,00,000), not from the trial's own peak. The column is now rebuilt from values
for trial reports (`services/portfolio.py`, commit `9ac2e8e`, 2026-10-09), and the 15% halt uses the
trial's own peak (`drawdown_peak`). From 2026-10-12 the stored column agrees.

| Day | Total value (₹) | Stored `drawdown_pct` | Rebuilt from the trial peak |
|---|---|---|---|
| 2026-09-28 | 9,79,601 | 2.04% | 0.02% |
| 2026-09-29 | 9,78,257 | 2.17% | 0.16% |
| 2026-09-30 | 9,79,800 | 2.02% | 0.00% |
| 2026-10-01 | 9,78,043 | 2.20% | 0.18% |
| 2026-10-02 | 9,78,043 | 2.20% | 0.18% |
| 2026-10-05 | 9,77,492 | 2.25% | 0.24% |
| 2026-10-06 | 9,78,514 | 2.15% | 0.13% |
| 2026-10-07 | 9,78,108 | 2.19% | 0.17% |
| 2026-10-08 | 9,83,429 | 1.66% | 0.00% |
| 2026-10-09 | 9,75,883 | 2.41% | 0.77% |
| 2026-10-12 | 9,80,202 | 0.33% | 0.33% |
| 2026-10-13 | 9,77,342 | 0.62% | 0.62% |
| 2026-10-14 | 9,76,966 | 0.66% | 0.66% |
| 2026-10-15 | 9,76,758 | 0.68% | 0.68% |

Reconciles: the rebuilt maximum (0.77% on 2026-10-09) equals the summary's `max_drawdown_pct`.

Effect while it lasted: the stored figure was about 2 points too high, so the account looked closer to the
15% halt than it was. That errs toward caution (a halt could only have come early, never late), and no
halt fired. Rows are kept as they are; screens read the rebuilt figure.

## 4. The local-only cause

Local root `.env` sets `PAPER_STARTING_CAPITAL=200000` (code default 1,000,000), and the local snapshot job
ran with it from about 7 Sep. Local snapshot rows therefore sit about ₹8,00,000 below the live ledger, and
the trial's opening equity, taken from the last snapshot before 2026-09-28, came out near ₹1.84 lakh,
hence +435%. This affects the local database only. Fixing it locally means changing the local `.env` and
local snapshot rows; it has no effect on prod and is not part of the evidence record.

## 5. Tests that pin the behaviour

`backend/tests/test_paper_trial_window.py` (from `9ac2e8e`), 14 tests, all passing on 2026-10-15, including:
- `test_drawdown_does_not_inherit_the_replaced_run`
- `test_halt_does_not_inherit_the_replaced_runs_peak`
- `test_halt_still_fires_on_a_real_fall_inside_the_trial`
- `test_trial_drawdown_is_rebuilt_from_values_not_stored_column`
- `test_return_measures_from_the_trial_opening_equity`

The evidence pack (task A5) adds a reconciliation test: its paper section must equal `/portfolio/summary`.
