# #254 Verification: do the weekly and paper/shadow reports match the stored rows?

Baseline commit: `5de3b9c` (main). Test database: `swing_trade_ml_dev3b_test`. Written 2026-11-24 (IST).
Tests and this note only. No frozen file, the sealed trial, a model or any report number was changed. Nothing sensitive is
in this note: no settings, keys, production data or real-account rows were read.

## In plain English

- **The weekly report's numbers match the stored rows.** Buys, sells, trades, wins, open positions, charges and profit were
  each worked out again from the database by a plain query and compared. They agree. A break-even trade is not counted as a
  win. Realized and open profit are shown side by side and never added together.
- **The week is cut at midnight India time.** A trade one second before or after midnight IST lands in the right week, for
  both orders and trades (tested on the four edge seconds around each end of the window).
- **Bot, Testing, the brain's paper slot and the h05 shadow lane stay apart.** Adding a Testing trade changes only the Testing
  figures; adding paper trades does not change the shadow counts, and the other way round. There is no combined total anywhere.
  Live-mode rows, the real-account book and rows from other modes never reach a paper figure. The route is owner-only.
- **The one profit definition holds where it is used.** For the same trades the weekly "Bot" profit equals the portfolio
  summary's realized profit and its win count, as long as the brain slot has not traded.
- **A week with no data says so in the full report** (a clear "no buys or sells this week", no average return, no NIFTY figure
  claimed) rather than showing zeros as results.
- **Four gaps, none fixed** (each pinned as an expected-failure test, see below):
  1. the Telegram message for an empty week still prints "0 buys, 0 sells, realized ₹0";
  2. once the brain's paper slot has traded, the weekly "Bot" figure and the portfolio summary's "Bot" figure disagree;
  3. the weekly report counts repeat-blocked picks as matured picks and hits, the lane's own report does not;
  4. a weekly report built for an earlier week also lists h05 events from later weeks.

## Findings table

| # | Question | Code (at `5de3b9c`) | Expected | Observed (test in `test_weekly_reports_reconcile.py` unless named) | Result |
|---|---|---|---|---|---|
| 1 | Counts equal the stored rows | `services/weekly_paper_report.py:collect, summarise_book` | buys, sells, trade rows, wins, open, charges, net equal a plain query | `test_every_count_in_the_week_equals_a_plain_query_of_the_stored_rows` (rejected and pending orders, out-of-window trades, a break-even trade) | Pass |
| 2 | Profit definition | `report_metrics.py` (`is_win`: more than zero), `weekly_paper_report.py:_pnl_block` | net = sum of stored nets; gross minus charges = net; zero is not a win | same test; `test_report_metrics.py` (cited) | Pass |
| 3 | Realized and open never summed | `summarise_book` | two separate figures | `test_realized_and_open_profit_are_never_added_together_in_the_report` | Pass |
| 4 | Same trades, same profit across reports | `services/portfolio.py:performance_stats` vs weekly | equal | `test_the_weekly_bot_figure_equals_portfolio_performance_stats_for_the_same_trades_without_a_brain_slot`; `test_report_metrics.py::test_all_paths_agree_on_the_same_round_trips` (cited) | Pass (no brain slot) |
| 5 | Dates by IST session | `collect` (`since`/`until` at midnight IST), `window` | cut at 00:00 IST | `test_orders_and_trades_are_cut_at_midnight_india_time_not_midnight_utc` (4 edge seconds); `test_the_week_has_seven_calendar_days_ending_yesterday_india_time` | Pass |
| 6 | Sources never mixed | `source_of`, `pick`, `brain_paper_section` | bot, testing, brain slot, h05 apart | `test_a_testing_book_trade_changes_only_the_testing_numbers`; `test_shadow_h05_rows_never_change_a_paper_figure_*`; brain seal: `test_weekly_paper_report.py` (cited) | Pass |
| 7 | Live, hand-book, other-mode rows excluded; no-strategy rows go to the bot | `collect` (`Order.mode == PAPER`, `HAND_BOOK_STRATEGY_NAMES`) | excluded; bot | `test_live_rows_hand_books_and_other_modes_never_reach_the_paper_report`; `test_a_row_with_no_strategy_belongs_to_the_bot_*` | Pass |
| 8 | Real-account rows hidden from non-owners | `api/v1/endpoints/weekly_report.py` (`require_owner`) | owner only | structural check in `test_the_report_endpoint_is_owner_only_*`; the second-owner refusals are #426's tests (cited, not re-tested) | Pass (cited) |
| 9 | h05 section counts | `weekly_paper_report.py:h05_section` | days, scored, picks equal stored rows; a pick with no result is not a zero; expected sessions are trading days inside the run | `test_the_h05_section_counts_equal_the_stored_rows_and_the_expected_sessions_are_trading_days` | Pass |
| 10 | h05 weekly vs the lane's own report | `h05_report.py:summarise_group` (`counted_picks` excludes `repeat_blocked`) | same pick and hit counts | equal with no repeats (`test_the_weekly_h05_hits_equal_the_lane_reports_counted_picks_*`); differ with one | **GAP 3** |
| 11 | Brain slot vs the portfolio summary | `weekly_paper_report.py:is_brain_strategy` keeps it out; `portfolio.py:performance_stats` has no brain filter (`outside_tester_book` drops only the Testing book) | one "Bot" figure | weekly 100 vs stats 800 with one brain trade | **GAP 2** |
| 12 | Empty week | `summarise_book` (`data_status`), `h05_section`, `benchmark` | says so | full report: yes (`test_an_empty_week_says_so_in_every_part_of_the_report`); Telegram message: prints zeros | **GAP 1** (message) |
| 13 | h05 events in the week | `h05_section` (`H05Event.signal_day >= start`, no upper bound) | that week's events only | an event 3 weeks later is listed | **GAP 4** |

Re-run for this note (dev3b): the new file plus `test_weekly_paper_report.py`, `test_report_metrics.py`,
`test_report_metrics_snapshot.py`, `test_real_report.py`, `test_h05_service.py` and `test_h05_job.py`: counts are in the
commit report.

## Gaps (strict expected-failure tests with `raises=AssertionError`, none fixed)

1. **Empty-week message:** the Telegram text for a week with no data reads like a result ("realized ₹0 after costs"). The
   full report has the plain "no buys or sells this week" status; the message should use it. Display only.
2. **Brain slot in the portfolio figures:** the weekly report keeps the brain's reserved paper slot out of "Bot" (owner rule:
   its own book). `performance_stats` (portfolio summary, Observatory) counts the brain strategy's paper trades in the same bot
   book, so the two "Bot" numbers diverge after the brain slot trades. Whether the sealed trial hides those figures elsewhere
   was not re-checked here. Fix needs the owner's call on where the brain slot belongs (it touches reported numbers).
3. **Repeat-blocked picks:** the weekly h05 section counts every selected pick that matured; the lane's report counts only
   non-repeat picks as "counted". The same week can show two different hit counts.
4. **Events with no upper bound:** only matters when a report is built for a past week (the scheduled job always runs for the
   week just ended), so low risk.

## Not covered here

Real-account (`real_report`) figures and their privacy (#426), the idea report and the brain health checklist (health checks,
not profit reports), and anything about the sealed trial's evidence. Production data was not read.
