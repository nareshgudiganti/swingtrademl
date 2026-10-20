# Look-ahead audit — every model input and label (ps10) — 2026-10-20

**Question:** can any input, label or training step use information from after the day it is used for?
A leak like that makes every back-test and paper result look better than the system really is.

**Method:** list every place data enters a model or a decision, name the protection in the code and the
test that proves it. Each new test was **mutation-checked**: the protection was broken on purpose and the
test had to fail (then the code was restored).

Result labels: **PASS** (protected and proven by a test) · **NOT TESTABLE** (a known limit of our data,
written on every report; it cannot be fixed with the data we have).

| # | Input / step | Protection | Test | Result |
|---|---|---|---|---|
| 1 | Stock price and volume indicators (v1 features) | rolling windows look back only | `test_features.py::test_features_do_not_use_future_data` (truncation) | PASS |
| 2 | Market context joined to each stock day: NIFTY, sector index, India VIX, breadth | `merge_asof(direction="backward")`: only a row on or before the stock's day | **new** `test_lookahead_audit.py::test_a_market_gap_is_filled_from_the_day_before_never_the_day_after` | PASS |
| 3 | Context series longer than the stock (late listing, missing bar, replay day) | same backward join | **new** `test_newer_market_rows_never_change_a_stocks_past_features` | PASS |
| 4 | Market breadth calculation | 50-day average per stock, no centred window | **new** `test_breadth_on_a_day_uses_no_later_day` | PASS |
| 5 | The +8% / −4% / 15-day label | future window by design; last 15 rows dropped; a same-day touch of both counts as a stop | barrier tests in `test_features.py` | PASS |
| 6 | Train / test split of v1 models | every training row whose 15-day result ends after the test start is purged (`label_end_ts`) | `test_correctness_release.py::test_split_keeps_dates_together_and_purges_labels`, `test_walk_forward.py` embargo tests | PASS |
| 7 | Calibration inside training (base model vs calibration slice) | base-model rows whose result ends after the slice cut are left out | **new** `test_the_calibration_step_trains_its_base_model_only_on_results_known_before_its_cut` | PASS (was untested) |
| 8 | Research "as-of" models | trained only on rows whose result was known by the cutoff | `test_asof_training.py` | PASS |
| 9 | M06 calibrated model | training window and purge rows dropped | `test_brain_m06_trainer.py::test_rows_inside_the_training_window_or_its_purge_are_dropped` | PASS |
| 10 | Every brain read (DatedReader) | bounded by the run's `as_of` | `test_brain_no_lookahead.py`, `test_asof_reader.py` | PASS |
| 11 | Replay with a model trained after the replayed days | refused unless asked, and then labelled in-sample; the live model is never used for past days | `test_asof_replay_score.py` | PASS |
| 12 | Which stocks are in the universe and in breadth | **today's** watchlist, so stocks that later disappeared are missing (survivorship) | — | NOT TESTABLE: no delisted-stock history |
| 13 | Sector of each stock (`ml/sector_map.py`) | **today's** mapping for every past day | — | NOT TESTABLE: no dated sector history; low impact (rarely changes) |
| 14 | Splits, bonuses and other company events | no corporate-action table; 5 suspicious one-day moves > 35% seen (audit F-07) | — | NOT TESTABLE |
| 15 | Delivery % | not a model input (rejected 2026-10-12) | — | not applicable |

## What this changed

- No leak was found in the code.
- Two protections were **in the code but not proven** by any test: the market-gap join (row 2; the old
  truncation test still passed when the join was flipped to look forward, because every test series shared
  one calendar) and the calibration slice purge (row 7). Both are now tested.
- Rows 12–14 stay on every evidence report as known limits.

Tests: `backend/tests/test_lookahead_audit.py` (4 tests).
