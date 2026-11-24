# #238 Verification: one 5-day large-cap idea across Today, Stock Detail and AI Analysis

Baseline commit: `5de3b9c` (main). Tests: `backend/tests/test_verify_238_5d_ideas_screens.py` (11 pass, 3 strict expected
failures) and `frontend/src/trademind/fiveDayIdeaScreens.test.ts` (8 pass, 2 expected failures). Tests and this note only: no
behaviour was changed. Written 2026-11-24 (IST). Nothing sensitive is in this note.

## In plain English

- **One decision, three screens.** For one fixed 5-day large-cap idea (a stored brain decision: TRADE, score 84, buy zone 100-101,
  target 108, stop 96, first reason "The market is calm and the stock is in an up-trend."), the idea list behind Today, the run
  behind AI Analysis, and the plain answers behind Stock Detail all return the **same stored decision**: same id, same run, same
  score, horizon, plan levels, word and first reason. The score line on Stock Detail ends on that same score and names the same
  model ("swing_classifier v2", a 5-session model). A Pro member sees the same score, horizon, levels, word and first reason; only
  the account's size is taken away.
- **The numbers shown are rounded one way.** Every screen turns the score into a whole number through one helper, and the
  day-by-day line rounds identically for every score from 0 to 1.
- **Missing pieces say so.** A stock the brain did not look at says "has not looked at this stock" with no plan and no money
  figures. A decision with a missing target gives "plan incomplete", never a zero. An old run is named as old.
- **Three gaps (none fixed):**
  1. **The horizon on the idea is 15 days, but its score comes from a 5-session model** (#385). The idea, and the "out by" day on
     Stock Detail, count 15 sessions.
  2. **Stock Detail's plan card prints percentages from the v1 settings** (`ML_TARGET_RETURN_PCT` etc.) next to a target price that is
     the Brain's own +8% plan. Where the settings differ (the v1 target setting can be overridden) the card can say +2% beside an
     +8% price. Fixed by #416 once it merges.
  3. **The word can differ between screens.** Today's counts and idea cards use the stored word; Stock Detail, AI Analysis and the
     ideas table use the stock verdict when only the test portfolio's room held the idea back. For the owner, such an idea reads
     TRADE on its stock page and WATCH on Today. A second, smaller one: for the owner the idea list serves the newest run of any
     book while Stock Detail's plain answers read the newest paper run.

## Findings table

| # | Question | Code (at `5de3b9c`) | Expected | Observed (test) | Result |
|---|---|---|---|---|---|
| a1 | Today and AI Analysis read one stored decision | `api/v1/endpoints/brain.py` (`/runs/latest`, `/runs/{id}`, `_decision_out`) | same row | `test_today_and_ai_analysis_read_the_same_stored_decision` | Pass |
| a2 | Stock Detail's plain answers carry that decision and plan | `services/beginner_views.py:stock_brief` (q2, q3) | same id, run, levels | `test_stock_detail_plain_answers_carry_the_same_decision_and_plan` | Pass |
| a3 | The score line is the same decision's score and names its model | `services/brain_score_trail.py` | last point = score; model named | `test_the_score_line_on_stock_detail_*` | Pass |
| a4 | A plan member sees the same facts | `api/v1/endpoints/brain.py:_decision_out` (non-owner) | same, size removed | `test_a_plan_member_is_shown_the_same_*` | Pass |
| t1 | The idea traces to its 5-session record (link = stock + date + score; no stored reference) | `services/horizon_nightly.py:record_prediction`, `db/models/horizon.py` | a correctly keyed record of the same stock, model version and score; horizon 5 | `test_the_idea_traces_to_its_five_session_record_*` | Pass |
| a5 | The "out by" day uses the decision's horizon from the run date | `beginner_views.py:stock_brief` | N trading days after the run | `test_the_last_exit_day_on_stock_detail_*` | Pass |
| a6 | One rounding for the score | `frontend/src/trademind/scoreText.ts:scorePoints`; `stockParts.tsx`, `HeldRead.tsx` | same whole number | `fiveDayIdeaScreens.test.ts` (0 to 1 in steps of 0.001; no screen keeps `confidence * 100`) | Pass |
| a7 | Stock Detail, AI Analysis and the ideas table share the word helper | `live.ts:shownWord` | one helper | `fiveDayIdeaScreens.test.ts` (source check) | Pass |
| m1 | Stock not in the run | `beginner_views.py:stock_brief` | says so, no plan | `test_a_stock_the_run_did_not_look_at_*` | Pass |
| m2 | A missing level | `beginner_views.py:_plan_in_order` | "incomplete", no zero | `test_a_decision_with_a_missing_level_*` | Pass |
| m3 | An old run | `beginner_views.py:_run_is_current` | named as old; list dated | `test_an_old_run_is_named_as_old_*` | Pass |
| h1 | The horizon the Brain stamps matches the model behind the score | `brain/modules/m08_decide/engine.py:177` (`horizon_days=policy.horizon_days`), `brain/contracts.py:245` (`Opinion.horizon_days`) | 5 | an opinion marked 5 sessions still gives a 15-day TRADE idea (derived from the real decision step, `decide_idea`) | **GAP 1** (#385) |
| h2 | The stock pages label the score a 5-day score | `frontend/src/trademind/stockParts.tsx` | "5-day model score"; plan worded as a separate rule | `test_the_decision_is_scored_by_a_five_session_model_*`, `fiveDayIdeaScreens.test.ts` | Pass |
| n1 | Plan percentages agree with the plan prices | `beginner_views.py:78, 506-516` (`settings.ML_*`) | from the Brain's plan | +2% beside a +8% price when settings differ | **GAP 2** (#416) |
| w1 | The word is the same on every screen | `live.ts:shownWord`, `live.ts:finalWord`, `beginner/IdeaCard.tsx:27` (`effectiveWord`) | one word | counts and cards use the stored word; stock pages use the stock verdict | **GAP 3** |
| w2 | Same run behind the list and the plain answers | `brain.py` (`service.latest_run`, newest of any book) vs `beginner_views.py:_latest_nightly` (paper only) | same run | differ when a live-book run is newest (owner) | **GAP 3b** |

## Gaps (strict expected failures / `it.fails`, none fixed)

1. **h1:** stamp the model's real horizon on the idea (or label the 15 as the plan's window). Test:
   `test_the_horizon_the_brain_stamps_on_an_idea_is_the_horizon_of_the_score_behind_it` (control: the API passes the stored
   horizon through unchanged).
2. **n1:** read the plan card's percentages from the Brain's plan (or from `GET /config/trading-rules`, #416). Test:
   `test_the_percentages_on_the_plan_card_agree_with_the_plan_prices`.
3. **w1:** use one word helper on every screen. Tests: `GAP: Today's idea counts agree with the word Stock Detail shows ...`,
   `GAP: Today's idea card word is the word Stock Detail shows ...`.
   **w2:** serve the owner the same run on both routes. Test:
   `test_the_idea_list_and_the_plain_answers_use_the_same_run_when_a_live_book_run_is_newest`.

## Cited, not tested here

- **Identity and horizon records (#448, #449, #451):** all three are on main at this baseline. One test follows the idea to its
  record: the nightly writer turns the model's stored 5-session prediction into a horizon record keyed by the stock's permanent
  id, with the model name and version, the prediction it came from and the horizon of the model (5). A stored decision carries
  no prediction or record id, so the link between an idea and its record is stock + date + score, not a stored reference; the
  test seeds both with the same score, so their equality is by construction. The record's horizon (5) is not the idea's (15),
  which is gap 1. The simulation and the other consumers of those records
  are verified by their own tests (`test_p0_acceptance.py`).
- **Which route each screen calls** is checked in the source: Today, Stock Detail, AI Analysis and the stock analysis page all
  use `useLatestRun`; Stock Detail's plain answers use `/beginner/stock/{symbol}`.
- **AI Analysis falls back to `GET /brain/why/{symbol}` for a stock the latest run lacks.** That route starts a fresh stored run,
  so its numbers can differ from the nightly run's; it was not called here.
- **AI Analysis shows a calibrated "chance" figure** where Today and Stock Detail show the model score as a ranking. They are two
  different numbers with two labels, by design (ux10); not a mismatch.
- **Numbers from the rules endpoint (#416):** the ratchet `frontend/src/trademind/noHardcodedRules.test.ts` on that branch pins
  the screens' trading numbers to `GET /config/trading-rules`; until it merges, gap 2 stays.
