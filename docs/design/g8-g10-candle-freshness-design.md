# G8 / G9 / G10 candle freshness: design only

Status: DRAFT for owner review. Design only: no code, no migration, no engine change, no production query.
Written 2026-11-25 (IST) against `origin/main` 13b9c31b. All engine, migration and trial-behaviour changes stay on HOLD.
Candle times are stamped IST midnight (18:30 UTC the previous day); every date below means `.astimezone(IST).date()`.
Paths are under `backend/src/swing_trade_ml/` unless stated.

## 1. Current behaviour (file:line)

Schedule (`workers/scheduler.py`): `daily_ingest` 15:40 IST (:133-135), `predict_watchlist` 15:42 (:139-141), `signal_scan` at
SIGNAL_SCAN_CRON_* (default 15:45) (:152). These are independent cron jobs; nothing passes the ingest result to the scan.

- `workers/jobs.py:500` `job_signal_scan` calls `engine.run_all_active` with no check of data age or of the ingest result.
- `services/engine.py:136` `load_candles(... limit=min_bars+50)` takes the newest bars it has (`ml/dataset.py:42`, ordered by ts, no date bound);
  `:140` `impl.evaluate(df, ...)` runs with no check that the last bar is the expected session. A 12-day-old bar is scored as if current.
  This is gap d2 in `docs/verification/246-data-freshness.md`.
- A failed ingest is reported (`workers/jobs.py:56` `_report_error`, alert plus Admin > Jobs) but does not stop the scan.
- `services/ingestion.py:344` `_upsert_candles`: overlapping windows are re-requested by design; `:412` `ON CONFLICT (instrument_id, interval, ts) DO UPDATE`.
  Late or restated bars are overwritten, but `:394` writes a `CandleCorrection` (old and new OHLCV, `corrected_at`) and `:426` writes a
  `CandleArrival` (first `received_at`, `DO NOTHING`). `invalidate_snapshots_for_candle_corrections` (:433) drops feature snapshots from the corrected bar.
  Models: `db/models/market.py:116` and `:138`.
- Brain path: `brain/modules/m01_quality/module.py:44` calls `expected_bar_day(as_of)`; `quality.py:23` `INGEST_DONE = 15:40`, `:42-48` expects
  TODAY's bar after 15:40 on a trading day, else the previous trading day. `assess_bars` marks a stock not fresh when `behind != 0` or score is under 0.6 (`quality.py:113`).
  The market is not fresh if the benchmark is stale or more than 20% of stocks are (`quality.py:125-144`, MAX_STALE_SHARE :29).
  `brain/constitution.py:59` makes unfresh overall data a NO NEW TRADES reason; `:84` downgrades a TRADE to WATCH for that stock. The Brain already fails closed.
- v1 path: `core/market_session.py:186` `expected_latest_trading_day` is the previous trading day ALL day, because "Zerodha doesn't publish a day's own historical
  candle same-day" (docstring :187-193). Used by `api/v1/endpoints/system.py:75` (status page) and `services/beginner_views.py:379`.
- Contradiction (gap c7): M01 expects today's bar after 15:40; the status page expects yesterday's. Both cannot be right; G9 evidence decides.
- Calendar: `core/holidays.py:18` `NSE_HOLIDAYS` per year (compiled 2026-08-05); `core/market_session.py:60-80` `is_holiday / is_trading_day / previous_trading_day`;
  `:198` `calendar_warning` flags a missing year. No Muhurat or special-session handling exists.
- Historical data is never deleted or filtered by age; backtests and training use all rows. The gate must not change that.

## 2. Proposed gate rules (calendar-based, no hour cut-offs)

Definition. `expected_bar_day(now)` = the latest trading day D (from the exchange calendar) whose candle is KNOWN to have been published by `now`.
"Known" comes from G9 evidence (observed publication per session), not from a clock constant. Until G9 evidence exists the conservative value is the
one the code comment states: `previous_trading_day(today)` (`core/market_session.py:186`). If G9 shows same-day publication is reliable, the rule becomes
"today's bar once published", using the observed arrival, never a fixed 4 PM.

A new signal run for an instrument is allowed only if ALL hold, evaluated per run with the calendar:
1. Present: a daily candle exists whose IST date equals `expected_bar_day`.
2. Valid: OHLC ordered (low <= open, close <= high), prices > 0, no NaN, volume >= 0, timestamp is IST midnight of a trading day.
3. Not stale: IST date of the newest bar >= `expected_bar_day`. Staleness is counted in TRADING days via `trading_days_between`, never in hours.
4. Calendar sound: `calendar_warning()` is None for the run year; otherwise "trading day" cannot be trusted and new signals fail closed.
5. Market-wide: the benchmark (NIFTY) candle passes 1-3, and no more than the existing 20% of the universe is stale (reuse M01's share, no new number).
6. Ingest outcome: the ingest record for the session (section 5, `ingest_runs`) shows `complete`, not `failed` or `partial`.

## 3. Fails closed vs warns

Fails closed (no NEW signal or entry; exits, stops and existing positions keep working; decisions only move toward caution):
- expected bar missing, invalid, or older than `expected_bar_day`; benchmark stale; failed ingest; holiday list missing for the year;
  a correction that arrived after the signal run for the same session (that signal is marked void, section 5).

Warns only (recorded and shown in plain English, no block):
- zero volume, a one-day gap inside history, a spike over the existing M01 threshold, a bar re-confirmed unchanged, a correction to a bar older than the
  lookback window, old rows with no arrival time (unknown, not "on time").

Historical data: never deleted or edited by the gate. Old rows that fail checks are kept and flagged with a warning record.

## 4. G9 evidence

Found in code (these show what we record, not when the provider publishes):
- `candle_arrivals.received_at` is OUR first ingestion time per bar (`services/ingestion.py:426`, `db/models/market.py:138`). Rows from before the table existed have none.
- A code comment (`core/market_session.py:187-193`) says Zerodha does not publish the day's historical candle the same day. No timestamped proof is in the repo.
- `brain/modules/m01_quality/quality.py:23` and `workers/scheduler.py:127-129` assume 15:40 is "settled". `docs/verification/246-data-freshness.md` (c7) records this as unresolved (#316, #353).
- NOT found: any provider-side publication timestamp. The Kite historical call returns the candle time only, not when it became available. No Groww candle client was found that gives one.
- Local dev DB: `DATABASE_URL` is not set in this session, so nothing was read. Nothing was queried in production.

Status: EVIDENCE MISSING. Exact request to the owner (read-only exports, no secrets):
1. From the production database, for the last 20 trading sessions, one row per (symbol, session): `instruments.tradingsymbol`, the IST date of `candles.ts`,
   `candle_arrivals.received_at` converted to IST, and whether a `candle_corrections` row exists (with `corrected_at`). Ten symbols including NIFTY.
   Shape: `candle_arrivals` joined to `instruments`; no other columns.
2. The scheduler log lines `job.ingest.done` and `job.ingest.index_done` with IST timestamps for the same 20 sessions (symbols and bar counts).
3. Going forward (needs approval): a record-only probe that asks the provider for the day's bar every few minutes after 15:30 IST for 10 sessions and logs the
   first time it appears. Only this gives the PROVIDER publication time; arrival data alone is an upper bound.

How the evidence is used: "today's bar" is allowed as the expectation only if, across the sample, the latest observed first-seen time is earlier than the earliest
planned run time, with a margin the owner chooses. No fixed hour is assumed.

## 5. G10 validation and audit

Current: duplicates cannot exist (primary key); corrections are logged; first arrival is kept; missing sessions are detected only indirectly (M01 `gap` penalty,
status page). Nothing reads corrections or arrivals back (gap a9). There is no session-completeness check against the calendar.

Proposed validation rules:
- Duplicate: same (instrument, interval, ts) re-delivered identical -> `duplicate_unchanged` event, no correction row.
- Late: first arrival after the expected publication for that session (per G9) -> `late`, with lateness in trading days and minutes.
- Corrected: values differ -> existing `candle_corrections`, plus classification (price or volume only), size of change, and whether a signal for that session had already run.
- Missing session: a calendar trading day between the first and last stored bar with no bar -> `missing_session`; a bar on a non-trading day -> `unexpected_session`.
- Invalid: fails rule 2 of section 2 -> stored as received, flagged, excluded from signals.
- Timestamp not IST midnight -> `bad_timestamp`.

Proposed audit table (TEXT ONLY, NEEDS OWNER APPROVAL, no migration written): `candle_audit_events`
`id, instrument_id, interval, session_date (IST date), event_type (late | corrected | duplicate_unchanged | missing_session | unexpected_session | invalid | bad_timestamp | ingest_failed),
provider, provider_published_at (nullable; only if the provider gives it), received_at, detected_at, ingest_run_id, old_values (json, nullable), new_values (json, nullable),
signal_run_affected (bool), severity (warn | block), note`.
Plus `ingest_runs` (NEEDS OWNER APPROVAL): `id, started_at, finished_at, interval, symbols_requested, symbols_ok, symbols_failed, bars_written, status (complete | partial | failed)`,
so the gate can read rule 6. `candle_corrections` and `candle_arrivals` stay unchanged.

## 6. Frozen-file list (`backend/tests/trial_freeze.json`, 98 files; changes need owner approval via `scripts/approve_trial_change.py`)

Frozen files a G8/G10 build could touch (paths under `backend/src/swing_trade_ml/`):
- `services/engine.py` (a gate at :136 would live here)
- `brain/modules/m01_quality/quality.py` and `brain/modules/m01_quality/module.py` (expected-day rule, INGEST_DONE)
- `brain/constitution.py`, `brain/reader.py`, `brain/service.py` (only if reason text or reads change)
- `strategies/ml_swing.py`, `strategies/base.py`, `ml/predict.py` (only if the check moves into strategies)

Not in the freeze list (still need owner go): `core/market_session.py`, `core/holidays.py`, `services/ingestion.py`, `workers/jobs.py`, `workers/scheduler.py`,
`db/models/market.py`, `api/v1/endpoints/system.py`, new audit modules.

Frozen-file-free option: put the gate in `workers/jobs.py` `job_signal_scan` (the existing comment at :512 already keeps work "out of services/engine.py") so the
whole scan is skipped, leaving the engine untouched. This STILL changes trial behaviour.

## 7. Trial-sensitivity list

- Any gate in `job_signal_scan` or the engine: on a stale day the v1 scan produces no signals where today it would. Directly changes which trades happen.
- Changing M01 `expected_bar_day` / `INGEST_DONE`: changes which stocks are "fresh" between 15:40 and the next morning, so Brain TRADE vs WATCH changes on those days.
- Aligning M01 with the status page (c7), in either direction, moves the freshness result for every stock in that window.
- Audit tables, `ingest_runs`, read-backs and the G9 probe are record-only (no decision change), but a migration needs approval.
- Voiding a signal after a correction changes outcomes only on days a correction occurs.
- Direction check: every proposed block moves toward caution; no rule loosens anything.

## 8. Questions for the owner

1. Will you run the G9 exports in section 4 (agents may not query production)? Which 10 symbols?
2. Approve a record-only probe job to measure provider publication time over 10 sessions?
3. Until evidence exists, which is the interim truth for the day's bar: the previous trading day (status page) or today's bar after 15:40 (M01)?
4. Where may the gate live: `job_signal_scan` (frozen-file-free, whole scan skipped) or the frozen engine/M01? Either needs a trial-change approval.
5. On a stale day, skip the whole v1 scan, or only the instruments with stale bars?
6. Approve the `candle_audit_events` and `ingest_runs` shapes (schema only; migration is a separate approval)?
7. A correction arrives after a signal ran: void the signal, or only warn?
8. Special sessions (Muhurat, weekend sessions) are not in `core/holidays.py`; who maintains them, and should a missing list fail closed (rule 4)?
9. After how many trading days may a missing bar be accepted as "provider will never publish" (halted stock) so the stock is simply excluded?
