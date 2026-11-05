# Index availability at the decision time (SX5 / SX10 preparation) — 2026-11-05

Question: the decision for day t uses index closes dated <= t and enters at the next open. Is the official index value of day t actually stored before the decision time of the daily jobs? No model was trained and nothing was written to any database for this note (local SELECTs and code reading only).

## VERIFIED from code

| Item | Finding | Where |
|---|---|---|
| Who ingests the daily candles | One job, `job_daily_ingest`, Monday to Friday **15:40 IST**: (1) all watchlisted stocks (`backfill_watchlist`), (2) **NIFTY 50** (`backfill_index`), (3) the **16 context indices** = the sector indices and INDIA VIX (`backfill_context_indices`), then the in-process index cache is cleared, then other strategies' symbol lists. Stocks and indices therefore come from the same job, the stocks first | `workers/scheduler.py` lines 122-127, `workers/jobs.py` `job_daily_ingest` |
| Order inside the job | A stock call is followed by a 0.35 s pause (Kite rate limit). The watchlist is about 306 stocks, so the stock part alone is at least about 107 s before NIFTY 50 and the sector indices are even requested. Real durations are UNKNOWN | `services/ingestion.py` `RATE_LIMIT_SLEEP`, `job_daily_ingest` |
| Jobs that follow | `predict_watchlist` 15:42, `signal_scan` 15:45 (config `SIGNAL_SCAN_CRON_*`), `sync_real_holdings` 15:48, `brain_nightly` 15:50, `daily_summary` 16:00. The scheduler is a thread pool (`max_instances=1` per job, not a global lock), so these can start while the ingest is still running. The v1 scan therefore may see index data of day t-1 for the index-based inputs (the code even clears its cache only at the end of the ingest). Not relevant to the research path below, but relevant to anyone who reuses the research rule in serving | `workers/scheduler.py` |
| Later jobs | `daily_market_feeds` 19:20, `company_filings` 19:40, `daily_market_feeds_final` 22:05; **h05 lane 07:30, 08:30, 18:30, 20:30, 22:30** (`h05_job.SCHEDULE`, disabled by default); shared shadow lane Monday to Saturday 18:45, 20:45, 22:45 (`lane_job.SCHEDULE`, disabled by default). All of these run 2h50m or more after the 15:40 ingest | `brain/lanes/h05_job.py`, `shadow_lanes/lane_job.py` |
| Repo's own definition of "final" | `core/market_session.SESSION_FINAL = 15:40 IST`; `last_closed_trading_day(now)` is the latest day "whose daily bar can no longer change", i.e. today only from 15:40 on a trading day. The h05 job uses it | `core/market_session.py` |
| Partial bars | The ingest does **not** refuse a bar for the current day: `backfill_instrument` requests `from = newest stored bar - 1 day` to `now` and upserts whatever Kite returns. A run during market hours (manual API call `market_data` backfill or the CLI) would therefore store a partial day bar. The next run re-fetches the last bar and overwrites it; a changed bar is logged in `candle_corrections`, and the first arrival time of each bar is kept in `candle_arrivals` (audit F-07). There is no "final" flag on a candle | `services/ingestion.py` `backfill_instrument`, `_upsert_candles` |
| Sector builder | `build_sector_features(..., as_of=t)` cuts every input at t. The calendar is the union of NIFTY 50 and sector-index dates; a missing close is carried forward at most once (`MAX_FFILL = 1`). So a missing NIFTY 50 bar on day t would be a one-day stale carry-forward, not an error. This was the gap the new rule below closes | `ml/sector_features.py` |

## VERIFIED from the local database (SELECT only)

- All index daily candles (NIFTY 50, 15 sector indices, NIFTY CHEMICALS, INDIA VIX) are stamped IST midnight (0 of every index's bars have a non-midnight IST time), so `.astimezone(IST).date()` gives the trading date.
- Only `interval='day'` exists for the indices (no intraday rows to mix in).
- Last dates: stocks 2026-09-07 (303 of 306; 1 at 09-04; 2 at 08-12), **NIFTY 50 2026-09-07**, the sector indices and INDIA VIX **2026-09-09**. So in the local copy the sector series run two sessions beyond NIFTY 50 and the stocks: the series are not always topped up together. No eligible training row is affected (rows end 2026-08-31).
- NIFTY 50 and the sector indices have no open-equals-high-equals-low (placeholder) bars except **NIFTY CAPITAL MKT: 786 bars with high = low between 2021-09-13 and 2024-11-08** (close-only data in that period). The sector inputs use closes only, so this does not change them; range-based features of that index would be wrong in that period.
- NIFTY HEALTHCARE has 1,228 bars against 1,240 for the other sector indices (12 missing sessions), which is why APOLLOHOSP loses 15 rows.
- `candle_arrivals` has **0 rows** and `candle_corrections` has **0 rows** locally.

## UNKNOWN (cannot be known from this machine)

- **U1** The real arrival time of day t's index bars on prod (the `candle_arrivals` table is empty locally; prod was not queried, and `/brain/*` sealed routes must not be read).
- **U2** Whether Kite returns the settled closing value of a sector index for day t at 15:40 IST (the final index values come from the exchange after the close; the repo treats 15:40 as final, but that is a convention, not a measurement for indices).
- **U3** How long the 15:40 job really takes on prod, i.e. whether NIFTY 50 and the sector indices are stored before 15:45/15:50.
- **U4** Whether the backfilled history in the local database (used for training) equals what a live 15:40 run would have stored on that day (a bar could have been stored partial and corrected the next day; with no arrival or correction rows locally this cannot be checked).

## Recommended rule for the research path (IMPLEMENTED for the as-of builder; PROPOSED for any future serving)

1. Features for decision day t exist only if the stock **and** NIFTY 50 **and** the stock's own sector index each have a bar dated exactly t (otherwise: no row, never a stale carry-forward). Implemented in `sector_research.assemble_asof_row` with tests.
2. When a clock is supplied, t must satisfy `t <= last_closed_trading_day(now)` (not before 15:40 IST on a trading day), because a bar stored earlier may be partial. Implemented (`now=` argument) with tests; research replays pass no clock.
3. Any daily research or lane job should be scheduled after the 15:40 ingest finishes (existing lane jobs at 18:30 and later already are) and should log the bar count per index for day t.
4. Before any forward use: read `candle_arrivals` on prod (read-only) for several recent days and record the real arrival times of NIFTY 50 and the 15 sector indices; if any day's index bar arrived after the intended decision time, the rule in 1 and 2 must be tightened to that time. This closes U1 to U4 only partly (U2 and U4 stay open).
