# #255 Verification: model scoreboard by horizon and cap group (parent #235)

Baseline commit: `5de3b9c` (main). Test database: `swing_trade_ml_dev1b_test`. Written 2026-11-23 (IST).
Tests and this note only. No model, model status, threshold, sealed-trial or frozen code was changed. The note holds no
account, key or personal data.
New tests: `backend/tests/test_verify_255_model_scoreboard.py` (19 tests: 13 pass, 6 are strict expected failures that mark gaps).

## In plain English

The question: wherever the app shows how a model is doing, does every number say which horizon (5, 10 or 15 days) and which
size group (large, mid, small) it belongs to, are research results kept for the owner, are different kinds of results kept apart,
and does a thin sample admit it is thin?

- **Labels and mixing are sound where the app shows model results to the owner.** The horizon report (all three horizons side by
  side), the lanes screen, the weekly report and the experiments report all name the horizon, and the size group where it applies.
  Each lane's numbers come only from its own stored rows. Two lanes with different results do not bleed into each other.
- **All of these screens are owner-only,** and no member-visible route reads the lane, weekly or experiment code.
- **Backtest, live-forward and paper results are kept in separate blocks.** The weekly report states that its three sources are never
  added together and has no grand total. A 5-day lane never shows a 10- or 15-day history test.
- **A model with no results says so** (empty values, never a zero) and the reports say "Not enough days to judge" or "Not proven".
- **Five gaps found, pinned by six tests (none fixed):**
  1. **a4: one number mixes models.** `GET /ml/predictions/accuracy` gives a single accuracy over every model, whatever
     its horizon, and mixes the older "endpoint" labels with the newer "barrier" labels. Who can reach it: the route is not in the plan
     rules, so with plans on it is owner-only; unrestricted accounts (for example a tester while plans are off) and scripts using the
     service key can also reach it. Members on a plan cannot.
  2. **b3: 10-day and 15-day rows carry no research-only flag** in the report data. The words say "test records only", and the screens are
     owner-only, but a machine-readable flag is missing although the research config marks both horizons research-only.
  3. **d2, d3: "too early to judge" still prints a rate.** The lanes screen and the horizon report say the sample is too small, but still
     show a hit rate and an average return (for example 100% from 3 finished picks).
  4. **d4: no results shows an accuracy of 0.0** on the prediction accuracy route, not an empty value (same route as a4). The same
     answer also gives 0.0 for the average probability and the average actual return when nothing has been evaluated.
  5. **e1: a pick that matured with no usable price is counted nowhere.** The lane shows 6 picks, 4 completed and 1 open, so the counts do not add up.

## Findings table

| # | Question | Code (at `5de3b9c`) | Expected | Observed (test) | Result |
|---|---|---|---|---|---|
| a1 | Horizon and cap group of each report row | `shadow_lanes/horizon_report.py:49` (`ROWS`) against `services/lane_slots.py` slot table | each row's horizon and group equal its slot's | all six rows agree; 5-day rows are the three h05 groups (`test_a1_*`); order and labels also in `test_horizon_report.py` | Pass |
| a2 | Do two lanes mix? | `api/v1/endpoints/lanes.py:173-179` (`_rows` filters by slot), `horizon_report.py:176` `_lane_row` | each row from its own slot only | mid lane +0.5% from 4 finished, large lane -5% from 6, empty 10-day lane stays empty; counts equal the stored rows (`test_a2_*`) | Pass |
| a3 | Mid-cap warning only on the mid lane | `lanes.py:35,194-195` | warning on mid only | `test_a3_*` | Pass |
| a4 | Does the accuracy route mix horizons or label eras? (owner-only with plans on; unrestricted accounts and service keys reach it) | `api/v1/endpoints/ml.py:301-330` (no `model_id` means every model's predictions pooled; `label_kind` is not filtered) | one figure per model and horizon | the pooled answer equals the sum over the three models' own answers, and differs from any single one; nothing in it names a horizon | **GAP** |
| b1 | Result routes owner-only | routers of `lanes`, `lane_picks`, `h05`, `weekly_report`, `experiments`, `model_registry` all carry `require_owner` | every route owner-only | every route has it (`test_b1_*`); role checks in `test_horizon_report.py` and `test_lane_shadow_api.py` | Pass |
| b2 | Who imports the lane, weekly and experiment code | `api/` | only the owner routers | only those four owner files (`test_b2_*`) | Pass |
| b3 | 10D and 15D rows marked research-only | `horizon_report.py:176` (`_lane_row`) sets no flag; `core/research_config.py:66-67` marks both research-only | `research_only: true` on both | field absent | **GAP** |
| b4 | Plain wording says test records, not trades | `horizon_report.py:NOTE`, `lanes.py:31` | words present | present (`test_b4_*`) | Pass |
| c1 | Weekly report keeps sources apart | `services/weekly_paper_report.py:511-535` (`build_report`) | h05, bot, testing separate; no grand total | separate sections, "never added together", and none of a few named keys (`total_pnl`, `combined`, `grand_total`, `all_books`) appears; this is a name check, not proof that no sum exists; 10D and 15D marked not part of it (`test_c1_*`; 20 tests in `test_weekly_paper_report.py`) | Pass |
| c2 | History test of one horizon shown for another? | `lanes.py:127-131` | a 5-day lane never shows a 10/15-day test | `test_c2_*` | Pass |
| c3 | History and forward in one figure? | `lanes.py:219-247`, `horizon_report.py:176-214` | separate blocks | separate keys, forward from stored rows only; the report reads history only for the qualification text (`test_c3_*`, `test_c4_*`) | Pass |
| c4 | Brain scoreboard (development data, sealed days) | `brain/scoreboard.py` | development data only; sealed days show counts only | `test_brain_scoreboard.py` (15 tests, includes thin-group flag and the sealed-window refusal) | Pass (cited) |
| d1 | No results | `lanes.py:182-216` | empty values and "too early" | `None`, never 0; "Fewer than 60 completed picks: too early to judge." (`test_d1_*`; the report's empty state in `test_horizon_report.py`) | Pass |
| d2 | Lanes screen with 3 finished picks | `lanes.py:196-202` | says "too early" and shows no rate | says so AND shows a 100% hit rate | **GAP** |
| d3 | Horizon report with 4 finished picks | `horizon_report.py:176-214` | "Not enough days" and no rate | verdict says so, `hit_rate` 0.5 and `net_per_trade` still present | **GAP** |
| d4 | Accuracy route with no evaluated predictions | `ml.py:325` | an empty value for accuracy, average probability and average return | `0.0` for all three (`ml.py:325` and the two averages beside it) | **GAP** |
| d5 | Experiments report | `services/experiments/report.py:30-79` | no mean or win rate until there is a closed sample; verdict "Not proven" below the minimum | empty values and "Not proven" (`test_d5_*`; the report also shows the minimum needed) | Pass |
| e1 | Lane counts add up | `lanes.py:182-201` (`open` counts picks with no outcome row; `completed` counts rows with a return) | picks = completed + open + unresolved | a matured pick with no price (`unresolved`) is in neither, 4 + 1 of 6 | **GAP** |
| e2 | Lane counts add up when there is no unresolved pick | same | 6 = 4 + 2 | pass; sessions recorded match (`test_e2_*`); horizon-report counts equal the stored rows (`test_a2_*`) | Pass |
| e3 | Ledger, h05 report and weekly report counts agree | `shadow_lanes/outcome_ledger.py` | equal where they mean the same | `test_outcome_ledger_reconcile.py::test_the_ledger_counts_equal_the_h05_report_and_the_weekly_report_where_they_mean_the_same` (5 tests) | Pass (cited) |

## Gaps for the owner (one line each, none fixed)

- **a4 / d4:** the accuracy route (owner, testers while plans are off, service keys) should be per model and horizon (and per label era), and an empty result should be empty, not 0.0 (accuracy and both averages).
- **b3:** add a `research_only` flag to the 10-day and 15-day rows (read from `core/research_config.py`).
- **d2 / d3:** when the screen says "too early" or "not enough days", show the sample size and hide the rate (or grey it out); the experiments report has the same shape but keeps its verdict at "Not proven".
- **e1:** show unresolved picks as their own count so picks equal completed plus open plus unresolved.

## Limits worth knowing (not gaps)

- The experiments report pools every hand-picked stock of one horizon; it has no size-group split. Those picks are the owner's own research, not a model scoreboard, and the report says so.
- The brain scoreboard (S1) ranks by score, not by size group, and uses development data only; the sealed trial days show counts only.
- The horizon report's 10-day row is shown even when no 10-day lane is running; the weekly report says "no lane" for 10-day. Both statements are about different things (the report lists a slot; the weekly report lists what runs), but the owner may read them as a conflict.

## How the gap tests work

Each gap is a test that states what the code SHOULD do, marked `xfail(strict=True, raises=AssertionError)`. They fail today for the stated
reason (checked with `--runxfail`). If a gap is fixed the strict marker turns the test red and is then removed on purpose.

## Not covered here

Real brokers, production, live trading, model training and the sealed trial were not touched. The customer-facing past-results layer
and the Brain's own idea reports read stored decisions, not these scoreboards, and are covered by other notes.

Re-run for this note (dev1b): the new file plus `test_horizon_report.py`, `test_lane_shadow_api.py`, `test_lane_review.py`,
`test_weekly_paper_report.py`, `test_outcome_ledger_reconcile.py`, `test_brain_scoreboard.py`, `test_h05_service.py` and the four
`test_experiments_*.py` files: **183 passed, 6 xfailed** (the six gaps).
