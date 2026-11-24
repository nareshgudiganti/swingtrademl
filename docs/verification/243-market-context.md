# #243 Verification: market, sector and similar-case context

Baseline commit: `5de3b9c` (main). Test file: `backend/tests/test_market_context_verify.py` (23 pass, 6 strict expected
failures). Test database: the developer's own `_test` database; every row rolls back. Tests and this note only: nothing in the
Brain, scoring, frozen files, models or the sealed trial was changed. Nothing sensitive is in this note.

## In plain English

- **Nothing from the future reaches the market view.** The Brain reads NIFTY, India VIX and the foreign-investor flows only up
  to the run's date. A test builds a database where NIFTY drops 50% the day after the run: the judgement for the run date is the
  same as when the later days are calm. The run's own day is counted; the next day is not. (Daily bars are stamped at IST midnight, so a run dated at 09:00 IST
  already contains that day's bar: runs are meant to be dated after the close.) Same for sector rankings (a later
  surge in the weakest sector does not move a past ranking) and for the table of similar past cases (a case is used only once its
  outcome was known; a case never describes its own starting day).
- **When the market data is missing the Brain stays careful, with two exceptions.** With no NIFTY data, or fewer than 200 days,
  it says "not enough NIFTY history" and stays DEFENSIVE. A missing FII feed is said in words. But a missing breadth figure or a
  missing VIX is **not said**, and a rising market with no breadth data is judged NORMAL (a narrow market would have been
  DEFENSIVE). That is the one place where missing data can make the Brain bolder (gap 1).
- **Sector strength is computed correctly, and named on the card** ("Sector: Banks, ranked 3 of 15, improving"). Every sector index
  the stock map uses has a plain name. But three things about the "strongest sectors" idea are not as the owner decided on
  2026-10-09: the gate that holds back ideas from weak sectors is **off by default** (gap 3); when it does hold an idea back
  its message always says "of 15" and does not name the sector (gap 4); and an idea whose sector could not be ranked passes
  the gate silently (gap 5). The "top 5 a day" is a cut where lists are drawn (Today screen and the daily digest agree on 5); the
  Brain itself keeps every idea.
- **Similar cases:** shown only with at least 30 cases; below that the card gives no rate and the "similar cases lost money" rule
  stays silent. The count, the hit rate, the honest figure and the expected result on the card are the same numbers the Brain's
  rule used. A match that had to be loosened says which part it dropped.
- **Breadth looks at today's watchlist** (gap 2): which stocks counted on a past date is not recorded, so adding a stock to the
  watchlist changes breadth for days already judged.

## Findings table

| # | Question | Code (at `5de3b9c`) | Expected | Observed (test) | Result |
|---|---|---|---|---|---|
| m1 | Market series end at the run date | `brain/reader.py:278` (`_closes`, `ts <= as_of`), `:347` (`fii_net`, `trade_date <= upto`) | nothing after the run date | `test_market_series_end_at_the_run_date_and_a_later_crash_changes_nothing`, `test_the_run_day_itself_is_included_and_the_next_day_is_not`, `test_fii_flows_stop_at_the_run_date` | Pass |
| m1b | A run dated early in the morning | `brain/reader.py:278` (bars stamped IST midnight) | a run is dated after the close | `as_of` 09:00 IST already includes that day's bar (`test_a_run_dated_early_in_the_morning_*`) | Observed: dating a run before the close sees a bar the market has not made |
| m2 | Breadth cut at the run date | `brain/reader.py:338`, `ml/market_context.py:137` (`upto`) | only closes up to the date | `test_breadth_for_a_run_date_uses_only_closes_up_to_that_date` | Pass |
| m3 | Breadth universe is point in time | `ml/market_context.py:158` (`is_watchlisted` now) | same value for a past day | adding a watchlisted stock later changes it | **GAP 2** |
| m4 | No data, short history | `brain/modules/m10_market/judge.py:69` | DEFENSIVE, said | `test_no_market_data_at_all_*`, `test_a_199_bar_index_history_*` | Pass |
| m5 | FII feed missing | `judge.py:137-` (`flow_note`) | said in words | `test_missing_fii_data_is_said_*` | Pass |
| m6 | Breadth or VIX missing | `judge.py:61-100` (`_raw`), `services/deployable.py:90` | said, never bolder | rising market, no breadth: NORMAL, no mention; same for VIX | **GAP 1** |
| m7 | Crash day, VIX spike, confirmation day | `judge.py:137-` | NO NEW TRADES; relax only after two days | `test_a_crash_day_or_a_vix_spike_*` (and the existing `test_brain_m10_judge.py`) | Pass |
| s1 | Sector ranking is point in time | `brain/reader.py:323`, `m11_sector/ranking.py:71` | a later surge changes nothing | `test_sector_ranking_ignores_everything_after_the_run_date` | Pass |
| s2 | The sector is named | `ranking.py:29`, `:89`, `:92` | plain name, rank, of how many | `test_every_sector_index_the_stock_map_uses_has_a_plain_name_on_the_card` | Pass |
| s3 | Gate holds weak sectors back | `m08_decide/rules.py:89` | outside top N: WAIT, with the rank | `test_the_sector_gate_waits_an_idea_outside_the_top_n_*`, `test_the_sector_gate_is_off_when_the_setting_is_zero` | Pass |
| s4 | "Strongest sectors by default" (owner, 2026-10-09) | `core/config.py:255` (`BRAIN_SECTOR_GATE_TOP_N: int = 0`) | on by default | default is 0 (off) | **GAP 3** |
| s5 | Gate message | `rules.py:97-99` | real total, sector named | says "of 15" always, no sector name | **GAP 4** |
| s6 | Unranked sector | `rules.py:93` (`f.sector_rank is None` returns no proposal) | not passed silently | passes silently | **GAP 5** |
| s7 | Top 5 a day | `services/ops_digest.py:36`, `frontend/src/trademind/today/TodayIdeas.tsx:22`, `m08_decide/module.py` | one number | both 5; the decision step sets no cap | Observed: display cut only |
| c1 | A case is known only after its outcome | `m05_memory/cases.py` (`outcome_day = days[i + k]`), `recall.py:38` | outcome day after the start day; used only when known | `test_a_case_is_known_only_after_its_own_outcome_day_*`, `test_recall_uses_only_cases_whose_outcome_was_known_*` | Pass |
| c2 | Experience table read to the run date | `brain/reader.py:314`, `m05_memory/store.py:load_experience` | `outcome_day <= date` | `test_the_experience_table_is_read_only_up_to_the_run_date` | Pass |
| c3 | Few cases | `m08_decide/engine.py:67-100`, `rules.py:74`, `policy.py` (`min_similar_cases = 30`) | no rate below 30 | no "Similar cases" line, the rule stays silent at 29 | Pass |
| c4 | Screen equals Brain | `engine.py:_evidence`, `recall_r` | same count, rate and expected result | `test_the_card_line_carries_the_same_count_and_rate_the_brain_used` | Pass |
| c5 | Loosened match is said | `recall.py:80-` (`widened`) | names the dropped part | `test_a_widened_match_says_which_parts_were_dropped` | Pass |

## Gaps (strict expected failures with `raises=AssertionError`, none fixed)

1. **m6:** say a missing breadth or VIX in the reasons, or stay DEFENSIVE; never let missing data lift the mode.
   Tests: `test_missing_breadth_or_vix_is_said_in_words_or_keeps_the_brain_careful[breadth|vix]`.
2. **m3:** read the stocks of a past date from the point-in-time list that already exists: the Brain's own universe for a replay
   uses `watchlist_as_of` and the `watchlist_snapshots` table (`brain/universe.py:43`, `services/watchlist_snapshots.py`), while
   the breadth loader (`ml/market_context.py:158`) reads `is_watchlisted` as it is today. No new record is needed, only to use
   that source. Test: `test_breadth_for_a_past_day_does_not_change_when_the_watchlist_changes_later`.
3. **s4:** switch the sector gate on by default (the 2026-10-09 proposal was top 3, the decision text says strongest sectors);
   needs the owner's approval, replay testing and the plan's step 2. The code default is 0 and the setting is absent from
   `docker-compose.yml` and `.env.example`, but production may set it in its environment file: **the production value was not
   read** and is unknown. Test: `test_the_strongest_sectors_gate_is_on_by_default`.
4. **s5:** the gate reason should say the sector's name and its real "of N". Test:
   `test_the_gate_reason_names_the_sector_and_the_real_total`.
5. **s6:** an idea with no sector rank should be said (and held back while the gate is on), not passed silently. Test:
   `test_an_idea_with_no_sector_rank_does_not_pass_the_gate_silently`.

## Not covered here

The market-quality check (M01) that stops new trades when NIFTY data is stale is a separate module with its own tests. The
screens were read, not run: the Today and stock pages build their similar-case record from the same evidence text that the test
checks. The honest-figure reliability weight (0.25) is the Brain's own evidence and is not re-measured.
