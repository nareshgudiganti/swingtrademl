# Feature 3 (#228): requirements check against main

Checked 25 Nov 2026 (IST) on `origin/main` = 13b9c31b, in worktree `wt-228-v1`. Requirements are the #282 draft section 6.
Run: backend `test_verify_238_5d_ideas_screens`, `test_plan_percentages_from_brain_policy`, `test_trading_rules_endpoint`,
`test_quote_snapshot`, `test_verify_246_data_freshness`, `test_verify_240_quote_states`, `test_brain_caution_only`,
`test_what_would_change`, `test_brain_m01_quality`, `test_brain_evidence_verification` = 230 passed, 8 strict expected failures
(each one is a known gap). **Frontend tests were not run** (the worktree has no usable `node_modules`), so every item that needs
a frontend test says "not yet testable". The #282 draft is not yet approved by the owner.

| ID | Status | Evidence |
|---|---|---|
| A1 | pass | `test_today_and_ai_analysis_read_the_same_stored_decision`, `test_stock_detail_plain_answers_carry_the_same_decision_and_plan` (test_verify_238, run) |
| A2 | pass | `test_the_score_line_on_stock_detail_is_the_score_of_the_same_decision_and_names_its_model` (run) |
| A3 | not yet testable | `fiveDayIdeaScreens.test.ts` ("no screen rounds the score its own way") exists; not run here |
| A4 | not yet testable | `live.ts:32` `shownWord` returns `finalWord` (read); the screen tests in `fiveDayIdeaScreens.test.ts` not run |
| A5 | fail | strict xfail `test_the_idea_list_and_the_plain_answers_use_the_same_run_when_a_live_book_run_is_newest` (G3b, still a gap) |
| A6 | fail | strict xfail `test_the_horizon_the_brain_stamps_on_an_idea_is_the_horizon_of_the_score_behind_it` (G1, HOLD for owner decision D1) |
| A7 | fail (as written) | `test_the_percentages_on_the_plan_card_agree_with_the_plan_prices` run with `--runxfail`: plan card now gives 0.08 from the Brain policy and ignores the v1 +2% setting (the #498 fix works, `test_plan_percentages_from_brain_policy` 7 passed), but the test still fails because it expects 0.0746 (target price over the middle of the buy zone, tolerance 0.005). The strict xfail marker is stale. Needs a decision on how the percentage is measured (from the zone middle or the entry) |
| B1 | pass | `test_a_decision_with_a_missing_level_gives_no_plan_and_no_zeros_anywhere` (run) |
| B2 | pass (code read) | `beginner_views.py:491-495`: non-TRADE gives "no buy plan" and "No money figures". No named test; covered inside #238 tests |
| B3 | pass | `test_the_last_exit_day_on_stock_detail_counts_the_decisions_own_horizon_from_the_run_date` (run) |
| B4 | pass | `test_brain_caution_only.py` (run); held-back levels kept, size zero. #242 pinned test not located by name |
| B5 | pass | `test_the_decision_is_scored_by_a_five_session_model_and_the_screens_label_the_score_as_a_five_day_one` (run). The plan itself is still labelled 15 days, so the separate-rule wording depends on D1 |
| C1 | pass | `test_brain_evidence_verification.py` (run, all pass except 2 strict xfails that are G1 #385) |
| C2 | pass | `test_brain_caution_only.py` (run) |
| C3 | pass | `test_brain_evidence_verification.py` WATCH-to-"what would change" tests (run); the 16-real-refusals claim not re-counted |
| C4 | pass | `test_what_would_change.py`, `test_brain_what_would_change_api.py` (run first; second file not run) |
| C5 | pass | `test_no_risk_gate_gives_a_no_new_trades_banner...`, `test_an_owner_pause_and_stale_market_data_each_name_themselves_in_the_banner` (run) |
| C6 | not yet testable | #243 few-cases test (PR #487 merged) not located or run |
| D1 | pass | `test_quote_snapshot.py` and `test_verify_246_data_freshness.py` b1-b3 (run); `priceSnapshot.test.tsx` not run |
| D2 | not yet testable | `closeDate.ts` and a "closed on" label exist on main (#506); `verify240.test.tsx` GAP b1 (no snapshot, no date) is still `it.fails` (read, not run). Treat as partly open |
| D3 | not yet testable | Chart date (G5) and NaN (G6) are marked FIXED (#470, #486) in `verify240.test.tsx`; not run. PR #520 adds missing-day markers |
| D4 | pass | `test_verify_246_data_freshness.py` c1-c4 and `test_brain_m01_quality.py` (run) |
| D5 | fail | G8: strict xfail `test_d2_no_scan_runs_when_the_candles_are_stale_and_the_ingest_failed`; design only, engine file frozen |
| E1 | not yet testable | `live-system.test.ts` exists (frontend, not run); `test_a3`, `test_a4` in test_verify_246 passed (status sentence, ingest failure reported) |
| E2 | not yet testable | #385: PR #510 (read-only Models tab) is open and not merged; expanded scope on HOLD |

Counts (25 requirements): pass 14, fail 4 (A5, A6, A7, D5), not yet testable 7 (A3, A4, C6, D2, D3, E1, E2). Re-run the frontend tests before the owner signs.
