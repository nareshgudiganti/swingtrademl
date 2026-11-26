# F3 horizon labels: G1 option A (label only)

## Wording change
- Old, `frontend/src/trademind/pages/StockDetail.tsx:330`: `{decision.horizon_days} trading days` under "Horizon".
- New, same place (about lines 331-333): two lines from `forecastAndHold()` (`frontend/src/trademind/scoreVsPlan.ts`, end of file):
  - "Forecast: 5 trading days (the window the score looks at)"
  - "Longest hold: up to 15 trading days (when the plan sells)"
- Number sources: the 15 is still `decision.horizon_days`. The 5 is `horizonRule(5).max_sessions`, the server's trading-rules payload that `scoreVsPlan()` already uses. No backend field is needed, so nothing was invented.
- StockNew.tsx renders StockDetail, so it needed no change. `horizons.ts` and `today/SwingPicks.tsx` were left alone (see below).

## Tests
- `horizonLabels.test.ts`: added 2 tests. One asserts the exact new wording, that the forecast line has no 15, and that no label calls the score a 15-day prediction. One asserts the header uses the helper and no bare `{decision.horizon_days} trading days`.
- Run: horizonLabels 66, scoreVsPlan 4, HorizonSelector 6, total 76 passed. All Stock* tests: 19 passed. `npx tsc --noEmit -p .` was clean.

## A7 (#238 plan percentage test)
- Test: `test_the_percentages_on_the_plan_card_agree_with_the_plan_prices`, in `backend/tests/test_verify_238_5d_ideas_screens.py:268`, on branch `test/238-5d-ideas-screens`. It is not on main.
- Measurement: `plan["target_pct"]` (from `/beginner/stock/{symbol}` `q3_plan`) must equal `target / middle - 1` within abs 0.005. `middle` is (entry_low + entry_high) / 2 = 100.5, and target is 108.0, so the expected value is 7.46% (108/100.5 - 1).
- It is marked `xfail(strict=True)` for GAP #416. The percentages come from v1 `settings.ML_*` (`beginner_views.py` q3_plan) while the target price is the Brain's +8% plan. The test sets ML_TARGET_RETURN_PCT to 0.02 and so deliberately shows +2% beside a +8% price.
- I did not change or weaken it. The owner should decide whether the fix belongs in the backend (q3_plan computing percentages from the stored prices, which changes a number, so it is out of scope here) or in the test. As written, the test correctly describes a real defect.

## #241
What remains: the score is a 5-session model reading and the plan is 15 sessions. They are now named apart on the stock header and in the existing `scoreVsPlan` text, but they have not been tested together. The brain still stamps 15 days on a 5-day score. Anything beyond labels, such as a 5-day plan, a different exit date or a model matched to 15 days, stays blocked on the owner's choice of an option other than A.

## Not changed
- `today/SwingPicks.tsx:321` ("15D" badge), `:536` ("Trade setup (N days)") and `:553` ("Holding period: up to N trading days"): the "Holding period" line is already correct. The badge and title are ambiguous but fall outside the "Horizon" header ask, so they are reported, not changed. Follow-up for the owner: relabel the badge as "up to 15D hold".
- `horizons.ts`: its 15d tab is the plan window ("up to N trading days") and already says "up to". Unchanged.
- No numbers, decisions, exit dates, frozen files, chart files, `ui.tsx` or backend were touched.
