# #246 Verification: market data freshness and missing-data handling (parent #231)

Baseline commit: `5de3b9c` (main). Test database: `swing_trade_ml_dev1b_test`. Written 2026-11-23 (IST).
Tests and this note only. No ingestion, scan, risk, order or frozen code was changed.
New tests: `backend/tests/test_verify_246_data_freshness.py` (25 tests: 18 pass, 7 are strict expected failures that mark gaps).

## In plain English

The question: when price data is late, missing or corrected, does the app say so, and does it avoid acting as if the data were fresh?

- **Daily candles are handled well when they arrive.** A bar that arrives late has its real arrival time stored. A bar the provider
  later restates is stored as a correction (old and new values) and the newest value is the one read. A day with no bar shows up
  on the status page as "Market data hasn't updated since 27 Nov". If the day's download breaks, an alert is sent.
- **The Brain's quality gate (M01) and its dated reader are sound.** The reader never returns a bar later than the run's time, it
  reads dates in India time, and M01 marks a 12-day-old bar and a stock with no bars as not fresh. Rows that arrived after the run
  time are excluded.
- **The stock page never shows a stale price as live.** A quote that is old, from an earlier day, or from the future is labelled
  stale. With no quote it shows the last close with its own date. The screens use only this labelled view.
- **Seven gaps found (none fixed here):**
  1. **a7, a8: two places read candle times as UTC dates,** so a daily bar lands on the day before. The "to" date on the data
     coverage page (`/market-data/coverage`) is one day early in a UTC database. In the backtest every bar is shifted the same
     way, so nothing looks ahead inside a run; the real effect is at the edges of a window, where comparing a UTC label with an
     India date can drop the first or last bar. Display and research only; no live order uses them.
  2. **a9: late and corrected candles are recorded but no screen, API or report reads them back.** A correction does act at write
     time: it invalidates the stored feature snapshots from that bar's date (`test_candle_corrections.py:48`). The gap test
     checks imports only. The candle-ready and ingest-report work (#316 and #357) is not on main.
  3. **b6: a paper order can be priced from an old saved quote** even when a newer close exists. The stock page already refuses to do this.
  4. **b7: a quote with no price is saved as a fresh quote priced at 0.** Unlikely in practice (Kite quotes without a price are rare),
     but nothing stops it.
  5. **c7: two parts of the app disagree about which bar should exist at 4 pm.** The Brain's quality gate expects today's bar after
     15:40; the status page and the original scan treat yesterday's bar as the newest. Which is right depends on when the provider
     really publishes the day's bar, which the code comments say is not the same day (tracked in #316 and #353).
  6. **d2 (the main one): the original daily scan runs on whatever candle it has, however old,** and nothing upstream stops it, not
     even a failed download that morning. The new test proves only that NO freshness gate exists upstream (the engine is stubbed in it).
     That the engine then scores a stale bar is the finding already reported in #253 (b4, PR #462) and tracked as #344 and #353;
     it is cited, not re-tested.

## Findings table

| # | Question | Code (at `5de3b9c`) | Expected | Observed (test) | Result |
|---|---|---|---|---|---|
| a1 | A late bar: is its real arrival kept? | `services/ingestion.py:426` (`CandleArrival`, first arrival kept) | session date and arrival date both stored | `test_a1_*` (bar 10 days old arrives today: lateness 10 days is derivable); also `test_candle_arrivals.py` (3 tests) | Pass |
| a2 | A restated bar: logged as a correction? | `ingestion.py:394` (`CandleCorrection`, old and new OHLCV, `corrected_at`); the newest value is stored | one correction row, none for an unchanged re-fetch | `test_a2_*`; `test_candle_corrections.py` (2 tests) | Pass |
| a3 | A missed day: visible to a person? | `api/v1/endpoints/system.py:48` `_plain_status`, `:45` expected day | warning naming the last bar date | `test_a3_*` ("hasn't updated since 27 Nov", "never") | Pass |
| a4 | Ingest failure: reported, not swallowed? | `workers/jobs.py:396-459`, `:56` `_report_error` (alert + Admin > Jobs) | one error report | `test_a4_*` | Pass |
| a5 | Daily bars dated in IST where it matters | `services/quote_snapshot.py:80`, `brain/reader.py:99,186,299,311`, `system.py:208` | IST date of an IST-midnight stamp | `test_a5_*`, `test_c1_*`, `test_status_candle_date.py` | Pass |
| a6 | Any other `.date()` on a candle time without IST? | source scan of `src/swing_trade_ml` | none | `test_a6_*` pins the full list: the backtest (a8) plus two snapshot times that are not candles (`services/portfolio.py:236,738`, written mid-afternoon IST so UTC and IST dates agree). Limit: the scan matches the name `ts` (and `df['ts'].dt.date`), so a `.date()` on a differently named variable would not be seen | Pass (pinned, name-based) |
| a7 | Coverage page names the IST date of the newest bar | `api/v1/endpoints/market_data.py:250-251` (`.date()` on a UTC time) | `2026-12-01` for a bar stamped IST midnight 1 Dec | `2026-11-30` (skipped if the database session is not UTC) | **GAP** |
| a8 | Backtest places each bar on its IST day | `services/backtest.py:109,322,328,345,371-372` (`df['ts'].dt.date`, no conversion) | the 30 Nov close for 30 Nov | returns the 1 Dec bar's close (200.0 instead of 100.0). All days shift the same way, so no look-ahead inside a run; the effect is at window edges (`start <= date <= end` compares UTC labels with IST dates, so the first or last bar can drop) | **GAP** (window edges) |
| a9 | Late and corrected candles readable somewhere | `ingestion.py:394,426` write them; `invalidate_snapshots_for_candle_corrections` uses a correction at write time (`test_candle_corrections.py:48`) | at least one read path for people | no screen, API or report reads them (the test checks imports only) | **GAP** |
| b1 | Stale or future quote shown as live? | `quote_snapshot.py:123-131` (stale after 15 min, other day, or negative age) | state `stale` | 3 hours, 2 days and 1 hour in the future all give `stale` (`test_b1_*`); pure rules in `test_quote_snapshot.py` (15 tests) | Pass |
| b2 | Missing quote | `quote_snapshot.py:87` `_from_close` | last close with its date, never live | price 100.0 with its date, no time, a note (`test_b2_*`) | Pass |
| b3 | No quote and no candle | `quote_snapshot.py:172` `build_snapshot` | `no_data`, no price | `test_b3_*` | Pass |
| b4 | Raw quote endpoint | `market_data.py:72` | the quote's own timestamp, or 404 | `test_b4_*` (true age carried, 404 when none). It adds no stale label, but no screen calls it | Pass (limit noted) |
| b5 | Which endpoint do the screens use | `frontend/src/api/client.ts:628` | the labelled snapshot only | `test_b5_*` | Pass |
| b6 | Paper order price from an old cached quote | `brokers/paper.py:92-96` (any quote row wins over a newer candle close) | the newer close (the stock page's own rule, `test_old_stored_quote_does_not_hide_a_newer_close`) | 500.0 from a 5-day-old quote instead of 100.0 | **GAP** |
| b7 | A quote with no price | `ingestion.py:610` (`float(data.get("last_price", 0))`, then stored with `ts=now`) | not stored as a fresh quote | stored with price 0.0 (unlikely in practice: Kite quotes without a price are rare) | **GAP** |
| c1 | Dated reader never reads past `as_of` | `brain/reader.py:77-90,163,291,305,278` (`Candle.ts <= as_of`) | nothing after `as_of` | poison bars after `as_of` never appear in 5 readers, dates are IST (`test_c1_*`, `test_c2_*`, `test_c4_*` for the benchmark) | Pass |
| c2 | Side feeds cut at `as_of` | `reader.py:202` events by `created_at`; `:214,229,250` restrictions, delivery, deals by trading day | later rows excluded | `test_c5_*` | Pass |
| c3 | Limit: an intraday `as_of` sees that day's bar | `reader.py:77-90` (a bar is stamped IST midnight) | n/a | `test_c3_*` pins it: `as_of` 09:00 IST already includes that day's bar | **Observed limit** |
| c4 | M01 flags stale and missing data | `brain/modules/m01_quality/quality.py:55-116` | not fresh, low score, plain reason | `test_c6_*` (12 days old: not fresh, "trading days old"; no bars: score 0); `test_brain_m01_quality.py` (21), `test_brain_m01_module.py` (4), `test_bad_data_drills.py` (30 incl. the DB drills) | Pass |
| c7 | M01 and the status page agree on the expected bar (`test_c7_*`) | `quality.py:23,42-48` (`INGEST_DONE` 15:40, today's bar) vs `system.py:45` (previous trading day, all day) | the same day at 16:00 IST on a trading day | M01 says 1 Dec, the status page says 30 Nov | **GAP** |
| d1 | Any gate between ingest and scan | `workers/scheduler.py:135` (15:40), `:141` (15:42), `:152` (scan) are independent cron jobs; `jobs.py:500-556` `job_signal_scan` | a check of data age or the ingest result | none: the scan code mentions neither (`test_d1_*`); no data-quality job exists in `workers/` | **No gate** |
| d2 | Scan after a failed ingest with 12-day-old candles | `services/engine.py:136` loads the newest candles, `:140` `evaluate`, no age check; cited as #253 b4, tracked #344 and #353 | no scan, or no BUY from an old bar | the scan runs (`calls == ['day']`, engine stubbed): this proved that no freshness gate existed; the engine scoring the stale bar is #253 (PR #462) | **FIXED** by #316 (PR #548): the scan waits for validated candles, no scan runs |

## Gaps for the owner (one line each, none fixed)

- **a7 / a8:** read candle times in India time in `market_data.py:250-251` and `backtest.py` (five places); display and research only (in the backtest the effect is at window edges, not a look-ahead).
- **a9:** nothing reads late or corrected candles back; the ingest report (#357) would be the reader.
- **b6:** a paper order can be priced from an old saved quote; use the same rule as the stock page (newer close beats an old quote).
- **b7:** do not save a quote that has no price.
- **c7:** settle once whether the day's bar exists after 15:40 or only the next morning, and make M01, the status page and the scan use one definition (#316 and #353).
- **d2:** the version 1 scan should refuse a bar older than the last closed session and not run when the day's ingest failed (frozen engine; needs the owner's approval; #344 and #353).

## How the gap tests work

Each gap is a test that states what the code SHOULD do and is marked `xfail(strict=True, raises=AssertionError)`. They fail today for the
stated reason (checked with `--runxfail`). If a gap is fixed the strict marker turns the test red, and the marker is then removed on purpose.
a7 and a8 skip themselves if the test database session is not in UTC, because the defect needs a UTC session.

## Not covered here

Real brokers, the live Kite feed, production and the owner's accounts were not touched. The late-candle guard, download report and scan
readiness work (#316, #357, #353) is on other branches and not on main, so it is not judged here. The `/ready` and `/status` routes are
read for freshness wording only; their access rules are covered by other notes.

Re-run for this note (dev1b): the new file plus `test_candle_arrivals.py`, `test_candle_corrections.py`, `test_quote_snapshot.py`,
`test_status_candle_date.py`, `test_brain_m01_quality.py`, `test_brain_m01_module.py`, `test_bad_data_drills.py` and `test_asof_reader.py`:
**131 passed, 7 xfailed** (the seven gaps).
